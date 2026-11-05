"""JUnit XML report generation for CI test dashboards."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from promptdrift.impact import ImpactRadiusReport
from promptdrift.models import RegressionReport

_MAX_TEXT_LENGTH = 10_000


def _xml_safe_text(value: object) -> str:
    """Remove characters forbidden by XML 1.0 and limit diagnostic size."""
    text = str(value)

    valid_characters = []
    for character in text:
        codepoint = ord(character)

        if (
            codepoint in (0x09, 0x0A, 0x0D)
            or 0x20 <= codepoint <= 0xD7FF
            or 0xE000 <= codepoint <= 0xFFFD
            or 0x10000 <= codepoint <= 0x10FFFF
        ):
            valid_characters.append(character)

    safe_text = "".join(valid_characters)

    if len(safe_text) > _MAX_TEXT_LENGTH:
        safe_text = safe_text[:_MAX_TEXT_LENGTH] + " ... [truncated]"

    return safe_text


def _format_seconds(milliseconds: float) -> str:
    """Convert milliseconds into JUnit's seconds representation."""
    return f"{milliseconds / 1000:.3f}"


def write_junit_xml(
    report: RegressionReport,
    path: Path,
    impact: ImpactRadiusReport | None = None,
) -> None:
    """Write a JUnit XML report from a PromptDrift regression report."""
    counts = report.counts

    suite_attributes = {
        "name": "promptdrift",
        "tests": str(len(report.tests)),
        "failures": str(counts["FAIL"]),
        "errors": "0",
        "skipped": "0",
        "time": _format_seconds(report.duration_ms),
        "timestamp": report.generated_at.isoformat(),
    }

    root = ET.Element("testsuites", suite_attributes)
    suite = ET.SubElement(root, "testsuite", suite_attributes)

    if impact is not None:
        properties = ET.SubElement(suite, "properties")

        impact_values = {
            "improved": impact.improved,
            "unchanged": impact.unchanged,
            "changed_but_valid": impact.changed_but_valid,
            "regressed": impact.regressed,
            "impact_radius_percentage": impact.impact_radius_percentage,
            "latency_pct_change": impact.latency_pct_change,
            "cost_pct_change": impact.cost_pct_change,
        }

        for name, value in impact_values.items():
            ET.SubElement(
                properties,
                "property",
                {"name": name, "value": _xml_safe_text(value)},
            )

    for test in report.tests:
        classname = f"promptdrift.{test.provider}.{test.model}"

        testcase = ET.SubElement(
            suite,
            "testcase",
            {
                "name": _xml_safe_text(test.test_id),
                "classname": _xml_safe_text(classname),
                "time": _format_seconds(test.latency_ms),
            },
        )

        failures = [
            evaluation
            for evaluation in test.evaluations
            if not evaluation.passed and evaluation.severity == "fail"
        ]

        if test.status == "FAIL":
            if failures:
                for evaluation in failures:
                    failure = ET.SubElement(
                        testcase,
                        "failure",
                        {
                            "message": _xml_safe_text(evaluation.reason),
                            "type": _xml_safe_text(evaluation.assertion),
                        },
                    )

                    failure.text = "\n".join(
                        [
                            f"Assertion: {_xml_safe_text(evaluation.assertion)}",
                            f"Reason: {_xml_safe_text(evaluation.reason)}",
                            f"Expected: {_xml_safe_text(evaluation.expected)}",
                            f"Actual: {_xml_safe_text(evaluation.actual)}",
                        ]
                    )
            else:
                failure = ET.SubElement(
                    testcase,
                    "failure",
                    {
                        "message": "Test reported FAIL without a failed evaluation",
                        "type": "AssertionFailure",
                    },
                )
                failure.text = "The test status was FAIL, but no failing evaluation was available."

        warnings = [evaluation for evaluation in test.evaluations if evaluation.severity == "warn"]

        if warnings:
            system_out = ET.SubElement(testcase, "system-out")
            system_out.text = "\n".join(
                _xml_safe_text(evaluation.reason) for evaluation in warnings
            )

    path.parent.mkdir(parents=True, exist_ok=True)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
