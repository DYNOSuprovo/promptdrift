"""Small OpenAI Chat Completions adapter without SDK coupling."""

from __future__ import annotations

import os
import time
from collections.abc import Callable

import httpx

from promptdrift.errors import ProviderAuthError
from promptdrift.models.result import ModelResponse

from .base import Provider
from .resilience import ResilienceExecutor


class OpenAIProvider(Provider):
    def __init__(
        self,
        config,
        executor: ResilienceExecutor | None = None,
        clock: Callable[[], float] = time.perf_counter,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.executor = executor or ResilienceExecutor(
            self.config.resilience,
            provider_name="OpenAI",
            clock=clock,
            sleeper=sleeper,
        )

    def complete(self, prompt: str, *, temperature: float, max_output_tokens: int) -> ModelResponse:
        env_name = self.config.api_key_env or "OPENAI_API_KEY"
        api_key = os.environ.get(env_name)
        if not api_key:
            raise ProviderAuthError(
                f"{env_name} is not set. Set it before using the OpenAI provider."
            )
        start = self.executor.clock()

        def _attempt(timeout: float) -> ModelResponse:
            response = httpx.post(
                (self.config.base_url or "https://api.openai.com/v1").rstrip("/")
                + "/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": self.config.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                    "max_tokens": max_output_tokens,
                },
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            usage = payload.get("usage", {})
            output = payload["choices"][0]["message"]["content"]
            if not isinstance(output, str):
                raise ValueError("Expected a text completion")
            return ModelResponse(
                output=output,
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
                latency_ms=round((self.executor.clock() - start) * 1000, 2),
                model=self.config.model,
                provider="openai",
                resolved_model=payload.get("model"),
                system_fingerprint=payload.get("system_fingerprint"),
                estimated_cost_usd=None,
            )

        res = self.executor.execute(_attempt, start_time=start)
        res.latency_ms = round((self.executor.clock() - start) * 1000, 2)
        return res
