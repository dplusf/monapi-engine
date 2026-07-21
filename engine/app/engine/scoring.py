from __future__ import annotations

from app.engine.models import Signal


def score_from_signals(signals: list[Signal]) -> int:
    score = 0
    for s in signals:
        score += int(s.weight)
    return min(100, max(0, score))


def confidence_from_signals(signals: list[Signal]) -> float:
    if not signals:
        return 0.2
    # Simple MVP heuristic.
    total = sum(int(s.weight) for s in signals)
    if total >= 80:
        return 0.9
    if total >= 30:
        return 0.7
    return 0.5
