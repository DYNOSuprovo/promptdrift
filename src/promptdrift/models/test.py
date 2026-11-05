"""Models representing declarative test contracts."""

from __future__ import annotations

import math
import re
from typing import Any, Literal

from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for
from pydantic import BaseModel, ConfigDict, Field, model_validator

ASSERTION_TYPES = {
    "exact_match",
    "contains",
    "not_contains",
    "regex",
    "not_regex",
    "json_valid",
    "json_schema",
    "min_length",
    "max_length",
    "max_tokens",
    "latency_ms",
    "cost_usd",
}


class Assertion(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    type: Literal[
        "exact_match",
        "contains",
        "not_contains",
        "regex",
        "not_regex",
        "json_valid",
        "json_schema",
        "min_length",
        "max_length",
        "max_tokens",
        "latency_ms",
        "cost_usd",
    ]
    value: Any | None = None
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")
    name: str | None = None
    tolerance_percent: float | None = Field(default=None, ge=0)
    severity: Literal["fail", "warn"] = "fail"

    @model_validator(mode="after")
    def validate_payload(self) -> Assertion:
        if self.type == "json_schema":
            if self.schema_ is None:
                raise ValueError("json_schema assertions require a schema")
            try:
                validator_for(self.schema_).check_schema(self.schema_)
            except SchemaError as exc:
                raise ValueError("Invalid JSON schema") from exc
            _check_local_references(self.schema_)
        if self.type not in {"json_valid", "json_schema"} and self.value is None:
            raise ValueError(f"{self.type} assertions require a value")
        if self.type in {"regex", "not_regex"}:
            try:
                re.compile(str(self.value))
            except re.error as exc:
                raise ValueError("Invalid regex") from exc
        if self.type in {"min_length", "max_length", "max_tokens", "latency_ms", "cost_usd"}:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise ValueError("Numeric assertions require a non-negative number")
            if not math.isfinite(self.value) or self.value < 0:
                raise ValueError("Numeric assertions require a finite non-negative number")
            if (
                self.type in {"min_length", "max_length", "max_tokens"}
                and int(self.value) != self.value
            ):
                raise ValueError("Length and token assertions require an integer")
        return self

    @property
    def label(self) -> str:
        return self.name or self.type


def _check_local_references(value: Any) -> None:
    """Schemas must not retrieve remote resources while evaluating provider output."""
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                key in {"$ref", "$dynamicRef", "$recursiveRef"}
                and isinstance(item, str)
                and not item.startswith("#")
            ):
                raise ValueError("JSON schema references must be local fragments (#...)")
            _check_local_references(item)
    elif isinstance(value, list):
        for item in value:
            _check_local_references(item)


class Evaluator(BaseModel):
    """Reserved model for a future explicit probabilistic evaluator extension."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["semantic_similarity", "llm_judge", "similarity"]
    threshold: float | None = Field(default=None, ge=0, le=1)
    provider: str | None = None
    model: str | None = None


class OutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["text", "json"] = "text"


class Threshold(BaseModel):
    model_config = ConfigDict(extra="forbid")
    warn: float | None = Field(default=None, ge=0)
    fail: float | None = Field(default=None, ge=0)


class ToolSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class RequestEnvelope(BaseModel):
    """Declared request context for provenance only; it is never sent to a provider."""

    model_config = ConfigDict(extra="forbid")
    system: str | None = None
    tools: list[ToolSchema] = Field(default_factory=list)
    retrieval_context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_duplicate_tools(self) -> RequestEnvelope:
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("request_envelope tool names must be unique")
        return self


class TestCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    prompt: str
    variables: dict[str, Any] = Field(default_factory=dict)
    request_envelope: RequestEnvelope | None = None
    assertions: list[Assertion] = Field(default_factory=list)
    evaluators: list[Evaluator] = Field(default_factory=list)
    output: OutputConfig = Field(default_factory=OutputConfig)
    thresholds: dict[Literal["latency_ms", "cost_usd"], Threshold | float] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def reject_unimplemented_evaluators(self) -> TestCase:
        if self.evaluators:
            raise ValueError(
                "optional evaluators are not available; use deterministic assertions instead"
            )
        return self
