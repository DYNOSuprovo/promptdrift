"""Tests for provider adapters."""

import httpx
import pytest

from promptdrift.errors import (
    ProviderAuthError,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from promptdrift.models.config import ProviderConfig
from promptdrift.providers import create_provider
from promptdrift.providers.mock import MockProvider
from promptdrift.providers.ollama import OllamaProvider
from promptdrift.providers.openai import OpenAIProvider


class TestOpenAIProvider:
    def test_normalizes_response(self, monkeypatch):
        def fake_post(*args, **kwargs):
            assert kwargs["headers"]["Authorization"] == "Bearer test-key"
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "hello"}}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1},
                },
                request=httpx.Request("POST", "https://example.test"),
            )

        monkeypatch.setenv("TEST_OPENAI_KEY", "test-key")
        monkeypatch.setattr("promptdrift.providers.openai.httpx.post", fake_post)
        provider = OpenAIProvider(
            ProviderConfig(type="openai", model="test-model", api_key_env="TEST_OPENAI_KEY")
        )
        response = provider.complete("test", temperature=0, max_output_tokens=10)
        assert response.output == "hello"
        assert response.input_tokens == 2
        assert response.output_tokens == 1
        assert response.provider == "openai"
        assert response.model == "test-model"

    def test_missing_key_raises_safe_error(self, monkeypatch):
        monkeypatch.delenv("MISSING_KEY", raising=False)
        provider = OpenAIProvider(
            ProviderConfig(type="openai", model="x", api_key_env="MISSING_KEY")
        )
        with pytest.raises(ProviderError, match="MISSING_KEY is not set"):
            provider.complete("test", temperature=0, max_output_tokens=10)

    def test_uses_default_api_key_env(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        provider = OpenAIProvider(ProviderConfig(type="openai", model="x"))
        with pytest.raises(ProviderError, match="OPENAI_API_KEY is not set"):
            provider.complete("test", temperature=0, max_output_tokens=10)

    def test_http_error_raises_provider_error(self, monkeypatch):
        def fake_post(*args, **kwargs):
            return httpx.Response(
                401,
                json={"error": "unauthorized"},
                request=httpx.Request("POST", "https://example.test"),
            )

        monkeypatch.setenv("TEST_KEY", "k")
        monkeypatch.setattr("promptdrift.providers.openai.httpx.post", fake_post)
        provider = OpenAIProvider(ProviderConfig(type="openai", model="x", api_key_env="TEST_KEY"))
        with pytest.raises(ProviderError, match="OpenAI request failed"):
            provider.complete("test", temperature=0, max_output_tokens=10)

    def test_custom_base_url(self, monkeypatch):
        called_url = None

        def fake_post(url, **kwargs):
            nonlocal called_url
            called_url = url
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "ok"}}], "usage": {}},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setenv("KEY", "k")
        monkeypatch.setattr("promptdrift.providers.openai.httpx.post", fake_post)
        provider = OpenAIProvider(
            ProviderConfig(
                type="openai",
                model="x",
                api_key_env="KEY",
                base_url="https://custom.api.test/v1/",
            )
        )
        provider.complete("test", temperature=0, max_output_tokens=10)
        assert called_url == "https://custom.api.test/v1/chat/completions"

    def test_error_does_not_leak_credentials(self, monkeypatch):
        def fake_post(*args, **kwargs):
            raise httpx.ConnectError("Connection refused")

        monkeypatch.setenv("SECRET_KEY", "sk-super-secret-12345")
        monkeypatch.setattr("promptdrift.providers.openai.httpx.post", fake_post)
        provider = OpenAIProvider(
            ProviderConfig(type="openai", model="x", api_key_env="SECRET_KEY")
        )
        with pytest.raises(ProviderError) as exc_info:
            provider.complete("test", temperature=0, max_output_tokens=10)
        assert "sk-super-secret" not in str(exc_info.value)
        assert isinstance(exc_info.value, ProviderConnectionError)

    def test_auth_error_raises_provider_auth_error(self, monkeypatch):
        def fake_post(*args, **kwargs):
            return httpx.Response(
                401,
                json={
                    "error": {
                        "message": "Invalid API key provided",
                        "type": "invalid_request_error",
                    }
                },
                request=httpx.Request("POST", "https://example.test"),
            )

        monkeypatch.setenv("TEST_KEY", "test-key-val")
        monkeypatch.setattr("promptdrift.providers.openai.httpx.post", fake_post)
        provider = OpenAIProvider(ProviderConfig(type="openai", model="x", api_key_env="TEST_KEY"))
        with pytest.raises(ProviderAuthError) as exc_info:
            provider.complete("test", temperature=0, max_output_tokens=10)
        # Verify response body and key are not leaked in message
        assert "Invalid API key provided" not in str(exc_info.value)
        assert "test-key-val" not in str(exc_info.value)

    def test_rate_limit_error_raises_provider_rate_limit_error(self, monkeypatch):
        def fake_post(*args, **kwargs):
            return httpx.Response(
                429,
                json={"error": {"message": "Rate limit exceeded"}},
                request=httpx.Request("POST", "https://example.test"),
            )

        monkeypatch.setenv("TEST_KEY", "k")
        monkeypatch.setattr("promptdrift.providers.openai.httpx.post", fake_post)
        provider = OpenAIProvider(ProviderConfig(type="openai", model="x", api_key_env="TEST_KEY"))
        with pytest.raises(ProviderRateLimitError):
            provider.complete("test", temperature=0, max_output_tokens=10)

    def test_timeout_raises_provider_timeout_error(self, monkeypatch):
        def fake_post(*args, **kwargs):
            raise httpx.ReadTimeout("Request timed out")

        monkeypatch.setenv("TEST_KEY", "k")
        monkeypatch.setattr("promptdrift.providers.openai.httpx.post", fake_post)
        provider = OpenAIProvider(ProviderConfig(type="openai", model="x", api_key_env="TEST_KEY"))
        with pytest.raises(ProviderTimeoutError):
            provider.complete("test", temperature=0, max_output_tokens=10)

    def test_malformed_response_raises_provider_response_error(self, monkeypatch):
        def fake_post(*args, **kwargs):
            return httpx.Response(
                200,
                json={"unexpected": "structure"},
                request=httpx.Request("POST", "https://example.test"),
            )

        monkeypatch.setenv("TEST_KEY", "k")
        monkeypatch.setattr("promptdrift.providers.openai.httpx.post", fake_post)
        provider = OpenAIProvider(ProviderConfig(type="openai", model="x", api_key_env="TEST_KEY"))
        with pytest.raises(ProviderResponseError):
            provider.complete("test", temperature=0, max_output_tokens=10)


