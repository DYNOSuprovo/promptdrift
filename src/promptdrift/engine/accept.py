"""Selective baseline acceptance logic."""

from __future__ import annotations

from pathlib import Path

from promptdrift.engine.baseline import baseline_from_report
from promptdrift.errors import BaselineError, PromptDriftError
from promptdrift.impact import ImpactRadiusReport
from promptdrift.models import Config
from promptdrift.models.baseline import Baseline, BaselineTest
from promptdrift.models.result import RegressionReport


def selective_accept(
    current_baseline: Baseline,
    report: RegressionReport,
    impact: ImpactRadiusReport,
    scenario_ids: list[str] | None = None,
    accept_changed: bool = False,
    accept_regressions: bool = False,
) -> Baseline:
    """Selectively accept scenarios into a new baseline.

    Rules:
    - If scenario_ids is provided, ONLY those scenarios are accepted.
    - If accept_changed is True, all CHANGED_BUT_VALID scenarios are accepted.
    - REGRESSED scenarios are blocked unless accept_regressions is True.
    - NOT_EVALUATED scenarios are NEVER modified (copied from current_baseline).
    - IMPROVED, UNCHANGED, NEW are accepted by default (unless scenario_ids restricts).

    Returns a new Baseline object merging the accepted changes with the unaccepted
    parts of the current baseline.
    """
    if scenario_ids is not None:
        unknown = set(scenario_ids) - {run.test_id for run in report.tests}
        if unknown:
            raise BaselineError(
                "Requested scenarios were not evaluated: " + ", ".join(sorted(unknown))
            )
    new_baseline_obj = baseline_from_report(report)

    # We will build the new tests dictionary by picking either from current_baseline or new_baseline_obj
    merged_tests = {}

    # First, copy over everything from current baseline
    for test_id, current_test in current_baseline.tests.items():
        merged_tests[test_id] = current_test

    errors = []

    # Build classification lookup
    classifications = {s.scenario_id: s.classification for s in impact.scenarios}

    # We iterate over all tests in the new report
    for test_id, new_test in new_baseline_obj.tests.items():
        classification = classifications.get(test_id, "NOT_EVALUATED")

        if classification == "NOT_EVALUATED":
            # Never modify NOT_EVALUATED
            continue

        if scenario_ids is not None and test_id not in scenario_ids:
            # Skip if specific IDs were requested and this is not one of them
            continue

        if classification == "REGRESSED":
            if not accept_regressions:
                errors.append(test_id)
                continue

        if classification == "CHANGED_BUT_VALID":
            # Only accept if --changed was specified, or if specifically requested by ID
            if not accept_changed and (scenario_ids is None or test_id not in scenario_ids):
                continue

        # If we made it here, we accept the new test
        merged_tests[test_id] = new_test

    if errors:
        raise PromptDriftError(
            f"Cannot accept {len(errors)} REGRESSED scenario(s) without --accept-regressions:\n"
            + "\n".join(f"  - {tid}" for tid in errors)
        )

    # Return a new baseline with the merged tests and updated revision info
    from promptdrift.git import GitContext

    current_git_sha = (
        impact.current_git_sha if impact.current_git_sha else GitContext().get_head_sha()
    )

    return Baseline(
        schema_version=new_baseline_obj.schema_version,
        promptdrift_version=new_baseline_obj.promptdrift_version,
        generated_at=new_baseline_obj.generated_at,
        provider=new_baseline_obj.provider,
        prompt_revision=new_baseline_obj.prompt_revision,
        git_sha=current_git_sha,
        prompt_hash=impact.current_prompt_hash,
        tests=merged_tests,
    )


