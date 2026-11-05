"""Unit tests for accept --run-id observation promotion path."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from promptdrift.cli import app
from promptdrift.engine.baseline import load_baseline
from promptdrift.errors import BaselineError, PromptDriftError
from promptdrift.models import Config
from promptdrift.models.baseline import Baseline
from promptdrift.models.monitor import Diagnosis, MonitorCase, MonitorReport
from promptdrift.models.provenance import Provenance
from promptdrift.storage.history import history_path, load_monitor_run_by_id, save_monitor_report


@pytest.fixture
def test_project(tmp_path: Path):
    config_data = {
        "version": 2,
        "project": {"name": "test-accept-project"},
        "provider": {"type": "mock", "model": "echo"},
        "baseline": {"path": "promptdrift.baseline.json"},
        "tests": [
            {
                "id": "greeting",
                "prompt": "prompts/greeting.txt",
                "variables": {"name": "World"},
                "assertions": [{"type": "contains", "value": "Hello"}],
            },
            {
                "id": "farewell",
                "prompt": "prompts/farewell.txt",
                "variables": {"name": "World"},
                "assertions": [{"type": "contains", "value": "Goodbye"}],
            },
        ],
    }
    config_file = tmp_path / "promptdrift.yaml"
    config_file.write_text(json.dumps(config_data), encoding="utf-8")

    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "greeting.txt").write_text("Hello, {{ name }}!", encoding="utf-8")
    (prompts_dir / "farewell.txt").write_text("Goodbye, {{ name }}!", encoding="utf-8")

    loaded_config = Config.model_validate(config_data)
    return loaded_config, config_file


def _create_sample_monitor_report(
    run_id: str = "test-run-1234",
    status: str = "PASS",
    diagnosis: Diagnosis = "stable",
    failures: int = 0,
    output_hash: str | None = None,
    config: Config | None = None,
    config_path: Path | None = None,
) -> MonitorReport:
    out_hash = output_hash or hashlib.sha256(b"Hello, World!").hexdigest()
    if config is not None and config_path is not None:
        from promptdrift.engine.provenance import fingerprint
        from promptdrift.engine.suite import resolve_suite
        from promptdrift.templates import render_prompt

        active, _ = resolve_suite(config, config_path)
        prov_map = {}
        for t in active.tests:
            p_text = render_prompt(active.resolve_path(config_path, t.prompt), t.variables)
            prov_map[t.id] = fingerprint(active, t, p_text)
        prov_greeting = prov_map.get("greeting")
        prov_farewell = prov_map.get("farewell")
    else:
        prov_greeting = prov_farewell = Provenance(
            input_hash="hash_in",
            provider_hash="hash_prov",
            configuration_hash="hash_cfg",
            contract_hash="hash_contract",
            engine_version="0.4.0",
        )

    cases = [
        MonitorCase(
            test_id="greeting",
            status=status,  # type: ignore[arg-type]
            diagnosis=diagnosis,
            summary="Greeting probe passed",
            samples=2,
            failures=failures,
            output_hash=out_hash,
            assertions={"contains": True},
            metrics={"latency_ms": 15.0, "input_tokens": 5, "output_tokens": 4},
            provenance=prov_greeting,
        ),
        MonitorCase(
            test_id="farewell",
            status="PASS",
            diagnosis="stable",
            summary="Farewell probe passed",
            samples=2,
            failures=0,
            output_hash=hashlib.sha256(b"Goodbye, World!").hexdigest(),
            assertions={"contains": True},
            metrics={"latency_ms": 12.0, "input_tokens": 5, "output_tokens": 4},
            provenance=prov_farewell,
        ),
    ]
    return MonitorReport(
        run_id=run_id,
        provider="mock",
        model="echo",
        samples=2,
        baseline_path="promptdrift.baseline.json",
        tests=cases,
    )


class TestLoadMonitorRunById:
    def test_load_existing_run(self, tmp_path):
        db_path = tmp_path / "history.sqlite3"
        report = _create_sample_monitor_report("run-abc-123")
        save_monitor_report(report, db_path)

        loaded = load_monitor_run_by_id(db_path, "run-abc-123")
        assert loaded.run_id == "run-abc-123"
        assert len(loaded.tests) == 2
        assert loaded.tests[0].output_hash == report.tests[0].output_hash

    def test_missing_database_raises_error(self, tmp_path):
        db_path = tmp_path / "nonexistent.sqlite3"
        with pytest.raises(PromptDriftError, match="not found"):
            load_monitor_run_by_id(db_path, "any-run")

    def test_missing_run_id_raises_error(self, tmp_path):
        db_path = tmp_path / "history.sqlite3"
        report = _create_sample_monitor_report("run-1")
        save_monitor_report(report, db_path)

        with pytest.raises(PromptDriftError, match="not found in history"):
            load_monitor_run_by_id(db_path, "run-unknown")

    def test_corrupt_database_raises_error(self, tmp_path):
        db_path = tmp_path / "history.sqlite3"
        db_path.write_bytes(b"not a valid database")

        with pytest.raises(PromptDriftError, match="corrupted"):
            load_monitor_run_by_id(db_path, "run-1")

    def test_corrupt_non_dict_json_raises_error(self, tmp_path):
        db_path = tmp_path / "history.sqlite3"
        with sqlite3.connect(db_path) as db:
            db.execute(
                "CREATE TABLE monitor_runs (run_id TEXT PRIMARY KEY, report_json TEXT NOT NULL)"
            )
            db.execute("PRAGMA user_version = 1")
            db.execute("INSERT INTO monitor_runs VALUES (?, ?)", ("corrupt-1", "[1, 2, 3]"))
            db.commit()

        with pytest.raises(PromptDriftError, match="corrupted"):
            load_monitor_run_by_id(db_path, "corrupt-1")


class TestAcceptFromHistory:
    def test_accept_run_id_creates_baseline_without_provider_calls(self, test_project, monkeypatch):
        config, config_file = test_project
        hist_file = history_path(config_file)
        run_id = "reviewed-run-001"
        report = _create_sample_monitor_report(
            run_id=run_id, config=config, config_path=config_file
        )
        save_monitor_report(report, hist_file)

        # Mock MockProvider.complete to assert no provider calls happen
        def fail_if_called(*args, **kwargs):
            pytest.fail("Provider adapter complete() should not be invoked during accept --run-id!")

        monkeypatch.setattr("promptdrift.providers.mock.MockProvider.complete", fail_if_called)

        runner = CliRunner()
        result = runner.invoke(
            app, ["accept", "-c", str(config_file), "--run-id", run_id, "--force"]
        )
        assert result.exit_code == 0, result.output
        assert "Accepted new baseline" in result.output

        baseline_file = config_file.parent / "promptdrift.baseline.json"
        assert baseline_file.is_file()
        baseline = load_baseline(baseline_file)

        assert baseline.schema_version == 3
        assert "greeting" in baseline.tests
        assert "farewell" in baseline.tests
        assert baseline.tests["greeting"].output_hash == report.tests[0].output_hash
        assert baseline.tests["greeting"].metadata.get("promoted_from_run_id") == run_id

    def test_accept_run_id_json_output(self, test_project):
        config, config_file = test_project
        hist_file = history_path(config_file)
        run_id = "reviewed-run-json"
        save_monitor_report(
            _create_sample_monitor_report(run_id=run_id, config=config, config_path=config_file),
            hist_file,
        )

        runner = CliRunner()
        result = runner.invoke(
            app, ["accept", "-c", str(config_file), "--run-id", run_id, "--force", "--json"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "accepted"
        assert data["promoted_run_id"] == run_id

    def test_accept_run_id_incompatible_cases_rejected(self, test_project):
        _, config_file = test_project
        hist_file = history_path(config_file)
        run_id = "incomplete-run"

        # Report missing 'farewell' test
        prov = Provenance(
            input_hash="h1",
            provider_hash="h2",
            configuration_hash="h3",
            contract_hash="h4",
            engine_version="0.4.0",
        )
        incomplete_report = MonitorReport(
            run_id=run_id,
            provider="mock",
            model="echo",
            samples=1,
            baseline_path="promptdrift.baseline.json",
            tests=[
                MonitorCase(
                    test_id="greeting",
                    status="PASS",
                    diagnosis="stable",
                    summary="ok",
                    samples=1,
                    output_hash="hash123",
                    assertions={},
                    metrics={},
                    provenance=prov,
                )
            ],
        )
        save_monitor_report(incomplete_report, hist_file)

        runner = CliRunner()
        result = runner.invoke(
            app, ["accept", "-c", str(config_file), "--run-id", run_id, "--force"]
        )
        assert result.exit_code != 0
        assert "incompatible" in result.output.lower() or "missing" in result.output.lower()

    def test_accept_run_id_failing_case_requires_accept_regressions(self, test_project):
        config, config_file = test_project
        hist_file = history_path(config_file)
        run_id = "failing-run"

        failing_report = _create_sample_monitor_report(
            run_id=run_id,
            status="FAIL",
            diagnosis="observed_model_drift",
            failures=1,
            config=config,
            config_path=config_file,
        )
        save_monitor_report(failing_report, hist_file)

        runner = CliRunner()
        # Without --accept-regressions -> must be refused
        result = runner.invoke(
            app, ["accept", "-c", str(config_file), "--run-id", run_id, "--force"]
        )
        assert result.exit_code != 0
        assert "accept-regressions" in result.output

        # With --accept-regressions -> succeeds
        result_ok = runner.invoke(
            app,
            [
                "accept",
                "-c",
                str(config_file),
                "--run-id",
                run_id,
                "--force",
                "--accept-regressions",
            ],
        )
        assert result_ok.exit_code == 0
        baseline_file = config_file.parent / "promptdrift.baseline.json"
        baseline = load_baseline(baseline_file)
        assert baseline.tests["greeting"].status == "FAIL"

    def test_accept_run_id_selective_scenario(self, test_project):
        config, config_file = test_project
        hist_file = history_path(config_file)
        run_id = "selective-run"
        report = _create_sample_monitor_report(
            run_id=run_id, config=config, config_path=config_file
        )
        save_monitor_report(report, hist_file)

        # First, create an initial baseline with old hashes
        baseline_file = config_file.parent / "promptdrift.baseline.json"
        initial_baseline = Baseline(
            schema_version=3,
            promptdrift_version="0.4.0",
            generated_at="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
            provider={"type": "mock", "model": "echo"},
            tests={
                "greeting": {
                    "output_hash": "old_greeting_hash",
                    "status": "PASS",
                    "assertions": {},
                    "metrics": {},
                },
                "farewell": {
                    "output_hash": "old_farewell_hash",
                    "status": "PASS",
                    "assertions": {},
                    "metrics": {},
                },
            },
        )
        baseline_file.write_text(
            initial_baseline.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )

        # Selectively accept only 'greeting'
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "accept",
                "-c",
                str(config_file),
                "--run-id",
                run_id,
                "--scenario",
                "greeting",
                "--force",
            ],
        )
        assert result.exit_code == 0

        updated_baseline = load_baseline(baseline_file)
        # 'greeting' should be updated to the history observation
        assert updated_baseline.tests["greeting"].output_hash == report.tests[0].output_hash
        # 'farewell' should remain the old hash
        assert updated_baseline.tests["farewell"].output_hash == "old_farewell_hash"

    def test_accept_run_id_archives_existing_baseline(self, test_project):
        config, config_file = test_project
        hist_file = history_path(config_file)
        run_id = "archive-run"
        save_monitor_report(
            _create_sample_monitor_report(run_id=run_id, config=config, config_path=config_file),
            hist_file,
        )

        baseline_file = config_file.parent / "promptdrift.baseline.json"
        baseline_file.write_text(
            '{"schema_version": 3, "promptdrift_version": "0.4.0", "generated_at": "2026-01-01T00:00:00Z", "provider": {"type": "mock", "model": "m"}, "tests": {}}\n'
        )

        runner = CliRunner()
        result = runner.invoke(
            app, ["accept", "-c", str(config_file), "--run-id", run_id, "--force"]
        )
        assert result.exit_code == 0

        archive_dir = config_file.parent / ".promptdrift" / "baseline_history"
        assert archive_dir.is_dir()
        archived_files = list(archive_dir.glob("*.json"))
        assert len(archived_files) == 1

    def test_accept_run_id_does_not_leak_raw_prompts_or_secrets(self, test_project):
        config, config_file = test_project
        hist_file = history_path(config_file)
        run_id = "no-leak-run"
        report = _create_sample_monitor_report(
            run_id=run_id, config=config, config_path=config_file
        )
        report.tests[0] = report.tests[0].model_copy(
            update={"summary": "secret summary", "evidence": ["secret evidence"]}
        )
        save_monitor_report(report, hist_file)

        runner = CliRunner()
        runner.invoke(app, ["accept", "-c", str(config_file), "--run-id", run_id, "--force"])

        baseline_file = config_file.parent / "promptdrift.baseline.json"
        raw_content = baseline_file.read_text(encoding="utf-8")
        assert "Hello, World!" not in raw_content
        assert "Goodbye, World!" not in raw_content
        assert "secret" not in raw_content.lower()

    def test_accept_run_id_rejects_changed_flag(self, test_project):
        config, config_file = test_project
        hist_file = history_path(config_file)
        run_id = "test-changed-run"
        save_monitor_report(
            _create_sample_monitor_report(run_id=run_id, config=config, config_path=config_file),
            hist_file,
        )

        runner = CliRunner()
        result = runner.invoke(
            app, ["accept", "-c", str(config_file), "--run-id", run_id, "--changed", "--force"]
        )
        assert result.exit_code != 0
        assert "--changed cannot be combined with --run-id" in result.output

    def test_accept_run_id_rejects_without_force_when_baseline_exists(self, test_project):
        config, config_file = test_project
        hist_file = history_path(config_file)
        run_id = "test-force-run"
        save_monitor_report(
            _create_sample_monitor_report(run_id=run_id, config=config, config_path=config_file),
            hist_file,
        )

        baseline_file = config_file.parent / "promptdrift.baseline.json"
        baseline_file.write_text(
            '{"schema_version": 3, "promptdrift_version": "0.4.0", "generated_at": "2026-01-01T00:00:00Z", "provider": {"type": "mock", "model": "m"}, "tests": {}}\n'
        )

        from promptdrift.engine.accept import accept_from_history

        with pytest.raises(BaselineError, match="Use --force to replace it"):
            accept_from_history(config, config_file, run_id=run_id, force=False)

    def test_accept_run_id_rejects_mismatched_provenance(self, test_project):
        config, config_file = test_project
        hist_file = history_path(config_file)
        run_id = "mismatched-prov-run"
        save_monitor_report(
            _create_sample_monitor_report(run_id=run_id, config=config, config_path=config_file),
            hist_file,
        )

        # Modify the prompt file after monitoring was recorded
        prompt_file = config_file.parent / "prompts" / "greeting.txt"
        prompt_file.write_text("Modified greeting: {{ name }}", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            app, ["accept", "-c", str(config_file), "--run-id", run_id, "--force"]
        )
        assert result.exit_code != 0
        assert "mismatched" in result.output and "provenance" in result.output
