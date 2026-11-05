"""Ollama generation adapter."""

from __future__ import annotations

import time

import httpx

from promptdrift.errors import (
    ProviderAuthError,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from promptdrift.models.result import ModelResponse

from .base import Provider


class OllamaProvider(Provider):
    def __init__(self, config):
        self.config = config

    def complete(self, prompt: str, *, temperature: float, max_output_tokens: int) -> ModelResponse:
        start = time.perf_counter()
        try:
            response = httpx.post(
                (self.config.base_url or "http://localhost:11434").rstrip("/") + "/api/generate",
                json={
                    "model": self.config.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_output_tokens},
                },
                timeout=90,
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
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
                model=self.config.model,
                provider="ollama",
                resolved_model=payload.get("model"),
                estimated_cost_usd=0.0,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"Ollama request failed: timeout ({type(exc).__name__})"
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (401, 403):
                raise ProviderAuthError(
                    f"Ollama request failed: HTTP {status} (authentication error)"
                ) from exc
            if status == 429:
                raise ProviderRateLimitError(
                    f"Ollama request failed: HTTP {status} (rate limit exceeded)"
                ) from exc
            raise ProviderError(f"Ollama request failed: HTTP {status}") from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise ProviderConnectionError(
                f"Ollama request failed: {type(exc).__name__}. Is Ollama running?"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama request failed: {type(exc).__name__}") from exc
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ProviderResponseError(
                f"Ollama request failed: malformed response ({type(exc).__name__})"
            ) from exc