def accept_from_history(
    config: Config,
    config_path: Path,
    run_id: str,
    *,
    scenario_ids: list[str] | None = None,
    accept_regressions: bool = False,
    force: bool = False,
) -> Baseline:
    """Promote reviewed observations from monitoring history to canonical baseline without provider calls."""
    from datetime import UTC, datetime

    from promptdrift import __version__
    from promptdrift.engine.baseline import atomic_write, load_baseline
    from promptdrift.engine.baseline_history import archive_baseline
    from promptdrift.engine.suite import resolve_suite
    from promptdrift.git import GitContext
    from promptdrift.storage.history import history_path, load_monitor_run_by_id

    hist_file = history_path(config_path)
    report = load_monitor_run_by_id(hist_file, run_id)

    baseline_path = config.resolve_path(config_path, config.baseline.path)
    if baseline_path.exists() and not force:
        raise BaselineError(f"Baseline already exists: {baseline_path}. Use --force to replace it.")

    active, _ = resolve_suite(config, config_path)
    active_test_ids = {t.id for t in active.tests}
    active_tests_by_id = {t.id: t for t in active.tests}
    report_cases_by_id = {c.test_id: c for c in report.tests}

    if scenario_ids:
        unknown_requested = set(scenario_ids) - active_test_ids
        if unknown_requested:
            raise BaselineError(
                f"Requested scenario(s) not found in active suite: {', '.join(sorted(unknown_requested))}"
            )
        missing_in_run = set(scenario_ids) - set(report_cases_by_id.keys())
        if missing_in_run:
            raise BaselineError(
                f"Requested scenario(s) not found in history run '{run_id}': {', '.join(sorted(missing_in_run))}"
            )
        target_ids = scenario_ids
    else:
        missing_in_run = active_test_ids - set(report_cases_by_id.keys())
        if missing_in_run:
            raise BaselineError(
                f"History run '{run_id}' is incompatible with the active suite: missing cases: {', '.join(sorted(missing_in_run))}"
            )
        target_ids = [t.id for t in active.tests]

    failing_cases: list[str] = []
    from promptdrift.engine.provenance import fingerprint
    from promptdrift.templates import render_prompt

    for test_id in target_ids:
        test = active_tests_by_id[test_id]
        case = report_cases_by_id[test_id]
        if case.output_hash is None:
            raise BaselineError(
                f"Case '{test_id}' in history run '{run_id}' has no observed output hash to promote."
            )
        if case.provenance is not None:
            prompt_str = render_prompt(
                active.resolve_path(config_path, test.prompt), test.variables
            )
            current_prov = fingerprint(active, test, prompt_str)
            if (
                case.provenance.input_hash != current_prov.input_hash
                or case.provenance.configuration_hash != current_prov.configuration_hash
                or case.provenance.contract_hash != current_prov.contract_hash
                or case.provenance.provider_hash != current_prov.provider_hash
            ):
                raise BaselineError(
                    f"Case '{test_id}' in history run '{run_id}' has mismatched provenance with current test configuration. "
                    "The prompt, configuration, contracts, or provider have changed since this run was recorded."
                )
        if case.status in ("FAIL", "ERROR") or case.failures > 0 or case.provider_errors > 0:
            failing_cases.append(test_id)

    if failing_cases and not accept_regressions:
        raise BaselineError(
            f"Cannot accept {len(failing_cases)} failing scenario(s) from run '{run_id}' without --accept-regressions:\n"
            + "\n".join(f"  - {tid}" for tid in failing_cases)
        )

    merged_tests: dict[str, BaselineTest] = {}
    if baseline_path.is_file():
        existing_baseline = load_baseline(baseline_path)
        for tid, btest in existing_baseline.tests.items():
            merged_tests[tid] = btest

    for test_id in target_ids:
        case = report_cases_by_id[test_id]
        status = (
            "PASS"
            if case.status == "PASS"
            else ("FAIL" if case.status in ("FAIL", "ERROR") else case.status)
        )
        merged_tests[test_id] = BaselineTest(
            output_hash=case.output_hash,  # type: ignore[arg-type]
            provenance=case.provenance,
            status=status,
            assertions=case.assertions,
            metrics=case.metrics,
            evaluator_scores={},
            metadata={"promoted_from_run_id": run_id},
        )

    git_sha = GitContext().get_head_sha()

    new_baseline = Baseline(
        schema_version=3,
        promptdrift_version=__version__,
        generated_at=datetime.now(UTC),
        provider={"type": report.provider, "model": report.model},
        prompt_revision=None,
        git_sha=git_sha,
        prompt_hash=None,
        tests=merged_tests,
    )

    if baseline_path.is_file():
        archive_baseline(baseline_path)

    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(baseline_path, new_baseline.model_dump_json(indent=2) + "\n")
    return new_baseline
