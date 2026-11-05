"""Offline coverage for OpenAI-compatible response normalization and safety."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from promptdrift.errors import ProviderError
from promptdrift.models.config import ProviderConfig
from promptdrift.providers.openai import OpenAIProvider

FIXTURES = Path(__file__).parents[1] / "fixtures" / "openai"


def _payload(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _install_payload(monkeypatch, name: str) -> None:
    payload = _payload(name)

    def fake_post(url: str, **kwargs):
        return httpx.Response(
            200,
            json=payload,
            request=httpx.Request("POST", url),
        )

    monkeypatch.setenv("TEST_OPENAI_KEY", "test-key")
    monkeypatch.setattr("promptdrift.providers.openai.httpx.post", fake_post)


def _install_malformed_payload(monkeypatch, name: str) -> None:
    raw_payload = (FIXTURES / name).read_text(encoding="utf-8")

    def fake_post(url: str, **kwargs):
        return httpx.Response(
            200,
            content=raw_payload.encode("utf-8"),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setenv("TEST_OPENAI_KEY", "test-key")
    monkeypatch.setattr("promptdrift.providers.openai.httpx.post", fake_post)


def test_full_fixture_normalizes_supported_response(monkeypatch):
    _install_payload(monkeypatch, "chat_completion_full.json")

    provider = OpenAIProvider(
        ProviderConfig(
            type="openai",
            model="configured-model",
            api_key_env="TEST_OPENAI_KEY",
        )
    )

    response = provider.complete(
        "test prompt",
        temperature=0,
        max_output_tokens=100,
    )

    assert response.output == "Hello PRIVATE_OPENAI_OUTPUT_SENTINEL"
    assert response.input_tokens == 5
    assert response.output_tokens == 3
    assert response.model == "configured-model"
    assert response.provider == "openai"
    assert response.resolved_model == "test-model"
    assert response.system_fingerprint == "fp_test_123"


def test_missing_usage_is_handled_safely(monkeypatch):
    _install_payload(monkeypatch, "chat_completion_no_usage.json")

    provider = OpenAIProvider(
        ProviderConfig(
            type="openai",
            model="configured-model",
            api_key_env="TEST_OPENAI_KEY",
        )
    )

    response = provider.complete(
        "test prompt",
        temperature=0,
        max_output_tokens=100,
    )

    assert response.output == "Hello WITHOUT_USAGE_SENTINEL"
    assert response.input_tokens is None
    assert response.output_tokens is None
    assert response.resolved_model == "test-model"
    assert response.system_fingerprint == "fp_test_123"


def test_missing_model_metadata_is_handled_safely(monkeypatch):
    _install_payload(monkeypatch, "chat_completion_no_model.json")

    provider = OpenAIProvider(
        ProviderConfig(
            type="openai",
            model="configured-model",
            api_key_env="TEST_OPENAI_KEY",
        )
    )

    response = provider.complete(
        "test prompt",
        temperature=0,
        max_output_tokens=100,
    )

    assert response.output == "Hello WITHOUT_MODEL_SENTINEL"
    assert response.resolved_model is None
    assert response.input_tokens == 5
    assert response.output_tokens == 3
    assert response.system_fingerprint == "fp_test_123"


def test_missing_system_fingerprint_is_handled_safely(monkeypatch):
    _install_payload(monkeypatch, "chat_completion_no_fingerprint.json")

    provider = OpenAIProvider(
        ProviderConfig(
            type="openai",
            model="configured-model",
            api_key_env="TEST_OPENAI_KEY",
        )
    )

    response = provider.complete(
        "test prompt",
        temperature=0,
        max_output_tokens=100,
    )

    assert response.output == "Hello WITHOUT_FINGERPRINT_SENTINEL"
    assert response.system_fingerprint is None
    assert response.resolved_model == "test-model"
    assert response.input_tokens == 5
    assert response.output_tokens == 3


def test_missing_choices_fails_safely(monkeypatch):
    _install_payload(monkeypatch, "chat_completion_missing_choices.json")

    provider = OpenAIProvider(
        ProviderConfig(
            type="openai",
            model="configured-model",
            api_key_env="TEST_OPENAI_KEY",
        )
    )

    with pytest.raises(ProviderError, match="OpenAI request failed"):
        provider.complete(
            "private prompt",
            temperature=0,
            max_output_tokens=100,
        )


def test_malformed_json_fails_safely(monkeypatch):
    _install_malformed_payload(monkeypatch, "chat_completion_malformed.json")

    provider = OpenAIProvider(
        ProviderConfig(
            type="openai",
            model="configured-model",
            api_key_env="TEST_OPENAI_KEY",
        )
    )

    with pytest.raises(ProviderError, match="OpenAI request failed") as error:
        provider.complete(
            "private prompt",
            temperature=0,
            max_output_tokens=100,
        )

    assert "PRIVATE_MALFORMED_JSON_SENTINEL" not in str(error.value)


@pytest.mark.parametrize(
    ("fixture_name", "private_value"),
    [
        (
            "chat_completion_missing_choices.json",
            "PRIVATE_MALFORMED_OPENAI_OUTPUT",
        ),
        (
            "chat_completion_non_string_content.json",
            "PRIVATE_NON_STRING_CONTENT",
        ),
        (
            "chat_completion_empty_choices.json",
            "PRIVATE_EMPTY_CHOICES_SENTINEL",
        ),
        (
            "chat_completion_missing_message.json",
            "PRIVATE_MISSING_MESSAGE_SENTINEL",
        ),
    ],
)
def test_invalid_response_shapes_fail_safely(monkeypatch, fixture_name, private_value):
    _install_payload(monkeypatch, fixture_name)

    provider = OpenAIProvider(
        ProviderConfig(
            type="openai",
            model="configured-model",
            api_key_env="TEST_OPENAI_KEY",
        )
    )

    with pytest.raises(ProviderError, match="OpenAI request failed") as error:
        provider.complete(
            "private prompt",
            temperature=0,
            max_output_tokens=100,
        )

    assert private_value not in str(error.value)
