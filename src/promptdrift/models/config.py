"""Strict, serializable configuration models supporting v1 and v2 options."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .test import TestCase


class ResilienceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_retries: int = Field(default=0, ge=0, le=10)
    initial_backoff: float = Field(default=0.5, gt=0)
    backoff_factor: float = Field(default=2.0, ge=1.0)
    max_backoff: float = Field(default=10.0, gt=0)
    timeout: float = Field(default=60.0, gt=0)
    timeout_budget: float | None = Field(default=None, gt=0)
    request_budget: int | None = Field(default=None, gt=0)


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["openai", "ollama", "mock"]
    model: str = "mock"
    api_key_env: str | None = None
    base_url: str | None = None
    timeout: float | None = None
    max_retries: int | None = None
    initial_backoff: float | None = None
    backoff_factor: float | None = None
    max_backoff: float | None = None
    timeout_budget: float | None = None
    request_budget: int | None = None
    resilience: ResilienceConfig = Field(default_factory=ResilienceConfig)

    @model_validator(mode="after")
    def sync_resilience(self) -> ProviderConfig:
        if self.timeout is not None:
            self.resilience.timeout = self.timeout
        if self.max_retries is not None:
            self.resilience.max_retries = self.max_retries
        if self.initial_backoff is not None:
            self.resilience.initial_backoff = self.initial_backoff
        if self.backoff_factor is not None:
            self.resilience.backoff_factor = self.backoff_factor
        if self.max_backoff is not None:
            self.resilience.max_backoff = self.max_backoff
        if self.timeout_budget is not None:
            self.resilience.timeout_budget = self.timeout_budget
        if self.request_budget is not None:
            self.resilience.request_budget = self.request_budget
        return self


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temperature: float = Field(default=0, ge=0, le=2)
    max_output_tokens: int = Field(default=500, gt=0)


class BaselineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = "promptdrift.baseline.json"
    store_raw_output: bool = False


class CIConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fail_on: list[str] = ["assertion_failure"]
    warn_on: list[str] = ["semantic_change", "latency_regression"]


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "promptdrift-project"


class SourcesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompts: list[str] = Field(default_factory=lambda: ["prompts/**"])


class ScenariosConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file: str = ".promptdrift/scenarios.json"


class SemanticEvalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: Literal[False] = False
    provider: str | None = None
    model: str | None = None


class EvaluationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semantic: SemanticEvalConfig = Field(default_factory=SemanticEvalConfig)


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fail_on: list[str] = Field(default_factory=lambda: ["regression"])
    warn_on: list[str] = Field(default_factory=list)


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1, 2] = 1
    project: ProjectConfig | None = None
    provider: ProviderConfig
    defaults: Defaults = Field(default_factory=Defaults)
    baseline: BaselineConfig = Field(default_factory=BaselineConfig)
    ci: CIConfig = Field(default_factory=CIConfig)
    sources: SourcesConfig | None = None
    scenarios: ScenariosConfig | None = None
    evaluation: EvaluationConfig | None = None
    policy: PolicyConfig | None = None
    tests: list[TestCase] = Field(default_factory=list)

    @field_validator("tests")
    @classmethod
    def test_ids_are_unique(cls, tests: list[TestCase]) -> list[TestCase]:
        ids = [test.id for test in tests]
        if len(ids) != len(set(ids)):
            raise ValueError("test ids must be unique")
        return tests

    @model_validator(mode="after")
    def validate_tests_present(self) -> Config:
        if self.ci != CIConfig():
            raise ValueError(
                "ci policy customization is not implemented; use assertion severity and thresholds"
            )
        if self.policy and (self.policy.fail_on != ["regression"] or self.policy.warn_on):
            raise ValueError("only policy.fail_on: [regression] with an empty warn_on is supported")
        # If version is 1 or no scenarios config is specified, at least one test is required
        if self.version == 1 and not self.tests:
            raise ValueError("tests list cannot be empty for version: 1")
        if not self.tests and not self.scenarios and not self.sources:
            raise ValueError("either tests or scenarios must be configured")
        return self

    def resolve_path(self, config_path: Path, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else config_path.parent / path
