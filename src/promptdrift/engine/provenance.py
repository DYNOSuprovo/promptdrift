"""Fingerprint the exact monitored inputs without persisting their contents."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from promptdrift import __version__
from promptdrift.models import Config, TestCase
from promptdrift.models.provenance import Provenance
from promptdrift.models.result import ModelResponse
from promptdrift.models.test import RequestEnvelope

ENVELOPE_COMPONENTS = ("system", "tools", "retrieval_context")
# Exact matches after lowercasing and removing "-"/"_"; substrings would catch e.g. max_tokens.
CREDENTIAL_KEYS = frozenset(
    {
        "apikey",
        "xapikey",
        "token",
        "accesstoken",
        "refreshtoken",
        "sessiontoken",
        "secret",
        "clientsecret",
        "password",
        "privatekey",
        "authorization",
        "credential",
        "credentials",
        "cookie",
        "setcookie",
    }
)
# Word-bounded and long, so ordinary text such as "risk-assessment" is never altered.
CREDENTIAL_VALUE_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}|\bBearer\s+\S{20,}")


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def strip_credentials(value: Any) -> Any:
    """Drop scalar values under credential-named keys and mask token-shaped strings."""
    if isinstance(value, dict):
        return {
            key: strip_credentials(item)
            for key, item in value.items()
            if isinstance(item, (dict, list))
            or str(key).lower().replace("-", "").replace("_", "") not in CREDENTIAL_KEYS
        }
    if isinstance(value, list):
        return [strip_credentials(item) for item in value]
    if isinstance(value, str):
        return CREDENTIAL_VALUE_PATTERN.sub("[REDACTED]", value)
    return value


def envelope_hashes(envelope: RequestEnvelope | None) -> dict[str, str] | None:
    if envelope is None:
        return None
    data = strip_credentials(envelope.model_dump(mode="json"))
    # Names are unique, so name order is unambiguous; lists inside parameters keep their order.
    data["tools"] = sorted(data["tools"], key=lambda tool: tool["name"])
    return {component: digest(data[component]) for component in ENVELOPE_COMPONENTS}


def fingerprint(config: Config, test: TestCase, prompt: str) -> Provenance:
    default_url = {
        "openai": "https://api.openai.com/v1",
        "ollama": "http://localhost:11434",
        "mock": "",
    }[config.provider.type]
    return Provenance(
        input_hash=digest(prompt),
        configuration_hash=digest(config.defaults.model_dump(mode="json")),
        contract_hash=digest(
            {
                "assertions": [item.model_dump(mode="json") for item in test.assertions],
                "thresholds": test.model_dump(mode="json")["thresholds"],
                "output": test.output.model_dump(mode="json"),
            }
        ),
        provider_hash=digest(
            {
                "type": config.provider.type,
                "model": config.provider.model,
                "endpoint": (config.provider.base_url or default_url).rstrip("/"),
            }
        ),
        engine_version=__version__,
        envelope_hashes=envelope_hashes(test.request_envelope),
    )


def with_response(provenance: Provenance, response: ModelResponse) -> Provenance:
    result = provenance.model_copy()
    result.response_model_hash = (
        digest(response.resolved_model) if response.resolved_model else None
    )
    result.system_fingerprint_hash = (
        digest(response.system_fingerprint) if response.system_fingerprint else None
    )
    return result
