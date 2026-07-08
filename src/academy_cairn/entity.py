"""Core data types: entity refs, readings, and score events."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

EntityType = Literal["data_source", "capability", "agent"]


class EntityRef(BaseModel):
    type: EntityType
    external_id: str


class Reading(BaseModel):
    composite_score: float
    confidence: float
    last_updated: str | None = None

    @classmethod
    def no_data(cls) -> "Reading":
        return cls(composite_score=0.5, confidence=0.0, last_updated=None)


class ScoreEvent(BaseModel):
    reviewee: EntityRef
    score: float
    context: str = "general"
    weight: float | None = None
    task: str | None = None
    dimensions: dict[str, float] | None = None
    rationale: str | None = None
    failure_modes: list[str] | None = None
    metrics: dict[str, float] | None = None
    observed_at: str | None = None

    def to_payload(self) -> dict[str, object]:
        return self.model_dump(exclude_none=True)


def agent_entity(namespace: str, agent_name: str) -> EntityRef:
    return EntityRef(type="agent", external_id=f"agent://academy/{namespace}/{agent_name}")


_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def snake_case(name: str) -> str:
    s = _CAMEL.sub("_", name).lower()
    s = re.sub(r"[^a-z0-9_]", "_", s).strip("_")
    if not s or not s[0].isalpha():
        s = f"e_{s}" if s else "unknown"
    return s[:64]