class TestOllamaProvider:
    def test_normalizes_response(self, monkeypatch):
        def fake_post(*args, **kwargs):
            return httpx.Response(
                200,
                json={"response": "local", "prompt_eval_count": 3, "eval_count": 1},
                request=httpx.Request("POST", "http://localhost:11434/api/generate"),
            )

        monkeypatch.setattr("promptdrift.providers.ollama.httpx.post", fake_post)
        provider = OllamaProvider(ProviderConfig(type="ollama", model="llama3.2"))
        response = provider.complete("test", temperature=0, max_output_tokens=10)
        assert response.output == "local"
        assert response.input_tokens == 3
        assert response.output_tokens == 1
        assert response.provider == "ollama"

    def test_connection_error(self, monkeypatch):
        def fake_post(*args, **kwargs):
            raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr("promptdrift.providers.ollama.httpx.post", fake_post)
        provider = OllamaProvider(ProviderConfig(type="ollama", model="x"))
        with pytest.raises(ProviderError, match="Ollama request failed"):
            provider.complete("test", temperature=0, max_output_tokens=10)

    def test_custom_base_url(self, monkeypatch):
        called_url = None

        def fake_post(url, **kwargs):
            nonlocal called_url
            called_url = url
            return httpx.Response(
                200,
                json={"response": "ok"},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr("promptdrift.providers.ollama.httpx.post", fake_post)
        provider = OllamaProvider(
            ProviderConfig(
                type="ollama",
                model="x",
                base_url="http://remote:11434",
            )
        )
        provider.complete("test", temperature=0, max_output_tokens=10)
        assert called_url == "http://remote:11434/api/generate"

    def test_auth_error_raises_provider_auth_error(self, monkeypatch):
        def fake_post(*args, **kwargs):
            return httpx.Response(
                401,
                json={"error": "unauthorized access"},
                request=httpx.Request("POST", "http://localhost:11434/api/generate"),
            )

        monkeypatch.setattr("promptdrift.providers.ollama.httpx.post", fake_post)
        provider = OllamaProvider(ProviderConfig(type="ollama", model="x"))
        with pytest.raises(ProviderAuthError):
            provider.complete("test", temperature=0, max_output_tokens=10)

    def test_rate_limit_error_raises_provider_rate_limit_error(self, monkeypatch):
        def fake_post(*args, **kwargs):
            return httpx.Response(
                429,
                json={"error": "too many requests"},
                request=httpx.Request("POST", "http://localhost:11434/api/generate"),
            )

        monkeypatch.setattr("promptdrift.providers.ollama.httpx.post", fake_post)
        provider = OllamaProvider(ProviderConfig(type="ollama", model="x"))
        with pytest.raises(ProviderRateLimitError):
            provider.complete("test", temperature=0, max_output_tokens=10)

    def test_timeout_raises_provider_timeout_error(self, monkeypatch):
        def fake_post(*args, **kwargs):
            raise httpx.ConnectTimeout("connection timed out")

        monkeypatch.setattr("promptdrift.providers.ollama.httpx.post", fake_post)
        provider = OllamaProvider(ProviderConfig(type="ollama", model="x"))
        with pytest.raises(ProviderTimeoutError):
            provider.complete("test", temperature=0, max_output_tokens=10)

    def test_malformed_response_raises_provider_response_error(self, monkeypatch):
        def fake_post(*args, **kwargs):
            return httpx.Response(
                200,
                json={"not_response": 123},
                request=httpx.Request("POST", "http://localhost:11434/api/generate"),
            )

        monkeypatch.setattr("promptdrift.providers.ollama.httpx.post", fake_post)
        provider = OllamaProvider(ProviderConfig(type="ollama", model="x"))
        with pytest.raises(ProviderResponseError):
            provider.complete("test", temperature=0, max_output_tokens=10)


class TestMockProvider:
    def test_echoes_prompt(self):
        provider = MockProvider(ProviderConfig(type="mock", model="local-echo"))
        response = provider.complete("hello world", temperature=0, max_output_tokens=500)
        assert "hello world" in response.output

    def test_normalizes_whitespace(self):
        provider = MockProvider(ProviderConfig(type="mock", model="local-echo"))
        response = provider.complete(
            "  lots   of    spaces  ", temperature=0, max_output_tokens=500
        )
        assert "  " not in response.output  # Whitespace collapsed

    def test_zero_cost(self):
        provider = MockProvider(ProviderConfig(type="mock", model="local-echo"))
        response = provider.complete("test", temperature=0, max_output_tokens=500)
        assert response.estimated_cost_usd == 0.0
        assert response.provider == "mock"

    def test_respects_max_tokens_truncation(self):
        provider = MockProvider(ProviderConfig(type="mock", model="local-echo"))
        response = provider.complete("x " * 1000, temperature=0, max_output_tokens=1)
        assert len(response.output) <= 4  # max_output_tokens * 4 chars


class TestProviderFactory:
    def test_creates_openai(self):
        provider = create_provider(ProviderConfig(type="openai", model="gpt-4"))
        assert isinstance(provider, OpenAIProvider)

    def test_creates_ollama(self):
        provider = create_provider(ProviderConfig(type="ollama", model="llama3"))
        assert isinstance(provider, OllamaProvider)

    def test_creates_mock(self):
        provider = create_provider(ProviderConfig(type="mock", model="echo"))
        assert isinstance(provider, MockProvider)
