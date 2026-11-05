"""Bounded provider resilience executor with configurable retry backoff and timeout budgets."""

from __future__ import annotations

import email.utils
import time
from collections.abc import Callable

import httpx

from promptdrift.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderTransportError,
)
from promptdrift.models.config import ResilienceConfig
from promptdrift.models.result import ModelResponse


def parse_retry_after(header_val: str | None, current_time: float | None = None) -> float | None:
    """Parse HTTP Retry-After header as delay in seconds."""
    if not header_val or not header_val.strip():
        return None
    val = header_val.strip()
    try:
        seconds = float(val)
        return max(0.0, seconds)
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(val)
        now = current_time if current_time is not None else time.time()
        return max(0.0, dt.timestamp() - now)
    except Exception:
        return None


def calculate_backoff(
    attempt: int,
    config: ResilienceConfig,
    retry_after: float | None = None,
) -> float:
    """Calculate bounded exponential backoff delay, honoring Retry-After."""
    delay = config.initial_backoff * (config.backoff_factor**attempt)
    delay = min(config.max_backoff, delay)
    if retry_after is not None and retry_after > 0:
        delay = min(config.max_backoff, max(delay, retry_after))
    return max(0.0, delay)


def classify_error(exc: Exception, provider_name: str) -> tuple[ProviderError, bool, float | None]:
    """Classify an exception into a safe, non-leaking ProviderError subclass and retryability."""
    if isinstance(exc, ProviderError):
        if isinstance(exc, (ProviderRateLimitError, ProviderTransportError)):
            return exc, True, getattr(exc, "retry_after", None)
        if isinstance(exc, ProviderTimeoutError):
            return exc, True, None
        return exc, False, None

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        retry_after = parse_retry_after(exc.response.headers.get("retry-after"))
        if status == 429:
            return (
                ProviderRateLimitError(
                    f"{provider_name} request failed: HTTPStatusError (429 Too Many Requests)"
                ),
                True,
                retry_after,
            )
        if status in (401, 403):
            return (
                ProviderAuthError(f"{provider_name} request failed: HTTPStatusError ({status})"),
                False,
                None,
            )
        if status in (500, 502, 503, 504):
            return (
                ProviderTransportError(
                    f"{provider_name} request failed: HTTPStatusError ({status})"
                ),
                True,
                retry_after,
            )
        if 400 <= status < 500:
            return (
                ProviderResponseError(
                    f"{provider_name} request failed: HTTPStatusError ({status})"
                ),
                False,
                None,
            )
        return (
            ProviderError(f"{provider_name} request failed: HTTPStatusError ({status})"),
            False,
            None,
        )

    if isinstance(exc, httpx.TimeoutException):
        return (
            ProviderTimeoutError(f"{provider_name} request failed: {type(exc).__name__}"),
            True,
            None,
        )

    if isinstance(exc, (httpx.NetworkError, httpx.TransportError)):
        extra = ". Is Ollama running?" if provider_name.lower() == "ollama" else ""
        return (
            ProviderTransportError(f"{provider_name} request failed: {type(exc).__name__}{extra}"),
            True,
            None,
        )

    if isinstance(exc, httpx.HTTPError):
        return (
            ProviderTransportError(f"{provider_name} request failed: {type(exc).__name__}"),
            True,
            None,
        )

    if isinstance(exc, (KeyError, ValueError, IndexError, TypeError, AttributeError)):
        return (
            ProviderResponseError(f"{provider_name} request failed: {type(exc).__name__}"),
            False,
            None,
        )

    return (
        ProviderError(f"{provider_name} request failed: {type(exc).__name__}"),
        False,
        None,
    )


class ResilienceExecutor:
    """Manages execution retries with backoff, timeout budgets, and error categorization."""

    def __init__(
        self,
        config: ResilienceConfig,
        provider_name: str,
        clock: Callable[[], float] = time.perf_counter,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.provider_name = provider_name
        self.clock = clock
        self.sleeper = sleeper
        self.attempts_made = 0

    def execute(
        self,
        fn: Callable[[float], ModelResponse],
        start_time: float | None = None,
    ) -> ModelResponse:
        if start_time is None:
            start_time = self.clock()

        max_attempts = 1 + self.config.max_retries
        for attempt in range(max_attempts):
            self.attempts_made += 1
            elapsed = self.clock() - start_time
            if self.config.timeout_budget is not None:
                remaining_budget = self.config.timeout_budget - elapsed
                if remaining_budget <= 0:
                    raise ProviderTimeoutError(
                        f"{self.provider_name} request failed: timeout budget of {self.config.timeout_budget}s exceeded"
                    )
                current_timeout = min(self.config.timeout, remaining_budget)
            else:
                current_timeout = self.config.timeout

            try:
                return fn(current_timeout)
            except Exception as exc:
                err, is_retryable, retry_after = classify_error(exc, self.provider_name)
                is_last_attempt = attempt >= max_attempts - 1
                if not is_retryable or is_last_attempt:
                    raise err from exc

                delay = calculate_backoff(attempt, self.config, retry_after)
                elapsed_now = self.clock() - start_time
                if self.config.timeout_budget is not None:
                    if elapsed_now + delay >= self.config.timeout_budget:
                        raise ProviderTimeoutError(
                            f"{self.provider_name} request failed: timeout budget of {self.config.timeout_budget}s exceeded"
                        ) from exc

                self.sleeper(delay)

        raise ProviderError(f"{self.provider_name} request failed: max retries exhausted")
