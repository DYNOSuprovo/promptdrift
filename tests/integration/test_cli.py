"""Integration tests for the PromptDrift CLI including capture, learn, check, promote."""

import io
import json
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from rich.console import Console
from typer.testing import CliRunner

import promptdrift.cli as cli
from promptdrift.cli import app

runner = CliRunner()


def _patch_check_dependencies(monkeypatch, report):
    loaded = SimpleNamespace(
        baseline=SimpleNamespace(store_raw_output=False),
        policy=None,
    )

    impact = SimpleNamespace(
        improved=0,
        unchanged=0,
        changed_but_valid=0,
        regressed=0,
        impact_radius_percentage=0.0,
        latency_pct_change=0.0,
        cost_pct_change=0.0,
    )

    monkeypatch.setattr(cli, "load_config", lambda config: (loaded, config))
    monkeypatch.setattr(cli, "orchestrate_check", lambda *args, **kwargs: (report, impact))
    monkeypatch.setattr(cli, "record_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "print_impact_report", lambda *args, **kwargs: None)


class TestInitCommand:
    def test_creates_starter_files(self, tmp_path):
        result = runner.invoke(app, ["init", "--directory", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / "promptdrift.yaml").is_file()
        assert (tmp_path / "prompts" / "example.txt").is_file()

    def test_creates_missing_target_directory(self, tmp_path):
        target = tmp_path / "new-project"
        result = runner.invoke(app, ["init", "--directory", str(target)])
        assert result.exit_code == 0, result.output
        assert (target / "promptdrift.yaml").is_file()
        assert (target / "prompts" / "example.txt").is_file()

    def test_creates_nested_target_directory(self, tmp_path):
        target = tmp_path / "deeply" / "nested" / "project"
        result = runner.invoke(app, ["init", "--directory", str(target)])
        assert result.exit_code == 0, result.output
        assert (target / "promptdrift.yaml").is_file()
        assert (target / "prompts" / "example.txt").is_file()

    def test_missing_target_is_initialized_on_a_non_utf_console(self, tmp_path, monkeypatch):
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        monkeypatch.setattr(cli, "console", Console(file=stream, color_system=None))
        result = runner.invoke(app, ["init", "--directory", str(tmp_path / "new-project")])
        assert result.exit_code == 0, result.output

    def test_nested_target_is_initialized_on_a_non_utf_console(self, tmp_path, monkeypatch):
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        monkeypatch.setattr(cli, "console", Console(file=stream, color_system=None))
        target = tmp_path / "deeply" / "nested" / "non_utf_project"
        result = runner.invoke(app, ["init", "--directory", str(target)])
        assert result.exit_code == 0, result.output
        assert (target / "promptdrift.yaml").is_file()

    def test_refuses_overwrite_without_force(self, tmp_path):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        result = runner.invoke(app, ["init", "--directory", str(tmp_path)])
        assert result.exit_code == 2

    def test_force_replaces_files(self, tmp_path):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        result = runner.invoke(app, ["init", "--directory", str(tmp_path), "--force"])
        assert result.exit_code == 0


class TestTestCommand:
    def test_runs_and_passes(self, tmp_path):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        result = runner.invoke(app, ["test", "--config", str(tmp_path / "promptdrift.yaml")])
        assert result.exit_code == 0

    def test_runs_on_non_utf_console(self, tmp_path, monkeypatch):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        monkeypatch.setattr(cli, "console", Console(file=stream, color_system=None))
        result = runner.invoke(app, ["test", "--config", str(tmp_path / "promptdrift.yaml")])
        assert result.exit_code == 0, result.output

    def test_json_output(self, tmp_path):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        result = runner.invoke(
            app, ["test", "--config", str(tmp_path / "promptdrift.yaml"), "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["tests"][0]["status"] == "PASS"

    def test_missing_config_fails(self, tmp_path):
        result = runner.invoke(app, ["test", "--config", str(tmp_path / "missing.yaml")])
        assert result.exit_code != 0


class TestBaselineCommand:
    def test_creates_baseline(self, tmp_path):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        result = runner.invoke(app, ["baseline", "--config", str(tmp_path / "promptdrift.yaml")])
        assert result.exit_code == 0
        assert (tmp_path / "promptdrift.baseline.json").is_file()

    def test_creates_baseline_on_non_utf_console(self, tmp_path, monkeypatch):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        monkeypatch.setattr(cli, "console", Console(file=stream, color_system=None))
        result = runner.invoke(app, ["baseline", "--config", str(tmp_path / "promptdrift.yaml")])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "promptdrift.baseline.json").is_file()

    def test_refuses_overwrite_without_force(self, tmp_path):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        runner.invoke(app, ["baseline", "--config", str(tmp_path / "promptdrift.yaml")])
        result = runner.invoke(app, ["baseline", "--config", str(tmp_path / "promptdrift.yaml")])
        assert result.exit_code != 0

    def test_force_replaces_baseline(self, tmp_path):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        runner.invoke(app, ["baseline", "--config", str(tmp_path / "promptdrift.yaml")])
        result = runner.invoke(
            app, ["baseline", "--config", str(tmp_path / "promptdrift.yaml"), "--force"]
        )
        assert result.exit_code == 0

    def test_json_output(self, tmp_path):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        result = runner.invoke(
            app, ["baseline", "--config", str(tmp_path / "promptdrift.yaml"), "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "baseline" in data


class TestDiffCommand:
    def test_diff_with_baseline(self, tmp_path):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        runner.invoke(app, ["baseline", "--config", str(tmp_path / "promptdrift.yaml")])
        result = runner.invoke(app, ["diff", "--config", str(tmp_path / "promptdrift.yaml")])
        assert result.exit_code == 0

    def test_diff_without_baseline(self, tmp_path):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        result = runner.invoke(app, ["diff", "--config", str(tmp_path / "promptdrift.yaml")])
        assert result.exit_code == 0

    def test_diff_on_non_utf_console(self, tmp_path, monkeypatch):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        runner.invoke(app, ["baseline", "--config", str(tmp_path / "promptdrift.yaml")])
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        monkeypatch.setattr(cli, "console", Console(file=stream, color_system=None))
        result = runner.invoke(app, ["diff", "--config", str(tmp_path / "promptdrift.yaml")])
        assert result.exit_code == 0, result.output


class TestReportCommand:
    def test_creates_html_report(self, tmp_path):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        output_path = tmp_path / "report.html"
        result = runner.invoke(
            app,
            [
                "report",
                "--config",
                str(tmp_path / "promptdrift.yaml"),
                "--output",
                str(output_path),
            ],
        )
        assert result.exit_code == 0
        assert output_path.is_file()


class TestDoctorCommand:
    def test_doctor_passes(self, tmp_path):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        result = runner.invoke(app, ["doctor", "--config", str(tmp_path / "promptdrift.yaml")])
        assert result.exit_code == 0

    def test_doctor_on_non_utf_console(self, tmp_path, monkeypatch):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        monkeypatch.setattr(cli, "console", Console(file=stream, color_system=None))
        result = runner.invoke(app, ["doctor", "--config", str(tmp_path / "promptdrift.yaml")])
        assert result.exit_code == 0, result.output

    def test_doctor_privacy(self, tmp_path):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        result = runner.invoke(
            app, ["doctor", "--config", str(tmp_path / "promptdrift.yaml"), "--privacy"]
        )
        assert result.exit_code == 0

    def test_doctor_json(self, tmp_path):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        result = runner.invoke(
            app, ["doctor", "--config", str(tmp_path / "promptdrift.yaml"), "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "checks" in data
        assert all(c["passed"] for c in data["checks"])

    def test_doctor_missing_config(self, tmp_path):
        result = runner.invoke(app, ["doctor", "--config", str(tmp_path / "missing.yaml")])
        assert result.exit_code != 0


class TestMonitorCommand:
    def test_monitor_runs_and_passes(self, tmp_path):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        runner.invoke(app, ["baseline", "--config", str(tmp_path / "promptdrift.yaml")])
        result = runner.invoke(
            app, ["monitor", "--config", str(tmp_path / "promptdrift.yaml"), "--samples", "2"]
        )
        assert result.exit_code == 0, result.output

    def test_monitor_json_output(self, tmp_path):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        runner.invoke(app, ["baseline", "--config", str(tmp_path / "promptdrift.yaml")])
        result = runner.invoke(
            app,
            ["monitor", "--config", str(tmp_path / "promptdrift.yaml"), "--samples", "2", "--json"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "tests" in data
        assert data["tests"][0]["status"] == "PASS"

    def test_monitor_missing_baseline_fails(self, tmp_path):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        result = runner.invoke(
            app, ["monitor", "--config", str(tmp_path / "promptdrift.yaml"), "--samples", "2"]
        )
        assert result.exit_code != 0

    def test_monitor_runs_on_non_utf_console(self, tmp_path, monkeypatch):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])
        runner.invoke(app, ["baseline", "--config", str(tmp_path / "promptdrift.yaml")])
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        monkeypatch.setattr(cli, "console", Console(file=stream, color_system=None))
        result = runner.invoke(
            app, ["monitor", "--config", str(tmp_path / "promptdrift.yaml"), "--samples", "2"]
        )
        assert result.exit_code == 0, result.output


class TestVersionCommand:
    def test_prints_version(self):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        from promptdrift import __version__

        assert __version__ in result.output


class TestNewLifecycleCommands:
    def test_capture_learn_promote_check(self, tmp_path):
        runner.invoke(app, ["init", "--directory", str(tmp_path)])

        # 1. Capture interaction
        res_cap = runner.invoke(
            app,
            [
                "capture",
                "--input",
                "How do I cancel my order?",
                "--output",
                "You can cancel your order within 24 hours.",
                "--json",
            ],
        )
        assert res_cap.exit_code == 0

        # 2. Learn candidate scenarios
        res_learn = runner.invoke(app, ["learn", "--json"])
        assert res_learn.exit_code == 0
        scenarios = json.loads(res_learn.output)
        assert len(scenarios) > 0
        first_id = scenarios[0]["id"]

        # 3. Suggest contracts
        res_sug = runner.invoke(app, ["suggest", first_id, "--json"])
        assert res_sug.exit_code == 0
        suggestions = json.loads(res_sug.output)
        assert len(suggestions) > 0

        # 4. Promote
        res_prom = runner.invoke(app, ["promote", first_id])
        assert res_prom.exit_code == 0

        # 5. Check
        res_check = runner.invoke(
            app, ["check", "--config", str(tmp_path / "promptdrift.yaml"), "--json"]
        )
        assert res_check.exit_code == 0
        check_data = json.loads(res_check.output)
        assert "impact" in check_data
        assert "report" in check_data

        # 6. Accept
        res_accept = runner.invoke(app, ["accept", "--config", str(tmp_path / "promptdrift.yaml")])
        assert res_accept.exit_code == 0

        # 7. Purge
        res_purge = runner.invoke(app, ["purge", "--yes"])
        assert res_purge.exit_code == 0

    def test_lifecycle_on_non_utf_console(self, tmp_path, monkeypatch):
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        monkeypatch.setattr(cli, "console", Console(file=stream, color_system=None))

        runner.invoke(app, ["init", "--directory", str(tmp_path)])

        res_cap = runner.invoke(
            app,
            [
                "capture",
                "--input",
                "How do I cancel my order?",
                "--output",
                "You can cancel your order within 24 hours.",
            ],
        )
        assert res_cap.exit_code == 0, res_cap.output

        res_learn = runner.invoke(app, ["learn"])
        assert res_learn.exit_code == 0, res_learn.output

        res_learn_json = runner.invoke(app, ["learn", "--json"])
        assert res_learn_json.exit_code == 0, res_learn_json.output
        first_id = json.loads(res_learn_json.output)[0]["id"]

        res_sug = runner.invoke(app, ["suggest", first_id])
        assert res_sug.exit_code == 0, res_sug.output

        res_prom = runner.invoke(app, ["promote", first_id])
        assert res_prom.exit_code == 0, res_prom.output

        res_check = runner.invoke(app, ["check", "--config", str(tmp_path / "promptdrift.yaml")])
        assert res_check.exit_code == 0, res_check.output

        res_purge = runner.invoke(app, ["purge", "--yes"])
        assert res_purge.exit_code == 0, res_purge.output


class TestIsolatedExecution:
    def test_cli_execution_leaves_no_lingering_files_in_repository(self, tmp_path):
        repo_root = Path(__file__).resolve().parents[2]
        files_before = {
            str(p.relative_to(repo_root))
            for p in repo_root.rglob("*")
            if not p.name.startswith(".git")
            and "__pycache__" not in p.parts
            and ".pytest_cache" not in p.parts
        }

        project_dir = tmp_path / "isolated_project"
        res = runner.invoke(app, ["init", "--directory", str(project_dir)])
        assert res.exit_code == 0, res.output
        res = runner.invoke(app, ["baseline", "--config", str(project_dir / "promptdrift.yaml")])
        assert res.exit_code == 0, res.output
        res = runner.invoke(app, ["test", "--config", str(project_dir / "promptdrift.yaml")])
        assert res.exit_code == 0, res.output
        res = runner.invoke(
            app, ["monitor", "--config", str(project_dir / "promptdrift.yaml"), "--samples", "2"]
        )
        assert res.exit_code == 0, res.output
        res = runner.invoke(
            app,
            [
                "report",
                "--config",
                str(project_dir / "promptdrift.yaml"),
                "--output",
                str(project_dir / "report.html"),
            ],
        )
        assert res.exit_code == 0, res.output

        assert (project_dir / "promptdrift.yaml").is_file()
        assert (project_dir / "promptdrift.baseline.json").is_file()
        assert (project_dir / "report.html").is_file()
        assert (project_dir / ".promptdrift" / "history.sqlite3").is_file()

        files_after = {
            str(p.relative_to(repo_root))
            for p in repo_root.rglob("*")
            if not p.name.startswith(".git")
            and "__pycache__" not in p.parts
            and ".pytest_cache" not in p.parts
        }
        assert files_after == files_before

    def test_home_directory_mock_isolation(self, tmp_path):
        home = Path.home()
        assert str(tmp_path) in str(home) or home.is_relative_to(tmp_path)

        res = runner.invoke(
            app,
            [
                "capture",
                "--input",
                "test query",
                "--output",
                "test response",
            ],
        )
        assert res.exit_code == 0, res.output
        expected_db = home / ".promptdrift" / "promptdrift.db"
        assert expected_db.is_file()

        res_purge = runner.invoke(app, ["purge", "--yes"])
        assert res_purge.exit_code == 0


class TestJUnitXmlCommand:
    def test_test_command_writes_junit_xml(self, tmp_path):
        initialized = runner.invoke(app, ["init", "--directory", str(tmp_path)])
        assert initialized.exit_code == 0, initialized.output

        output_path = tmp_path / "reports" / "results.xml"

        result = runner.invoke(
            app,
            [
                "test",
                "--config",
                str(tmp_path / "promptdrift.yaml"),
                "--junit-xml",
                str(output_path),
            ],
        )

        assert result.exit_code == 0, result.output
        assert output_path.is_file()

        root = ET.parse(output_path).getroot()
        assert root.tag == "testsuites"
        assert root.find("./testsuite/testcase") is not None

    def test_test_command_writes_xml_before_failure_exit(
        self, tmp_path, monkeypatch, multi_test_report
    ):
        monkeypatch.setattr(
            cli,
            "_run",
            lambda *args, **kwargs: (None, None, multi_test_report),
        )

        output_path = tmp_path / "results.xml"

        result = runner.invoke(
            app,
            ["test", "--junit-xml", str(output_path)],
        )

        assert result.exit_code == 1
        assert output_path.is_file()

        root = ET.parse(output_path).getroot()
        suite = root.find("testsuite")

        assert suite is not None
        assert suite.attrib["failures"] == "1"
        assert suite.find(".//failure") is not None

    def test_check_command_writes_xml_before_failure_exit(
        self, tmp_path, monkeypatch, multi_test_report
    ):
        _patch_check_dependencies(monkeypatch, multi_test_report)

        output_path = tmp_path / "reports" / "check-results.xml"

        result = runner.invoke(
            app,
            [
                "check",
                "--config",
                str(tmp_path / "promptdrift.yaml"),
                "--junit-xml",
                str(output_path),
            ],
        )

        assert result.exit_code == 1
        assert output_path.is_file()

        root = ET.parse(output_path).getroot()
        suite = root.find("testsuite")

        assert suite is not None
        assert suite.attrib["failures"] == "1"
        assert suite.find(".//failure") is not None
