"""Tests for bounded provider resilience, configurable retry backoff, and timeout budgets."""

from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import ValidationError

from promptdrift.engine.monitor import monitor_suite
from promptdrift.engine.runner import run_suite
from promptdrift.errors import (
    ProviderAuthError,
    ProviderBudgetExceededError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderTransportError,
)
from promptdrift.models import Config
from promptdrift.models.config import ProviderConfig, ResilienceConfig
from promptdrift.models.result import ModelResponse
from promptdrift.models.test import TestCase as DriftTestCase
from promptdrift.providers.ollama import OllamaProvider
from promptdrift.providers.openai import OpenAIProvider
from promptdrift.providers.resilience import (
    ResilienceExecutor,
    calculate_backoff,
    classify_error,
    parse_retry_after,
)


class FakeClock:
    """Deterministic simulated clock and sleeper for zero-wait tests."""

    def __init__(self, start: float = 1000.0):
        self._current = start
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self._current

    def sleep(self, duration: float) -> None:
        self.sleeps.append(duration)
        self._current += duration


class TestResilienceConfig:
    def test_defaults(self):
        cfg = ResilienceConfig()
        assert cfg.max_retries == 0
        assert cfg.initial_backoff == 0.5
        assert cfg.backoff_factor == 2.0
        assert cfg.max_backoff == 10.0
        assert cfg.timeout == 60.0
        assert cfg.timeout_budget is None
        assert cfg.request_budget is None

    def test_bounds_validation(self):
        with pytest.raises(ValidationError):
            ResilienceConfig(max_retries=-1)
        with pytest.raises(ValidationError):
            ResilienceConfig(max_retries=11)
        with pytest.raises(ValidationError):
            ResilienceConfig(initial_backoff=0)
        with pytest.raises(ValidationError):
            ResilienceConfig(timeout=-5)
        with pytest.raises(ValidationError):
            ResilienceConfig(extra_param=123)

    def test_provider_config_sync(self):
        cfg = ProviderConfig(
            type="openai",
            timeout=30.0,
            max_retries=3,
            timeout_budget=90.0,
            request_budget=50,
        )
        assert cfg.resilience.timeout == 30.0
        assert cfg.resilience.max_retries == 3
        assert cfg.resilience.timeout_budget == 90.0
        assert cfg.resilience.request_budget == 50

    def test_nested_resilience_config(self):
        cfg = ProviderConfig(
            type="ollama",
            resilience={
                "max_retries": 2,
                "initial_backoff": 1.0,
                "timeout": 45.0,
            },
        )
        assert cfg.resilience.max_retries == 2
        assert cfg.resilience.initial_backoff == 1.0
        assert cfg.resilience.timeout == 45.0


