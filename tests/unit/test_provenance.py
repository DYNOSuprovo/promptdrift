"""Request-envelope provenance: deterministic, credential-safe, component-attributed."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from promptdrift.engine.baseline import load_baseline, write_baseline
from promptdrift.engine.monitor import monitor_suite
from promptdrift.engine.provenance import envelope_hashes, fingerprint, strip_credentials
from promptdrift.engine.runner import run_suite
from promptdrift.models import Config
from promptdrift.models.test import RequestEnvelope


def envelope(**overrides):
    data = {
        "system": "You are a support agent.",
        "tools": [
            {
                "name": "lookup_order",
                "description": "Find an order by id.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string"},
                        "max_tokens": {"type": "integer"},
                    },
                    "required": ["order_id"],
                },
            }
        ],
        "retrieval_context": {"policy": {"refund_days": 30, "region": "EU"}, "faq": ["a", "b"]},
    }
    data.update(overrides)
    return RequestEnvelope.model_validate(data)


def configured(tmp_path, request_envelope=None):
    test = {
        "id": "policy",
        "prompt": "policy.txt",
        "variables": {"days": 30},
        "assertions": [{"type": "contains", "value": "30 days"}],
    }
    if request_envelope is not None:
        test["request_envelope"] = request_envelope
    config = Config.model_validate({"provider": {"type": "mock", "model": "echo"}, "tests": [test]})
    (tmp_path / "policy.txt").write_text("Refunds: {{ days }} days", encoding="utf-8")
    path = tmp_path / "promptdrift.yaml"
    path.write_text(json.dumps(config.model_dump(mode="json")), encoding="utf-8")
    return config, path


def test_hashes_ignore_key_order_including_nested():
    first = envelope()
    second = RequestEnvelope.model_validate(
        {
            "retrieval_context": {"faq": ["a", "b"], "policy": {"region": "EU", "refund_days": 30}},
            "tools": [
                {
                    "parameters": {
                        "required": ["order_id"],
                        "properties": {
                            "max_tokens": {"type": "integer"},
                            "order_id": {"type": "string"},
                        },
                        "type": "object",
                    },
                    "description": "Find an order by id.",
                    "name": "lookup_order",
                }
            ],
            "system": "You are a support agent.",
        }
    )
    assert envelope_hashes(first) == envelope_hashes(second)


@pytest.mark.parametrize(
    ("component", "value"),
    [
        ("system", "You are a billing agent."),
        ("tools", [{"name": "lookup_order", "description": "Find an order."}]),
        ("retrieval_context", {"policy": {"refund_days": 14, "region": "EU"}, "faq": ["a", "b"]}),
    ],
)
def test_each_component_changes_only_its_own_hash(component, value):
    before = envelope_hashes(envelope())
    after = envelope_hashes(envelope(**{component: value}))
    assert {name for name in before if before[name] != after[name]} == {component}


def test_credentials_do_not_affect_hashes():
    def with_secrets(key, bearer):
        return envelope(
            tools=[
                {
                    "name": "lookup_order",
                    "parameters": {"api_key": key, "headers": {"Authorization": bearer}},
                }
            ],
            retrieval_context={"X-API-Key": key, "notes": f"use {key} here", "source": "kb"},
        )

    first = with_secrets("sk-" + "a" * 32, "Bearer " + "b" * 32)
    second = with_secrets("sk-" + "c" * 32, "Bearer " + "d" * 32)
    assert envelope_hashes(first) == envelope_hashes(second)
    stripped = json.dumps(strip_credentials(first.model_dump(mode="json")))
    assert "a" * 32 not in stripped and "b" * 32 not in stripped
    assert "api_key" not in stripped and "Authorization" not in stripped


@pytest.mark.parametrize(
    "key", ["password", "privateKey", "refresh_token", "session-token", "cookie", "Set-Cookie"]
)
def test_sensitive_keys_are_removed_case_and_separator_insensitively(key):
    assert strip_credentials({key: "value", "kept": 1}) == {"kept": 1}


def test_schema_property_named_like_a_credential_still_counts():
    def password_tool(kind):
        return envelope(
            tools=[{"name": "login", "parameters": {"properties": {"password": {"type": kind}}}}]
        )

    assert envelope_hashes(password_tool("string")) != envelope_hashes(password_tool("integer"))
    assert strip_credentials({"max_tokens": 5}) == {"max_tokens": 5}


@pytest.mark.parametrize("text", ["risk-assessment", "task-scheduler.v2"])
def test_ordinary_text_is_never_redacted(text):
    assert strip_credentials(text) == text


def test_editing_a_risk_description_changes_the_tools_hash():
    def described(text):
        return envelope(tools=[{"name": "triage", "description": text}])

    before = envelope_hashes(described("Run the risk-assessment workflow."))
    after = envelope_hashes(described("Run the risk-evaluation workflow."))
    assert before["tools"] != after["tools"]


TOOLS = [
    {"name": "lookup_order", "description": "Find an order.", "parameters": {"type": "object"}},
    {"name": "refund_order", "description": "Refund an order.", "parameters": {"type": "object"}},
]


def test_tool_declaration_order_does_not_change_tools_hash():
    declared = envelope(tools=TOOLS)
    reordered = envelope(tools=list(reversed(TOOLS)))
    assert envelope_hashes(declared) == envelope_hashes(reordered)
    # Sorting happens only while hashing; the model keeps the declared order.
    assert [tool.name for tool in reordered.tools] == ["refund_order", "lookup_order"]


@pytest.mark.parametrize(
    "change",
    [
        {"name": "cancel_order"},
        {"description": "Find an order by id."},
        {"parameters": {"type": "object", "required": ["order_id"]}},
    ],
)
def test_changing_a_tool_changes_tools_hash(change):
    changed = [{**TOOLS[0], **change}, TOOLS[1]]
    assert (
        envelope_hashes(envelope(tools=TOOLS))["tools"]
        != (envelope_hashes(envelope(tools=changed))["tools"])
    )


def test_lists_inside_tool_parameters_keep_declared_order():
    def tool(required):
        return envelope(tools=[{"name": "t", "parameters": {"required": required}}])

    assert envelope_hashes(tool(["a", "b"]))["tools"] != envelope_hashes(tool(["b", "a"]))["tools"]


def test_duplicate_tool_names_are_rejected():
    with pytest.raises(ValidationError, match="unique"):
        envelope(tools=[{"name": "a"}, {"name": "a"}])


def test_case_without_envelope_keeps_previous_provenance(tmp_path):
    config, path = configured(tmp_path)
    provenance = fingerprint(config, config.tests[0], "Refunds: 30 days")
    assert provenance.envelope_hashes is None
    assert set(json.loads(provenance.model_dump_json())) == {
        "input_hash",
        "configuration_hash",
        "contract_hash",
        "provider_hash",
        "engine_version",
        "response_model_hash",
        "system_fingerprint_hash",
    }
    with_envelope = config.tests[0].model_copy(
        update={"request_envelope": RequestEnvelope(system="x")}
    )
    other = fingerprint(config, with_envelope, "Refunds: 30 days")
    assert other.model_dump(exclude={"envelope_hashes"}) == provenance.model_dump(
        exclude={"envelope_hashes"}
    )


def test_old_baseline_without_envelope_loads_and_reports_no_envelope_drift(tmp_path):
    config, path = configured(tmp_path)
    baseline_path = tmp_path / config.baseline.path
    write_baseline(baseline_path, run_suite(config, path))
    assert "envelope_hashes" not in baseline_path.read_text(encoding="utf-8")
    assert load_baseline(baseline_path).tests["policy"].provenance.envelope_hashes is None
    case = monitor_suite(config, path, samples=2).tests[0]
    assert case.diagnosis == "stable"
    assert not any("request_envelope" in item for item in case.evidence)


def test_envelope_hashes_round_trip_through_baseline(tmp_path):
    config, path = configured(tmp_path, envelope().model_dump(mode="json"))
    baseline_path = tmp_path / config.baseline.path
    write_baseline(baseline_path, run_suite(config, path))
    stored = load_baseline(baseline_path).tests["policy"].provenance.envelope_hashes
    assert stored == envelope_hashes(envelope())
    assert monitor_suite(config, path, samples=2).tests[0].diagnosis == "stable"


def test_monitor_evidence_names_the_drifted_component(tmp_path):
    config, path = configured(tmp_path, envelope().model_dump(mode="json"))
    write_baseline(tmp_path / config.baseline.path, run_suite(config, path))
    config.tests[0].request_envelope = envelope(tools=[{"name": "refund_order"}])
    case = monitor_suite(config, path, samples=2).tests[0]
    assert case.diagnosis == "prompt_changed"
    envelope_evidence = [item for item in case.evidence if "request_envelope" in item]
    assert envelope_evidence == ["request_envelope.tools differs from the accepted baseline."]


def test_adding_an_envelope_after_baselining_is_reported(tmp_path):
    config, path = configured(tmp_path)
    write_baseline(tmp_path / config.baseline.path, run_suite(config, path))
    config.tests[0].request_envelope = envelope()
    case = monitor_suite(config, path, samples=2).tests[0]
    assert case.diagnosis == "prompt_changed"
    assert "request_envelope was added since the accepted baseline." in case.evidence
