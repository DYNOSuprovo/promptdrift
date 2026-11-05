"""PromptDrift command-line interface."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from . import __version__
from .config import load_config
from .engine.baseline import atomic_write, load_baseline, write_baseline
from .engine.capture import create_interaction
from .engine.check import orchestrate_check
from .engine.discovery import discover_scenarios
from .engine.regression import compare_to_baseline
from .engine.runner import run_suite
from .engine.suggest import suggest_assertions_for_scenario
from .engine.suite import resolve_suite
from .errors import (
    BaselineError,
    ConfigError,
    EvaluationError,
    PromptDriftError,
    ProviderError,
    TemplateError,
)
from .git import GitContext
from .reports import print_impact_report, print_report, write_html_report, write_junit_xml
from .storage import (
    add_or_update_scenarios,
    get_interactions,
    load_scenarios,
    purge_storage,
    record_report,
    save_scenarios,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Git-native CI regression testing for LLM prompts.",
)
console = Console()


def _is_unicode_supported(console_instance: Console | None = None) -> bool:
    target = console_instance or console
    encoding = getattr(target, "encoding", None) or getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        "✓✗".encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def _exit_error(error: Exception, verbose: bool = False) -> None:
    if verbose:
        raise error
    console.print(f"[red]Error:[/] {error}")
    code = (
        3
        if isinstance(error, ProviderError)
        else 2
        if isinstance(error, (ConfigError, BaselineError, TemplateError, EvaluationError))
        else 3
    )
    raise typer.Exit(code=code)


def _run(config: Path | str, with_baseline: bool, verbose: bool):
    try:
        loaded, config_path = load_config(config)
        loaded, _ = resolve_suite(loaded, config_path)
        baseline_path = loaded.resolve_path(config_path, loaded.baseline.path)
        previous = (
            load_baseline(baseline_path) if with_baseline and baseline_path.exists() else None
        )
        report = run_suite(loaded, config_path)
        if previous is not None:
            report = compare_to_baseline(report, previous)
            report.baseline_path = str(baseline_path)
        record_report(report, store_raw_output=loaded.baseline.store_raw_output)
        return loaded, config_path, report
    except PromptDriftError as error:
        _exit_error(error, verbose)
    return None


def _emit(report, as_json: bool) -> None:
    if as_json:
        typer.echo(report.model_dump_json(indent=2))
    else:
        print_report(report, console)
    if report.counts["FAIL"]:
        raise typer.Exit(code=1)


@app.command()
def init(
    directory: Annotated[Path, typer.Option("--directory", "-d", help="Project directory.")] = Path(
        "."
    ),
    force: Annotated[bool, typer.Option(help="Replace generated starter files.")] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Non-interactive default setup.")
    ] = False,
) -> None:
    """Zero-config project setup detecting Git repository and local prompt files."""
    # GitContext uses this directory as a subprocess cwd. Create a requested
    # starter directory before probing it so `promptdrift init -d new-project`
    # works from an empty parent directory.
    directory.mkdir(parents=True, exist_ok=True)
    git = GitContext(root=directory)
    is_git = git.is_git_repo()

    prompt_files = list(directory.glob("prompts/**/*.*")) + list(directory.glob("*.txt"))
    config_file = directory / "promptdrift.yaml"
    example_prompt = directory / "prompts" / "example.txt"

    if (config_file.exists() or example_prompt.exists()) and not force:
        console.print("[red]Error:[/] Starter files already exist. Use --force to replace them.")
        raise typer.Exit(code=2)

    console.print(
        f"{'[green]OK[/]' if is_git else '[yellow]INFO[/]'} Git repository {'detected' if is_git else 'not detected'}"
    )
    if prompt_files:
        console.print(f"[green]OK[/] Prompt files detected: {len(prompt_files)} files")
    else:
        console.print(
            "[yellow]INFO[/] No existing prompt files found; creating prompts/example.txt"
        )

    example_prompt.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        """version: 2

project:
  name: promptdrift-starter

provider:
  type: mock
  model: local-echo

defaults:
  temperature: 0
  max_output_tokens: 500

baseline:
  path: promptdrift.baseline.json

