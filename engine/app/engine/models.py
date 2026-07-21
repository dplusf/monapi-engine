from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


Decision = Literal["allow", "challenge", "block"]


@dataclass
class Signal:
    id: str
    category: str
    weight: int
    match: str
    source: str
    severity: str


@dataclass
class Evidence:
    source: str
    category: str
    match: str
    weight: int
    note: str | None = None


@dataclass
class DecisionAction:
    type: str
    retry_after_seconds: int
    reason: str


@dataclass
class EngineResult:
    decision: Decision
    action: DecisionAction | None
    score: int
    confidence: float
    signals: list[Signal]
    evidence: list[Evidence]
    enrichment: dict[str, Any]
