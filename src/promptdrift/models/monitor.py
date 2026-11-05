"""Privacy-minimized, versioned monitoring report contract."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field

from .provenance import Provenance

Diagnosis = Literal[
    "stable",
    "observed_model_drift",
    "prompt_changed",
    "configuration_changed",
    "contract_changed",
    "provider_changed",
    "provider_error",
    "insufficient_evidence",
    "new_test",
    "stochastic_behavior",
    "output_changed",
]


class MonitorCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    test_id: str
    status: Literal["PASS", "WARN", "FAIL", "ERROR"]
    diagnosis: Diagnosis
    summary: str
    samples: int
    failures: int = 0
    provider_errors: int = 0
    output_changes: int = 0
    evidence: list[str] = Field(default_factory=list)
    output_hash: str | None = None
    assertions: dict[str, bool] = Field(default_factory=dict)
    metrics: dict[str, float | int | None] = Field(default_factory=dict)
    provenance: Provenance | None = None


class MonitorReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    provider: str
    model: str
    samples: int
    baseline_path: str
    tests: list[MonitorCase]
    warnings: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def counts(self) -> dict[str, int]:
        return {
            status: sum(t.status == status for t in self.tests)
            for status in ("PASS", "WARN", "FAIL", "ERROR")
        }

    @computed_field
    @property
    def diagnosis_counts(self) -> dict[str, int]:
        return dict(Counter(test.diagnosis for test in self.tests))

    @property
    def exit_code(self) -> int:
        if self.counts["ERROR"]:
            return 3
        return 1 if self.counts["FAIL"] else 0