tests:
  - id: hello
    prompt: prompts/example.txt
    variables:
      input: Hello
    assertions:
      - type: contains
        value: Hello
""",
        encoding="utf-8",
    )
    example_prompt.write_text(
        "Reply to this input exactly and concisely: {{ input }}\n", encoding="utf-8"
    )
    console.print(
        "[green]Created[/] promptdrift.yaml and prompts/example.txt\nRun: promptdrift check"
    )


@app.command()
def capture(
    input_text: Annotated[str, typer.Option("--input", "-i", help="Prompt input text.")] = "",
    output_text: Annotated[str, typer.Option("--output", "-o", help="Model output text.")] = "",
    provider: Annotated[str, typer.Option(help="Provider name.")] = "openai",
    model: Annotated[str, typer.Option(help="Model name.")] = "gpt-4.1-mini",
    prompt_file: Annotated[
        str, typer.Option(help="Prompt file reference.")
    ] = "prompts/example.txt",
    tag: Annotated[list[str], typer.Option(help="Tags for interaction.")] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
) -> None:
    """Capture a real or simulated interaction into local storage for learning."""
    if not input_text or not output_text:
        console.print("[yellow]Capturing example offline interaction for demonstration...[/]")
        input_text = input_text or "Can I get a refund for order #1234?"
        output_text = (
            output_text or "Refunds are processed within 30 days of purchase per company policy."
        )

    interaction = create_interaction(
        provider=provider,
        model=model,
        prompt=prompt_file,
        input=input_text,
        output=output_text,
        tags=tag or ["support"],
    )
    if json_output:
        typer.echo(interaction.model_dump_json(indent=2))
    else:
        console.print(f"[green]Captured interaction:[/] {interaction.id}")


@app.command()
def learn(
    limit: Annotated[int, typer.Option(help="Maximum interactions to process.")] = 1000,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Turn captured interactions into candidate regression scenarios."""
    interactions = get_interactions(limit=limit)
    if not interactions:
        console.print("[yellow]No captured interactions found. Use 'promptdrift capture' first.[/]")
        return

    scenarios = discover_scenarios(interactions)
    add_or_update_scenarios(scenarios)

    if json_output:
        typer.echo(json.dumps([s.model_dump() for s in scenarios], indent=2, default=str))
    else:
        mark = "✓" if _is_unicode_supported(console) else "OK"
        console.print(f"[green]{mark}[/] {len(interactions)} interactions loaded")
        console.print(
            f"[green]{mark}[/] {len(scenarios)} candidate scenarios discovered and saved to .promptdrift/scenarios.json"
        )
        console.print("\nReview candidates with: [bold]promptdrift scenarios[/bold]")
        console.print("Promote candidates with: [bold]promptdrift promote <scenario-id>[/bold]")


