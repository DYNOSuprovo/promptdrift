"""Small OpenAI Chat Completions adapter without SDK coupling."""

from __future__ import annotations

import os
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


class OpenAIProvider(Provider):
    def __init__(self, config):
        self.config = config

    def complete(self, prompt: str, *, temperature: float, max_output_tokens: int) -> ModelResponse:
        env_name = self.config.api_key_env or "OPENAI_API_KEY"
        api_key = os.environ.get(env_name)
        if not api_key:
            raise ProviderAuthError(
                f"{env_name} is not set. Set it before using the OpenAI provider."
            )
        start = time.perf_counter()
        try:
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
                timeout=60,
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
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
                model=self.config.model,
                provider="openai",
                resolved_model=payload.get("model"),
                system_fingerprint=payload.get("system_fingerprint"),
                estimated_cost_usd=None,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"OpenAI request failed: timeout ({type(exc).__name__})"
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (401, 403):
                raise ProviderAuthError(
                    f"OpenAI request failed: HTTP {status} (authentication error). Check your API key."
                ) from exc
            if status == 429:
                raise ProviderRateLimitError(
                    f"OpenAI request failed: HTTP {status} (rate limit exceeded). Check your quota."
                ) from exc
            raise ProviderError(f"OpenAI request failed: HTTP {status}") from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise ProviderConnectionError(
                f"OpenAI request failed: connection error ({type(exc).__name__})"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"OpenAI request failed: {type(exc).__name__}") from exc
        except (
            KeyError,
            ValueError,
            IndexError,
            TypeError,
            AttributeError,
        ) as exc:
            # Do not include response bodies: they can contain sensitive prompt data.
            raise ProviderResponseError(
                f"OpenAI request failed: malformed response ({type(exc).__name__})"
            ) from exc