class TestErrorClassification:
    def test_rate_limit_429(self):
        resp = httpx.Response(
            429,
            headers={"Retry-After": "5"},
            request=httpx.Request("POST", "https://api.test"),
        )
        err = httpx.HTTPStatusError("429", request=resp.request, response=resp)
        classified, retryable, retry_after = classify_error(err, "OpenAI")
        assert isinstance(classified, ProviderRateLimitError)
        assert isinstance(classified, ProviderError)
        assert retryable is True
        assert retry_after == 5.0
        assert "OpenAI request failed" in str(classified)

    def test_auth_error_401(self):
        resp = httpx.Response(401, request=httpx.Request("POST", "https://api.test"))
        err = httpx.HTTPStatusError("401", request=resp.request, response=resp)
        classified, retryable, retry_after = classify_error(err, "OpenAI")
        assert isinstance(classified, ProviderAuthError)
        assert retryable is False
        assert retry_after is None
        assert "OpenAI request failed: HTTPStatusError (401)" in str(classified)

    def test_server_error_503(self):
        resp = httpx.Response(503, request=httpx.Request("POST", "https://api.test"))
        err = httpx.HTTPStatusError("503", request=resp.request, response=resp)
        classified, retryable, retry_after = classify_error(err, "OpenAI")
        assert isinstance(classified, ProviderTransportError)
        assert retryable is True

    def test_timeout_exception(self):
        err = httpx.ReadTimeout("Read timed out")
        classified, retryable, retry_after = classify_error(err, "OpenAI")
        assert isinstance(classified, ProviderTimeoutError)
        assert retryable is True
        assert "OpenAI request failed: ReadTimeout" in str(classified)

    def test_connect_error(self):
        err = httpx.ConnectError("Connection refused")
        classified, retryable, _ = classify_error(err, "Ollama")
        assert isinstance(classified, ProviderTransportError)
        assert retryable is True
        assert "Ollama request failed: ConnectError. Is Ollama running?" in str(classified)

    def test_response_malformed(self):
        err = KeyError("choices")
        classified, retryable, _ = classify_error(err, "OpenAI")
        assert isinstance(classified, ProviderResponseError)
        assert retryable is False
        assert "OpenAI request failed: KeyError" in str(classified)

    def test_payload_not_leaked_in_client_error(self):
        resp = httpx.Response(
            400,
            text='{"error": "SECRET_USER_INPUT_LEAK"}',
            request=httpx.Request("POST", "https://api.test"),
        )
        err = httpx.HTTPStatusError("400", request=resp.request, response=resp)
        classified, retryable, _ = classify_error(err, "OpenAI")
        assert isinstance(classified, ProviderResponseError)
        assert retryable is False
        assert "SECRET_USER_INPUT_LEAK" not in str(classified)


class TestBackoffCalculation:
    def test_exponential_curve(self):
        cfg = ResilienceConfig(initial_backoff=0.5, backoff_factor=2.0, max_backoff=10.0)
        assert calculate_backoff(0, cfg) == 0.5
        assert calculate_backoff(1, cfg) == 1.0
        assert calculate_backoff(2, cfg) == 2.0
        assert calculate_backoff(3, cfg) == 4.0
        assert calculate_backoff(4, cfg) == 8.0
        assert calculate_backoff(5, cfg) == 10.0  # Capped at max_backoff

    def test_retry_after_override(self):
        cfg = ResilienceConfig(initial_backoff=0.5, backoff_factor=2.0, max_backoff=10.0)
        # retry_after larger than exponential delay
        assert calculate_backoff(0, cfg, retry_after=3.5) == 3.5
        # retry_after exceeding max_backoff
        assert calculate_backoff(0, cfg, retry_after=20.0) == 10.0
        # retry_after smaller than exponential delay
        assert calculate_backoff(3, cfg, retry_after=2.0) == 4.0

    def test_parse_retry_after(self):
        assert parse_retry_after("5") == 5.0
        assert parse_retry_after("2.5") == 2.5
        assert parse_retry_after(None) is None
        assert parse_retry_after("invalid") is None
        assert parse_retry_after("-10") == 0.0


