from __future__ import annotations

import ipaddress
import time
from typing import Any

from app.adapters.index import IndexStore
from app.engine.models import Evidence, EngineResult, Signal
from app.engine.policy import decision_from_score
from app.engine.profiles import PolicyProfile, default_profile
from app.engine.scoring import confidence_from_signals, effective_signals, score_from_signals


def _ip_signals(index: IndexStore, ip: str) -> tuple[list[Signal], list[Evidence]]:
    signals: list[Signal] = []
    evidence: list[Evidence] = []

    try:
        ipaddress.IPv4Address(ip)
    except Exception:
        return signals, evidence

    try:
        hit = index.ip_trie.get(ip)
    except Exception:
        hit = None

    if not hit:
        return signals, evidence

    if not isinstance(hit, list):
        hit = [hit]
    for i, meta in enumerate(hit):
        feed = str(meta.get("feed", "feed"))
        category = str(meta.get("category", "abuse"))
        weight = int(meta.get("weight", 1))
        sid = f"feed:{feed}:{i}"
        signals.append(
            Signal(
                id=sid,
                category=category,
                weight=weight,
                match=ip,
                source=feed,
                severity="high" if weight >= 30 else "medium",
            )
        )
        evidence.append(Evidence(source=feed, category=category, match=ip, weight=weight))
    return signals, evidence


def apply_profile(
    signals: list[Signal], evidence: list[Evidence], profile: PolicyProfile | None = None
) -> tuple[list[Signal], list[Evidence]]:
    """Apply category ignores and weight overrides to signals and evidence."""
    p = profile or default_profile()
    eff = effective_signals(signals, p)
    eff_evidence = [e for e in evidence if e.category not in p.ignore]
    for e in eff_evidence:
        if e.category in p.weights:
            e.weight = p.weights[e.category]
    return eff, eff_evidence


def check_ip(index: IndexStore, ip: str, profile: PolicyProfile | None = None) -> EngineResult:
    signals, evidence = _ip_signals(index, ip)
    signals, evidence = apply_profile(signals, evidence, profile)
    score = score_from_signals(signals)
    confidence = confidence_from_signals(signals)
    decision, action = decision_from_score(score, profile)
    enrichment: dict[str, Any] = {"ip": ip}
    return EngineResult(
        decision=decision,
        action=action,
        score=score,
        confidence=confidence,
        signals=signals,
        evidence=evidence,
        enrichment=enrichment,
    )
