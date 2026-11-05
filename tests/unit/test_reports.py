"""Tests for JUnit XML report generation."""

from xml.etree import ElementTree as ET

from promptdrift.models import RegressionReport, TestRun
from promptdrift.models.result import EvaluationResult
from promptdrift.reports.junit import write_junit_xml


def make_report(tests, duration_ms=456):
    return RegressionReport(
        provider="mock",
        model="test-model",
        tests=tests,
        duration_ms=duration_ms,
    )


def make_test_run(
    test_id="test_example",
    status="PASS",
    latency_ms=123,
    evaluations=None,
):
    return TestRun(
        test_id=test_id,
        provider="mock",
        model="test-model",
        input="test input",
        output="test output",
        latency_ms=latency_ms,
        status=status,
        evaluations=evaluations or [],
    )


class TestJUnitReport:
    def test_creates_xml_file_and_parent_directories(self, tmp_path):
        path = tmp_path / "reports" / "ci" / "junit.xml"
        report = make_report([make_test_run()])

        write_junit_xml(report, path)

        assert path.is_file()
        assert path.parent.is_dir()

        root = ET.parse(path).getroot()
        assert root.tag == "testsuites"

    def test_generates_standard_junit_structure(self, tmp_path):
        path = tmp_path / "junit.xml"

        report = make_report(
            [
                make_test_run("test_one"),
                make_test_run("test_two"),
            ]
        )

        write_junit_xml(report, path)

        root = ET.parse(path).getroot()
        suite = root.find("testsuite")

        assert suite is not None
        assert len(suite.findall("testcase")) == 2
        assert suite.attrib["tests"] == "2"
        assert suite.attrib["failures"] == "0"
        assert suite.attrib["errors"] == "0"
        assert suite.attrib["skipped"] == "0"

    def test_reports_execution_time_in_seconds(self, tmp_path):
        path = tmp_path / "junit.xml"

        report = make_report(
            [make_test_run(latency_ms=123)],
            duration_ms=456,
        )

        write_junit_xml(report, path)

        root = ET.parse(path).getroot()
        suite = root.find("testsuite")
        assert suite is not None

        testcase = suite.find("testcase")
        assert testcase is not None

        assert testcase.attrib["time"] == "0.123"
        assert suite.attrib["time"] == "0.456"

    def test_pass_and_warn_are_not_reported_as_failures(self, tmp_path):
        path = tmp_path / "junit.xml"

        warning = EvaluationResult(
            passed=False,
            assertion="contains",
            expected="optional phrase",
            actual="different output",
            reason="Optional phrase was not found",
            severity="warn",
        )

        report = make_report(
            [
                make_test_run("passing_test", status="PASS"),
                make_test_run(
                    "warning_test",
                    status="WARN",
                    evaluations=[warning],
                ),
            ]
        )

        write_junit_xml(report, path)

        root = ET.parse(path).getroot()
        suite = root.find("testsuite")
        assert suite is not None

        passing_case = suite.find("./testcase[@name='passing_test']")
        warning_case = suite.find("./testcase[@name='warning_test']")

        assert passing_case is not None
        assert warning_case is not None

        assert passing_case.find("failure") is None
        assert warning_case.find("failure") is None

        system_out = warning_case.find("system-out")
        assert system_out is not None
        assert "Optional phrase was not found" in system_out.text

        assert suite.attrib["failures"] == "0"

    def test_failure_contains_diagnostic_details(self, tmp_path):
        path = tmp_path / "junit.xml"

        failure = EvaluationResult(
            passed=False,
            assertion="contains",
            expected="hello",
            actual="goodbye",
            reason="Required text missing",
            severity="fail",
        )

        report = make_report(
            [
                make_test_run(
                    "failing_test",
                    status="FAIL",
                    evaluations=[failure],
                )
            ]
        )

        write_junit_xml(report, path)

        root = ET.parse(path).getroot()
        suite = root.find("testsuite")
        assert suite is not None

        testcase = suite.find("testcase")
        assert testcase is not None

        failure_element = testcase.find("failure")
        assert failure_element is not None

        assert failure_element.attrib["message"] == "Required text missing"
        assert failure_element.attrib["type"] == "contains"
        assert "Expected: hello" in failure_element.text
        assert "Actual: goodbye" in failure_element.text
        assert suite.attrib["failures"] == "1"

    def test_multiple_failed_assertions_are_preserved(self, tmp_path):
        path = tmp_path / "junit.xml"

        evaluations = [
            EvaluationResult(
                passed=False,
                assertion="contains",
                expected="hello",
                actual="goodbye",
                reason="Missing greeting",
                severity="fail",
            ),
            EvaluationResult(
                passed=False,
                assertion="equals",
                expected="success",
                actual="error",
                reason="Unexpected result",
                severity="fail",
            ),
        ]

        report = make_report(
            [
                make_test_run(
                    "multiple_failures",
                    status="FAIL",
                    evaluations=evaluations,
                )
            ]
        )

        write_junit_xml(report, path)

        root = ET.parse(path).getroot()
        testcase = root.find("./testsuite/testcase")

        assert testcase is not None

        failures = testcase.findall("failure")
        assert len(failures) == 2

        messages = [failure.attrib["message"] for failure in failures]

        assert "Missing greeting" in messages
        assert "Unexpected result" in messages

    def test_special_characters_and_invalid_xml_characters(self, tmp_path):
        path = tmp_path / "junit.xml"

        test_id = 'case_<tag>&"\x01'
        reason = 'Failure: expected <hello> & received "goodbye"\x01'

        failure = EvaluationResult(
            passed=False,
            assertion="equals",
            expected="<hello>",
            actual="goodbye & more",
            reason=reason,
            severity="fail",
        )

        report = make_report(
            [
                make_test_run(
                    test_id,
                    status="FAIL",
                    evaluations=[failure],
                )
            ]
        )

        write_junit_xml(report, path)

        # Parsing also verifies that the generated XML is well-formed.
        root = ET.parse(path).getroot()
        testcase = root.find("./testsuite/testcase")

        assert testcase is not None
        assert testcase.attrib["name"] == 'case_<tag>&"'

        failure_element = testcase.find("failure")
        assert failure_element is not None
        assert failure_element.attrib["message"] == (
            'Failure: expected <hello> & received "goodbye"'
        )

        assert "\x01" not in path.read_text(encoding="utf-8")
