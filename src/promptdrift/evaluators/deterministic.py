"""Deterministic behavioral contract evaluators."""

from __future__ import annotations

import json
import re
from typing import Any

from jsonschema import ValidationError, validate
from referencing import Registry
from referencing.exceptions import Unresolvable

from promptdrift.errors import EvaluationError
from promptdrift.models.result import EvaluationResult, ModelResponse
from promptdrift.models.test import Assertion


def _result(
    assertion: Assertion, passed: bool, expected: Any, actual: Any, reason: str
) -> EvaluationResult:
    return EvaluationResult(
        passed=passed,
        assertion=assertion.label,
        expected=expected,
        actual=actual,
        reason=reason,
        severity=assertion.severity,
    )


def evaluate_assertion(assertion: Assertion, response: ModelResponse) -> EvaluationResult:
    text = response.output
    kind, value = assertion.type, assertion.value
    if kind == "exact_match":
        return _result(
            assertion,
            text == value,
            value,
            text,
            "Output exactly matches expected value."
            if text == value
            else "Output does not exactly match expected value.",
        )
    if kind == "contains":
        return _result(
            assertion,
            str(value) in text,
            value,
            text,
            "Required text appears in the output."
            if str(value) in text
            else "Required text does not appear in the output.",
        )
    if kind == "not_contains":
        return _result(
            assertion,
            str(value) not in text,
            value,
            text,
            "Forbidden text does not appear in the output."
            if str(value) not in text
            else "Forbidden text appears in the output.",
        )
    if kind in {"regex", "not_regex"}:
        try:
            matched = re.search(str(value), text) is not None
        except re.error as exc:
            raise EvaluationError(f"Invalid regex in {assertion.label}: {exc}") from exc
        passed = matched if kind == "regex" else not matched
        return _result(
            assertion,
            passed,
            value,
            text,
            "Pattern condition satisfied." if passed else "Pattern condition was not satisfied.",
        )
    if kind in {"json_valid", "json_schema"}:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            return _result(assertion, False, "valid JSON", text, f"Invalid JSON: {exc.msg}")
        if kind == "json_valid":
            return _result(assertion, True, "valid JSON", text, "Output is valid JSON.")
        try:
            validate(payload, assertion.schema_, registry=Registry())
            return _result(
                assertion, True, assertion.schema_, payload, "JSON matches the required schema."
            )
        except ValidationError as exc:
            return _result(
                assertion, False, assertion.schema_, payload, f"JSON schema failed: {exc.message}"
            )
        except Unresolvable as exc:
            raise EvaluationError("JSON schema references could not be resolved locally.") from exc
    if kind in {"min_length", "max_length"}:
        actual, expected = len(text), int(value)
        passed = actual >= expected if kind == "min_length" else actual <= expected
        comparison = "at least" if kind == "min_length" else "at most"
        return _result(
            assertion,
            passed,
            expected,
            actual,
            f"Output length is {comparison} {expected}."
            if passed
            else f"Output length must be {comparison} {expected} characters.",
        )
    if kind == "max_tokens":
        if response.output_tokens is None:
            return _result(assertion, False, int(value), None, "Output token usage is unavailable.")
        actual, expected = response.output_tokens, int(value)
        return _result(
            assertion,
            actual <= expected,
            expected,
            actual,
            "Output token limit met." if actual <= expected else "Output token limit exceeded.",
        )
    if kind == "latency_ms":
        actual, expected = response.latency_ms, float(value)
        tolerance = assertion.tolerance_percent
        upper_bound = expected * (1 + tolerance / 100) if tolerance is not None else expected
        passed = actual <= upper_bound
        within_tolerance = passed and actual > expected and tolerance is not None

        if within_tolerance:
            reason = (
                f"Latency {actual:g}ms passed (within {tolerance:g}% tolerance of {expected:g}ms)."
            )
        else:
            reason = "Latency limit met." if passed else "Latency limit exceeded."

        return _result(assertion, passed, expected, actual, reason)
    if kind == "cost_usd":
        if response.estimated_cost_usd is None:
            return _result(assertion, False, float(value), None, "Estimated cost is unavailable.")
        actual, expected = response.estimated_cost_usd, float(value)
        tolerance = assertion.tolerance_percent
        upper_bound = expected * (1 + tolerance / 100) if tolerance is not None else expected
        passed = actual <= upper_bound
        within_tolerance = passed and actual > expected and tolerance is not None

        if within_tolerance:
            reason = (
                f"Estimated cost ${actual:g} passed "
                f"(within {tolerance:g}% tolerance of ${expected:g})."
            )
        else:
            reason = "Estimated cost limit met." if passed else "Estimated cost limit exceeded."

        return _result(assertion, passed, expected, actual, reason)
    raise EvaluationError(f"Unsupported assertion type: {kind}")