class TestResilienceExecutor:
    def test_success_on_first_try(self):
        clock = FakeClock()
        cfg = ResilienceConfig(max_retries=3)
        executor = ResilienceExecutor(cfg, "OpenAI", clock=clock.now, sleeper=clock.sleep)

        mock_call = MagicMock(
            return_value=ModelResponse(
                output="ok",
                latency_ms=10.0,
                model="test",
                provider="openai",
            )
        )
        res = executor.execute(mock_call)
        assert res.output == "ok"
        assert mock_call.call_count == 1
        assert clock.sleeps == []

    def test_retries_transient_error_and_succeeds(self):
        clock = FakeClock()
        cfg = ResilienceConfig(max_retries=2, initial_backoff=1.0, backoff_factor=2.0)
        executor = ResilienceExecutor(cfg, "OpenAI", clock=clock.now, sleeper=clock.sleep)

        resp_429 = httpx.Response(
            429,
            headers={"Retry-After": "3"},
            request=httpx.Request("POST", "https://api.test"),
        )
        calls = [
            httpx.HTTPStatusError("429", request=resp_429.request, response=resp_429),
            ModelResponse(output="recovered", latency_ms=10.0, model="test", provider="openai"),
        ]

        def call_fn(timeout):
            val = calls.pop(0)
            if isinstance(val, Exception):
                raise val
            return val

        res = executor.execute(call_fn)
        assert res.output == "recovered"
        assert clock.sleeps == [3.0]  # Respected Retry-After

    def test_exhausts_retries_and_raises(self):
        clock = FakeClock()
        cfg = ResilienceConfig(max_retries=2, initial_backoff=0.5, backoff_factor=2.0)
        executor = ResilienceExecutor(cfg, "OpenAI", clock=clock.now, sleeper=clock.sleep)

        def call_fn(timeout):
            raise httpx.ConnectError("Connection refused")

        with pytest.raises(ProviderTransportError) as exc_info:
            executor.execute(call_fn)

        assert "OpenAI request failed: ConnectError" in str(exc_info.value)
        assert executor.attempts_made == 3
        assert clock.sleeps == [0.5, 1.0]

    def test_terminal_error_fails_immediately(self):
        clock = FakeClock()
        cfg = ResilienceConfig(max_retries=3)
        executor = ResilienceExecutor(cfg, "OpenAI", clock=clock.now, sleeper=clock.sleep)

        resp_401 = httpx.Response(401, request=httpx.Request("POST", "https://api.test"))

        def call_fn(timeout):
            raise httpx.HTTPStatusError("401", request=resp_401.request, response=resp_401)

        with pytest.raises(ProviderAuthError):
            executor.execute(call_fn)

        assert executor.attempts_made == 1
        assert clock.sleeps == []

    def test_timeout_budget_clamps_call_timeout(self):
        clock = FakeClock()
        cfg = ResilienceConfig(timeout=30.0, timeout_budget=10.0)
        executor = ResilienceExecutor(cfg, "OpenAI", clock=clock.now, sleeper=clock.sleep)

        observed_timeouts = []

        def call_fn(timeout):
            observed_timeouts.append(timeout)
            clock.sleep(4.0)  # simulate call taking 4s
            return ModelResponse(output="ok", latency_ms=10.0, model="test", provider="openai")

        executor.execute(call_fn)
        assert observed_timeouts == [10.0]  # Clamped to remaining budget (10.0)

    def test_timeout_budget_exceeded_before_call(self):
        clock = FakeClock()
        cfg = ResilienceConfig(timeout=30.0, timeout_budget=5.0)
        executor = ResilienceExecutor(cfg, "OpenAI", clock=clock.now, sleeper=clock.sleep)

        # Record start time and advance clock beyond budget
        start = clock.now()
        clock._current += 6.0

        with pytest.raises(ProviderTimeoutError, match="timeout budget of 5.0s exceeded"):
            executor.execute(lambda t: None, start_time=start)

    def test_timeout_budget_prevents_further_retry_sleep(self):
        clock = FakeClock()
        # Budget of 2s, but initial backoff is 3s
        cfg = ResilienceConfig(max_retries=2, initial_backoff=3.0, timeout_budget=2.0)
        executor = ResilienceExecutor(cfg, "OpenAI", clock=clock.now, sleeper=clock.sleep)

        def call_fn(timeout):
            raise httpx.ReadTimeout("Timeout")

        with pytest.raises(ProviderTimeoutError, match="timeout budget of 2.0s exceeded"):
            executor.execute(call_fn)

        # Ensure we didn't waste time sleeping when budget was exceeded
        assert clock.sleeps == []


