from __future__ import annotations

from app.engine.models import Signal
from app.engine.profiles import PolicyProfile, default_profile


def effective_signals(signals: list[Signal], profile: PolicyProfile | None = None) -> list[Signal]:
    """Signals after applying profile ignores and weight overrides.

    Returned Signal objects keep their original id/category/source; the
    weight reflects what the active profile actually scored.
    """
    p = profile or default_profile()
    out: list[Signal] = []
    for s in signals:
        if s.category in p.ignore:
            continue
        w = p.weights.get(s.category, s.weight)
        if w == s.weight:
            out.append(s)
        else:
            out.append(
                Signal(
                    id=s.id,
                    category=s.category,
                    weight=w,
                    match=s.match,
                    source=s.source,
                    severity="high" if w >= 30 else ("medium" if w >= 10 else "low"),
                )
            )
    return out


def score_from_signals(signals: list[Signal], profile: PolicyProfile | None = None) -> int:
    score = sum(int(s.weight) for s in effective_signals(signals, profile))
    return min(100, max(0, score))


def confidence_from_signals(signals: list[Signal], profile: PolicyProfile | None = None) -> float:
    eff = effective_signals(signals, profile)
    if not eff:
        return 0.2
    # Simple MVP heuristic.
    total = sum(int(s.weight) for s in eff)
    if total >= 80:
        return 0.9
    if total >= 30:
        return 0.7
    return 0.5
