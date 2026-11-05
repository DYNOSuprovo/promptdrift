"""Ollama generation adapter."""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from promptdrift.models.result import ModelResponse

from .base import Provider
from .resilience import ResilienceExecutor


class OllamaProvider(Provider):
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
            provider_name="Ollama",
            clock=clock,
            sleeper=sleeper,
        )

    def complete(self, prompt: str, *, temperature: float, max_output_tokens: int) -> ModelResponse:
        start = self.executor.clock()

        def _attempt(timeout: float) -> ModelResponse:
            response = httpx.post(
                (self.config.base_url or "http://localhost:11434").rstrip("/") + "/api/generate",
                json={
                    "model": self.config.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_output_tokens},
                },
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            output = payload["response"]
            if not isinstance(output, str):
                raise ValueError("Expected a text completion")
            return ModelResponse(
                output=output,
                input_tokens=payload.get("prompt_eval_count"),
                output_tokens=payload.get("eval_count"),
                latency_ms=round((self.executor.clock() - start) * 1000, 2),
                model=self.config.model,
                provider="ollama",
                resolved_model=payload.get("model"),
                estimated_cost_usd=0.0,
            )

        res = self.executor.execute(_attempt, start_time=start)
        res.latency_ms = round((self.executor.clock() - start) * 1000, 2)
        return res
