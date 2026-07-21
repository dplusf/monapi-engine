from __future__ import annotations

import ipaddress
import time
from typing import Any

from app.adapters.index import IndexStore
from app.engine.models import Evidence, EngineResult, Signal
from app.engine.policy import decision_from_score
from app.engine.scoring import confidence_from_signals, score_from_signals


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


def check_ip(index: IndexStore, ip: str) -> EngineResult:
    signals, evidence = _ip_signals(index, ip)
    score = score_from_signals(signals)
    confidence = confidence_from_signals(signals)
    decision, action = decision_from_score(score)
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
