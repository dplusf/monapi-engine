from __future__ import annotations

import time
from fastapi import APIRouter, Depends, Request

from app.api.deps import get_profile
from app.core.auth import require_api_key
from app.engine.models import Evidence, Signal
from app.engine.policy import decision_from_score
from app.engine.profiles import PolicyProfile
from app.engine.scoring import confidence_from_signals, score_from_signals
from app.engine.checks import _ip_signals, apply_profile
from app.services.dns_resolver import resolve_a, resolve_mx_hosts


router = APIRouter()


@router.get("/check/domain/{domain}")
async def check_domain(
    domain: str,
    request: Request,
    _key: str = Depends(require_api_key),
    profile: PolicyProfile = Depends(get_profile),
):
    t0 = time.time()
    index = request.app.state.index
    if index:
        index.maybe_reload(request.app.state.settings.index_dir)

    signals: list[Signal] = []
    evidence: list[Evidence] = []
    enrichment = {"domain": domain, "resolved_ips": [], "mx_hosts": []}

    dom_lc = domain.strip().lower()
    hits = (index.domains or {}).get(dom_lc, {}) if index else {}
    for cat, info in hits.items():
        w = int(info.get("weight", 10))
        src = ",".join(info.get("feeds", ["domain_list"]))
        signals.append(
            Signal(
                id=f"domain:{cat}",
                category=cat,
                weight=w,
                match=dom_lc,
                source=src,
                severity="high" if w >= 30 else "low",
            )
        )
        evidence.append(Evidence(source=src, category=cat, match=dom_lc, weight=w))

    try:
        ips = resolve_a(dom_lc)
    except Exception:
        ips = []
    enrichment["resolved_ips"] = ips

    for ip in ips:
        s, e = _ip_signals(index, ip)
        signals.extend(s)
        evidence.extend(e)

    # Geo/ASN enrichment per resolved IP (only entries with data).
    enricher = request.app.state.enricher
    geo: dict[str, dict] = {}
    for ip in ips[:5]:
        try:
            info = await enricher.enrich_ip(ip)
        except Exception:
            info = {}
        if info:
            geo[ip] = info
    if geo:
        enrichment["geo"] = geo

    try:
        mx_hosts = resolve_mx_hosts(dom_lc)
    except Exception:
        mx_hosts = []
    enrichment["mx_hosts"] = mx_hosts

    signals, evidence = apply_profile(signals, evidence, profile)
    score = score_from_signals(signals)
    confidence = confidence_from_signals(signals)
    decision, action = decision_from_score(score, profile)

    timing_ms = {"total": int((time.time() - t0) * 1000)}
    return {
        "request_id": getattr(request.state, "request_id", ""),
        "ts": int(time.time()),
        "profile": profile.name,
        "decision": decision,
        "action": action.__dict__ if action else None,
        "score": score,
        "confidence": confidence,
        "signals": [s.__dict__ for s in signals],
        "evidence": [e.__dict__ for e in evidence],
        "enrichment": enrichment,
        "timing_ms": timing_ms,
    }