class TestUpfrontRequestBudgetGuardrails:
    def test_runner_rejects_exceeded_budget(self, tmp_path):
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("Hello {{ name }}")

        config = Config(
            provider=ProviderConfig(
                type="mock",
                request_budget=2,
            ),
            tests=[
                DriftTestCase(id="t1", prompt="prompt.txt", variables={"name": "A"}),
                DriftTestCase(id="t2", prompt="prompt.txt", variables={"name": "B"}),
                DriftTestCase(id="t3", prompt="prompt.txt", variables={"name": "C"}),
            ],
        )

        with pytest.raises(
            ProviderBudgetExceededError,
            match=r"Planned requests \(3\) exceed request budget \(2\)",
        ):
            run_suite(config, tmp_path / "promptdrift.yaml")

    def test_runner_allows_within_budget(self, tmp_path):
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("Hello {{ name }}")

        config = Config(
            provider=ProviderConfig(
                type="mock",
                request_budget=3,
            ),
            tests=[
                DriftTestCase(id="t1", prompt="prompt.txt", variables={"name": "A"}),
                DriftTestCase(id="t2", prompt="prompt.txt", variables={"name": "B"}),
            ],
        )

        report = run_suite(config, tmp_path / "promptdrift.yaml")
        assert len(report.tests) == 2

    def test_monitor_rejects_exceeded_budget(self, tmp_path):
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("Hello {{ name }}")
        baseline_file = tmp_path / "promptdrift.baseline.json"
        baseline_file.write_text(
            '{"schema_version": 3, "promptdrift_version": "0.1.0", "generated_at": "2026-01-01T00:00:00Z", "provider": {"type": "mock", "model": "mock"}, "tests": {}}'
        )

        config = Config(
            provider=ProviderConfig(
                type="mock",
                request_budget=5,
            ),
            tests=[
                DriftTestCase(id="t1", prompt="prompt.txt", variables={"name": "A"}),
                DriftTestCase(id="t2", prompt="prompt.txt", variables={"name": "B"}),
            ],
        )

        # 2 tests * 3 samples = 6 requests > budget of 5
        with pytest.raises(
            ProviderBudgetExceededError,
            match=r"Planned requests \(6\) exceed request budget \(5\)",
        ):
            monitor_suite(config, tmp_path / "promptdrift.yaml", samples=3)


class TestProviderIntegrationWithResilience:
    def test_openai_retries_transient_429(self, monkeypatch):
        clock = FakeClock()
        monkeypatch.setenv("TEST_KEY", "sk-test")

        resp_429 = httpx.Response(
            429,
            headers={"Retry-After": "2"},
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        )
        resp_200 = httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "recovered!"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        )

        post_responses = [resp_429, resp_200]

        def fake_post(*args, **kwargs):
            return post_responses.pop(0)

        monkeypatch.setattr("promptdrift.providers.openai.httpx.post", fake_post)

        cfg = ProviderConfig(
            type="openai",
            api_key_env="TEST_KEY",
            max_retries=2,
            initial_backoff=1.0,
        )
        provider = OpenAIProvider(cfg, clock=clock.now, sleeper=clock.sleep)
        res = provider.complete("test prompt", temperature=0.0, max_output_tokens=50)

        assert res.output == "recovered!"
        assert clock.sleeps == [2.0]

    def test_ollama_retries_connect_error(self, monkeypatch):
        clock = FakeClock()
        attempts = 0

        def fake_post(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise httpx.ConnectError("Connection refused")
            return httpx.Response(
                200,
                json={"response": "ollama response", "prompt_eval_count": 2, "eval_count": 2},
                request=httpx.Request("POST", "http://localhost:11434/api/generate"),
            )

        monkeypatch.setattr("promptdrift.providers.ollama.httpx.post", fake_post)

        cfg = ProviderConfig(
            type="ollama",
            max_retries=1,
            initial_backoff=0.5,
        )
        provider = OllamaProvider(cfg, clock=clock.now, sleeper=clock.sleep)
        res = provider.complete("test prompt", temperature=0.0, max_output_tokens=50)

        assert res.output == "ollama response"
        assert attempts == 2
        assert clock.sleeps == [0.5]
