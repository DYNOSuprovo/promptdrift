"""Rich terminal, text, and data presentations for Impact Radius Reports."""

from __future__ import annotations

import sys

from rich.console import Console

from promptdrift.impact import ImpactRadiusReport


def _is_unicode_supported(console_instance: Console | None = None) -> bool:
    target = console_instance or Console()
    encoding = getattr(target, "encoding", None) or getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        "✓⚪💬✗⏭".encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def print_impact_report(report: ImpactRadiusReport, console: Console | None = None) -> None:
    console = console or Console()
    unicode_safe = _is_unicode_supported(console)

    improved_icon = "✓" if unicode_safe else "+"
    unchanged_icon = "⚪" if unicode_safe else "="
    changed_icon = "💬" if unicode_safe else "*"
    regressed_icon = "✗" if unicode_safe else "X"
    skipped_icon = "⏭" if unicode_safe else "~"

    console.print("\n[bold]PromptDrift Impact Report[/bold]")
    console.print(
        f"Behavior changed in {report.regressed + report.improved + report.changed_but_valid} / {report.total_scenarios} scenarios."
    )
    console.print()

    console.print(f"  [green]{improved_icon} {report.improved} improved[/green]")
    console.print(f"  [cyan]{unchanged_icon} {report.unchanged} unchanged[/cyan]")
    console.print(f"  [yellow]{changed_icon} {report.changed_but_valid} changed but valid[/yellow]")
    if report.regressed > 0:
        console.print(f"  [red]{regressed_icon} {report.regressed} regressed[/red]")
    if report.new_scenarios > 0:
        console.print(f"  [blue]+ {report.new_scenarios} new[/blue]")
    if report.missing_scenarios > 0:
        console.print(f"  [magenta]- {report.missing_scenarios} missing[/magenta]")
    if report.not_evaluated > 0:
        console.print(
            f"  [dim]{skipped_icon} {report.not_evaluated} not evaluated (unaffected by this change)[/dim]"
        )

    console.print()
    console.print(f"[bold]Impact radius:[/] {report.impact_radius_percentage}%")
    console.print(f"Latency change: {report.latency_pct_change:+.1f}%")
    console.print(f"Cost change:    {report.cost_pct_change:+.1f}%")
    console.print()

    if report.category_breakdown:
        console.print("[bold]Affected Categories:[/bold]")
        for cat, count in report.category_breakdown.items():
            console.print(f"  {cat.capitalize():<16} {count} affected")
        console.print()

    regressions = [s for s in report.scenarios if s.classification == "REGRESSED"]
    if regressions:
        console.print("[bold red]Regressions:[/bold red]")
        for s in regressions:
            console.print(f"  [red]{regressed_icon} {s.scenario_id}[/red]")
            console.print(f"    {s.details}")
        console.print()

    changed_valid = [s for s in report.scenarios if s.classification == "CHANGED_BUT_VALID"]
    if changed_valid:
        console.print(
            f"[bold yellow]Changed but valid:[/] {len(changed_valid)} scenarios changed wording while passing contracts."
        )