@app.command()
def scenarios(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List scenarios in the scenario library."""
    lib = load_scenarios()
    if json_output:
        typer.echo(lib.model_dump_json(indent=2))
    else:
        if not lib.scenarios:
            console.print(
                "[yellow]Scenario library is empty. Run 'promptdrift learn' or author YAML tests.[/]"
            )
            return
        console.print(f"[bold]Scenario Library ({len(lib.scenarios)} items):[/bold]")
        for sc in lib.scenarios:
            status_color = "green" if sc.status == "promoted" else "yellow"
            console.print(
                f"  - [{status_color}]{sc.id}[/{status_color}] ({sc.status}) - {sc.input[:60]}"
            )


@app.command()
def suggest(
    scenario_id: Annotated[str, typer.Argument(help="Scenario ID to suggest contracts for.")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Suggest deterministic behavioral contracts for a scenario."""
    lib = load_scenarios()
    scenario = next((s for s in lib.scenarios if s.id == scenario_id), None)
    if not scenario:
        console.print(f"[red]Error:[/] Scenario '{scenario_id}' not found.")
        raise typer.Exit(code=2)

    interactions = get_interactions()
    suggestions = suggest_assertions_for_scenario(scenario, interactions)

    if json_output:
        typer.echo(json.dumps([a.model_dump() for a in suggestions], indent=2))
    else:
        mark = "✓" if _is_unicode_supported(console) else "OK"
        console.print(f"[bold]Suggested contracts for {scenario_id}:[/bold]")
        for a in suggestions:
            console.print(
                f"  {mark} {a.type} -> {a.value or a.schema_ or ''} (severity: {a.severity})"
            )


@app.command()
def promote(
    scenario_id: Annotated[str, typer.Argument(help="Scenario ID to promote to active suite.")],
    all_candidates: Annotated[
        bool, typer.Option("--all", help="Promote all candidate scenarios.")
    ] = False,
) -> None:
    """Promote candidate scenarios into committed regression tests."""
    lib = load_scenarios()
    promoted_count = 0
    interactions = get_interactions()

    for sc in lib.scenarios:
        if all_candidates or sc.id == scenario_id:
            sc.status = "promoted"
            if not sc.assertions:
                sc.assertions = suggest_assertions_for_scenario(sc, interactions)
            promoted_count += 1

    save_scenarios(lib)
    console.print(f"[green]Promoted {promoted_count} scenario(s) to active regression suite.[/]")
    console.print(
        "[dim]Commit .promptdrift/scenarios.json to version-control your regression tests.[/]"
    )


@app.command()
def check(
    config: Annotated[Path, typer.Option("--config", "-c", help="Config file path.")] = Path(
        "promptdrift.yaml"
    ),
    base: Annotated[
        str | None,
        typer.Option("--base", help="Git base ref (e.g. origin/main) for selective check."),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
    junit_xml: Annotated[
        Path | None,
        typer.Option("--junit-xml", help="Write a JUnit XML report."),
    ] = None,
) -> None:
    """Git-aware scenario execution and Impact Radius report."""
    try:
        loaded, config_path = load_config(config)
        report, impact = orchestrate_check(loaded, config_path, base_ref=base)
        record_report(report, store_raw_output=loaded.baseline.store_raw_output)
        if junit_xml is not None:
            write_junit_xml(report, junit_xml, impact=impact)

        if json_output:
            out_data = {
                "report": report.model_dump(),
                "impact": impact.model_dump(),
            }
            typer.echo(json.dumps(out_data, indent=2, default=str))
        else:
            print_impact_report(impact, console)

        # Policy evaluation: fail on regression
        fail_triggers = loaded.policy.fail_on if loaded.policy else ["regression"]
        if "regression" in fail_triggers and impact.regressed > 0:
            raise typer.Exit(code=1)
        if report.counts["FAIL"]:
            raise typer.Exit(code=1)
    except PromptDriftError as error:
        _exit_error(error, verbose)


@app.command()
def accept(
    config: Annotated[Path, typer.Option("--config", "-c", help="Config file path.")] = Path(
        "promptdrift.yaml"
    ),
    scenario: Annotated[
        list[str], typer.Option("--scenario", "-s", help="Selectively accept specific scenarios.")
    ] = [],
    changed: Annotated[
        bool, typer.Option("--changed", help="Accept all CHANGED_BUT_VALID scenarios.")
    ] = False,
    accept_regressions: Annotated[
        bool, typer.Option("--accept-regressions", help="Accept REGRESSED scenarios.")
    ] = False,
    run_id: Annotated[
        str | None,
        typer.Option(
            "--run-id", help="Promote a reviewed run from monitoring history to baseline."
        ),
    ] = None,
    force: Annotated[
        bool, typer.Option(help="Overwrite existing baseline without confirmation.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Accept current behavior as the new canonical baseline."""
    try:
        from promptdrift.config import load_config
        from promptdrift.engine.accept import accept_from_history, selective_accept
        from promptdrift.engine.baseline import load_baseline
        from promptdrift.engine.baseline_history import archive_baseline
        from promptdrift.engine.check import orchestrate_check

        loaded, config_path = load_config(config)

        path = loaded.resolve_path(config_path, loaded.baseline.path)
        if path.exists() and not force:
            confirmed = typer.confirm(
                f"Baseline {path.name} already exists. Overwrite with current behavior?"
            )
            if not confirmed:
                console.print("[yellow]Aborted.[/]")
                return

        if run_id:
            if changed:
                raise BaselineError(
                    "--changed cannot be combined with --run-id. Use --scenario to select cases."
                )
            accept_from_history(
                loaded,
                config_path,
                run_id=run_id,
                scenario_ids=scenario if scenario else None,
                accept_regressions=accept_regressions,
                force=True,
            )
        elif not path.exists():
            if scenario or changed:
                raise BaselineError(
                    "Selective acceptance requires an existing baseline. Create a full reviewed baseline first."
                )
            # Initial acceptance evaluates the full suite and records revision evidence.
            report, impact = orchestrate_check(loaded, config_path, selective=False)
            if report.counts["FAIL"] and not accept_regressions:
                raise BaselineError(
                    "Refusing a failing baseline. Review failures or use --accept-regressions explicitly."
                )
            from promptdrift.engine.baseline import write_baseline

            write_baseline(
                path,
                report,
                force=True,
                git_sha=impact.current_git_sha,
                prompt_hash=impact.current_prompt_hash,
            )
        else:
            # Evaluate the full suite; acceptance selection is independent of Git selection.
            report, impact = orchestrate_check(loaded, config_path, selective=False)
            current_baseline = load_baseline(path)

            new_baseline = selective_accept(
                current_baseline=current_baseline,
                report=report,
                impact=impact,
                scenario_ids=scenario if scenario else None,
                accept_changed=changed,
                accept_regressions=accept_regressions,
            )

            archive_baseline(path)
            content = new_baseline.model_dump_json(indent=2) + "\n"
            atomic_write(path, content)

        if json_output:
            payload = {"baseline": str(path), "status": "accepted"}
            if run_id:
                payload["promoted_run_id"] = run_id
            typer.echo(json.dumps(payload, indent=2))
        else:
            if run_id:
                console.print(f"[green]Accepted new baseline from history run {run_id}:[/] {path}")
            else:
                console.print(f"[green]Accepted new baseline:[/] {path}")
    except PromptDriftError as error:
        _exit_error(error, verbose)


@app.command()
def purge(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Confirm local storage purge.")] = False,
) -> None:
    """Purge all local SQLite interactions and history."""
    if not yes:
        confirmed = typer.confirm("Are you sure you want to purge all local captured interactions?")
        if not confirmed:
            return
    purge_storage()
    console.print("[green]Local storage successfully purged.[/]")


@app.command()
def test(
    config: Annotated[Path, typer.Option("--config", "-c", help="Config file path.")] = Path(
        "promptdrift.yaml"
    ),
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
    junit_xml: Annotated[
        Path | None,
        typer.Option("--junit-xml", help="Write a JUnit XML report."),
    ] = None,
) -> None:
    """Run behavioral contracts; automatically compares an existing baseline."""
    result = _run(config, with_baseline=True, verbose=verbose)
    if result:
        if junit_xml is not None:
            write_junit_xml(result[2], junit_xml)

        _emit(result[2], json_output)


@app.command()
def baseline(
    config: Annotated[Path, typer.Option("--config", "-c", help="Config file path.")] = Path(
        "promptdrift.yaml"
    ),
    force: Annotated[bool, typer.Option(help="Replace an existing baseline.")] = False,
    accept_regressions: Annotated[
        bool, typer.Option("--accept-regressions", help="Explicitly allow a failing baseline.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Create a canonical version-controlled baseline."""
    try:
        loaded, config_path = load_config(config)
        path = loaded.resolve_path(config_path, loaded.baseline.path)
        if path.exists() and not force:
            raise BaselineError("Baseline already exists. Use --force to replace it after review.")
    except PromptDriftError as error:
        _exit_error(error, verbose)
        return
    result = _run(config, with_baseline=False, verbose=verbose)
    if not result:
        return
    loaded, config_path, report = result
    try:
        if report.counts["FAIL"] and not accept_regressions:
            raise BaselineError(
                "Refusing a failing baseline. Review failures or use --accept-regressions explicitly."
            )
        path = loaded.resolve_path(config_path, loaded.baseline.path)
        write_baseline(path, report, force=force)
        if json_output:
            typer.echo(json.dumps({"baseline": str(path), "status": "created"}, indent=2))
        else:
            console.print(f"[green]Baseline written:[/] {path}")
    except PromptDriftError as error:
        _exit_error(error, verbose)


@app.command()
def baselines(
    config: Annotated[Path, typer.Option("--config", "-c", help="Config file path.")] = Path(
        "promptdrift.yaml"
    ),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List canonical baseline and archived history."""
    import json

    from promptdrift.engine.baseline import load_baseline
    from promptdrift.engine.baseline_history import list_baseline_history

    loaded, config_path = load_config(config)
    canonical = loaded.resolve_path(config_path, loaded.baseline.path)
    paths = list_baseline_history(canonical.parent / ".promptdrift" / "baseline_history")

    if json_output:
        history = [{"path": str(p)} for p in paths]
        typer.echo(json.dumps({"history": history}, indent=2))
        return

    from rich.table import Table

    table = Table(title="Baseline History")
    table.add_column("Date", style="cyan")
    table.add_column("Git SHA", style="green")
    table.add_column("Prompt Hash", style="yellow")
    table.add_column("Scenarios")

    for p in paths:
        try:
            b = load_baseline(p)
            table.add_row(
                b.generated_at.strftime("%Y-%m-%d %H:%M:%S"),
                b.git_sha[:8] if b.git_sha else "-",
                b.prompt_hash[:8] if b.prompt_hash else "-",
                str(len(b.tests)),
            )
        except Exception:
            table.add_row(p.name, "error", "-", "-")

    if not paths:
        console.print("No baseline history found.")
    else:
        console.print(table)


@app.command()
def diff(
    config: Annotated[Path, typer.Option("--config", "-c", help="Config file path.")] = Path(
        "promptdrift.yaml"
    ),
    json_output: Annotated[bool, typer.Option("--json")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run tests and compare the current behavior with the canonical baseline."""
    result = _run(config, with_baseline=True, verbose=verbose)
    if result:
        _emit(result[2], json_output)


@app.command()
def report(
    config: Annotated[Path, typer.Option("--config", "-c", help="Config file path.")] = Path(
        "promptdrift.yaml"
    ),
    output: Annotated[Path, typer.Option("--output", "-o", help="Output report file path.")] = Path(
        "promptdrift-report.html"
    ),
    json_output: Annotated[bool, typer.Option("--json")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Create an offline HTML report."""
    result = _run(config, with_baseline=True, verbose=verbose)
    if result:
        write_html_report(result[2], output)
        if json_output:
            typer.echo(result[2].model_dump_json(indent=2))
        else:
            console.print(f"[green]Report written:[/] {output}")
        if result[2].counts["FAIL"]:
            raise typer.Exit(code=1)


@app.command()
def doctor(
    config: Annotated[Path, typer.Option("--config", "-c", help="Config file path.")] = Path(
        "promptdrift.yaml"
    ),
    privacy: Annotated[
        bool, typer.Option("--privacy", help="Inspect privacy and local data storage.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Check configuration, files, secrets, baseline, provider prerequisites, and privacy."""
    checks: list[dict[str, str | bool]] = []
    try:
        loaded, config_path = load_config(config)
        loaded, _ = resolve_suite(loaded, config_path)
        checks.extend(
            [
                {"name": "Config found and YAML valid", "passed": True},
                {"name": f"{len(loaded.tests)} test cases discovered", "passed": True},
            ]
        )
        for test_case in loaded.tests:
            from .templates import render_prompt

            try:
                render_prompt(
                    loaded.resolve_path(config_path, test_case.prompt), test_case.variables
                )
                renderable = True
            except (TemplateError, OSError):
                renderable = False
            checks.append({"name": f"Prompt renders: {test_case.prompt}", "passed": renderable})
        if loaded.provider.type == "openai":
            env = loaded.provider.api_key_env or "OPENAI_API_KEY"
            checks.append({"name": f"{env} found", "passed": bool(os.environ.get(env))})
        baseline = loaded.resolve_path(config_path, loaded.baseline.path)
        try:
            if baseline.exists():
                load_baseline(baseline)
            checks.append(
                {
                    "name": "Baseline valid" if baseline.exists() else "No baseline yet (optional)",
                    "passed": True,
                }
            )
        except BaselineError:
            checks.append({"name": "Baseline valid", "passed": False})

        if privacy:
            checks.append({"name": "No telemetry configured", "passed": True})
            checks.append({"name": "Legacy history is local, not encrypted", "passed": True})
            checks.append(
                {
                    "name": "Raw baseline suppression active",
                    "passed": not loaded.baseline.store_raw_output,
                }
            )
    except PromptDriftError as error:
        _exit_error(error, verbose)
        return

    if json_output:
        typer.echo(json.dumps({"checks": checks}, indent=2))
    else:
        console.print("[bold]PromptDrift Doctor[/]")
        unicode_console = _is_unicode_supported(console)
        for check in checks:
            good, bad = ("✓", "✗") if unicode_console else ("OK", "X")
            console.print(
                f"{'[green]' + good + '[/]' if check['passed'] else '[red]' + bad + '[/]'} {check['name']}"
            )
    if not all(bool(check["passed"]) for check in checks):
        raise typer.Exit(code=2)


@app.command()
def monitor(
    config: Annotated[Path, typer.Option("--config", "-c", help="Config file path.")] = Path(
        "promptdrift.yaml"
    ),
    samples: Annotated[
        int, typer.Option(help="Probes per case (1-20); each may incur provider cost.")
    ] = 3,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    no_history: Annotated[
        bool, typer.Option("--no-history", help="Do not persist the privacy-minimized report.")
    ] = False,
) -> None:
    """Probe the full suite against a reviewed baseline, even when Git has no changes."""
    from .engine.monitor import monitor_suite
    from .storage.history import history_path, save_monitor_report

    try:
        loaded, config_path = load_config(config)
        report = monitor_suite(loaded, config_path, samples=samples)
        if not no_history:
            try:
                save_monitor_report(report, history_path(config_path))
            except PromptDriftError as error:
                report.warnings.append(str(error))
    except (PromptDriftError, OSError, ValueError) as error:
        code = 3 if isinstance(error, ProviderError) else 2
        # Config/parser errors can contain private YAML values. Do not publish them in CI JSON.
        message = "Monitoring could not start. Check configuration, baseline and prompt files locally with 'promptdrift doctor'."
        if json_output:
            typer.echo(
                json.dumps(
                    {"error": {"type": type(error).__name__, "message": message}, "exit_code": code}
                )
            )
        else:
            console.print(message, markup=False)
        raise typer.Exit(code=code) from error
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    else:
        from .reports.monitor import print_monitor_report

        print_monitor_report(report, console)
    raise typer.Exit(code=report.exit_code)


@app.command()
def history(
    config: Annotated[
        Path,
        typer.Option(
            "--config", "-c", help="Config path determines the project history directory."
        ),
    ] = Path("promptdrift.yaml"),
    limit: Annotated[int, typer.Option(min=1, max=1000)] = 20,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Read recent local monitoring reports without calling a provider."""
    from .storage.history import history_path, load_monitor_history

    try:
        runs = load_monitor_history(history_path(config.resolve()), limit=limit)
    except PromptDriftError as error:
        if json_output:
            typer.echo(
                json.dumps(
                    {"error": {"type": type(error).__name__, "message": str(error)}, "exit_code": 2}
                )
            )
            raise typer.Exit(code=2) from error
        _exit_error(error)
        return
    if json_output:
        typer.echo(json.dumps({"runs": runs}, indent=2))
    elif not runs:
        console.print("No monitoring history. Run 'promptdrift monitor' first.")
    else:
        for run in runs:
            console.print(
                f"{run['generated_at']}  {run['run_id']}  {run['diagnosis_counts']}", markup=False
            )


@app.command()
def demo(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Show a synthetic unchanged-input drift incident using a local HTTP fixture; no API key needed."""
    from .demo import run_demo

    report = run_demo()
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    else:
        from .reports.monitor import print_monitor_report

        console.print("Synthetic local demo: fixture responses changed, not a real model update.")
        print_monitor_report(report, console)


@app.command()
def version() -> None:
    """Print the PromptDrift version."""
    typer.echo(__version__)


def main() -> None:
    try:
        app()
    except PromptDriftError as error:
        _exit_error(error)


if __name__ == "__main__":
    main()
