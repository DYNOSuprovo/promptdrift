"""Execution engine connecting templates, providers, contracts and baselines."""

from __future__ import annotations

import time
from pathlib import Path

from promptdrift.engine.provenance import fingerprint, with_response
from promptdrift.errors import ProviderBudgetExceededError
from promptdrift.evaluators import evaluate_assertion
from promptdrift.models import Config, RegressionReport, TestRun
from promptdrift.models.result import EvaluationResult, ModelResponse
from promptdrift.models.test import TestCase
from promptdrift.providers import create_provider
from promptdrift.templates import render_prompt


def _threshold_results(test, response):
    """Translate shorthand thresholds into deterministic warning/failure evaluations."""
    results = []
    for metric, threshold in test.thresholds.items():
        warning = threshold.warn if hasattr(threshold, "warn") else None
        failure = threshold.fail if hasattr(threshold, "fail") else float(threshold)
        actual = response.latency_ms if metric == "latency_ms" else response.estimated_cost_usd
        if actual is None:
            results.append(
                EvaluationResult(
                    passed=False,
                    assertion=metric,
                    actual=None,
                    reason=f"{metric} is unavailable; the configured limit cannot be checked.",
                    severity="fail" if failure is not None else "warn",
                )
            )
            continue
        if failure is not None and actual > failure:
            results.append(
                EvaluationResult(
                    passed=False,
                    assertion=metric,
                    expected=failure,
                    actual=actual,
                    reason=f"{metric} exceeded failure threshold.",
                    severity="fail",
                )
            )
        elif warning is not None and actual > warning:
            results.append(
                EvaluationResult(
                    passed=False,
                    assertion=metric,
                    expected=warning,
                    actual=actual,
                    reason=f"{metric} exceeded warning threshold.",
                    severity="warn",
                )
            )
    return results


def evaluate_response(test: TestCase, response: ModelResponse) -> list[EvaluationResult]:
    results = [evaluate_assertion(assertion, response) for assertion in test.assertions]
    if test.output.format == "json":
        from promptdrift.models.test import Assertion

        results.append(
            evaluate_assertion(Assertion(type="json_valid", name="output.format"), response)
        )
    return results + _threshold_results(test, response)


def evaluation_status(evaluations: list[EvaluationResult]) -> str:
    if any(not item.passed and item.severity == "fail" for item in evaluations):
        return "FAIL"
    return "WARN" if any(not item.passed for item in evaluations) else "PASS"


def run_suite(config: Config, config_path: Path) -> RegressionReport:
    start = time.perf_counter()
    prepared = [
        (test, render_prompt(config.resolve_path(config_path, test.prompt), test.variables))
        for test in config.tests
    ]
    request_budget = config.provider.resilience.request_budget
    if request_budget is not None and len(prepared) > request_budget:
        raise ProviderBudgetExceededError(
            f"Planned requests ({len(prepared)}) exceed request budget ({request_budget})"
        )
    provider = create_provider(config.provider)
    runs: list[TestRun] = []
    for test, prompt in prepared:
        response = provider.complete(
            prompt,
            temperature=config.defaults.temperature,
            max_output_tokens=config.defaults.max_output_tokens,
        )
        evaluations = evaluate_response(test, response)
        status = evaluation_status(evaluations)
        runs.append(
            TestRun(
                test_id=test.id,
                provider=response.provider,
                model=response.model,
                input=prompt,
                output=response.output,
                latency_ms=response.latency_ms,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                estimated_cost_usd=response.estimated_cost_usd,
                provenance=with_response(fingerprint(config, test, prompt), response),
                evaluations=evaluations,
                status=status,
            )
        )
    return RegressionReport(
        provider=config.provider.type,
        model=config.provider.model,
        tests=runs,
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
    )
