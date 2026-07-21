from __future__ import annotations

import time
from fastapi import APIRouter, Depends, Request

from email_validator import EmailNotValidError, validate_email

from app.api.deps import get_profile
from app.core.auth import require_api_key
from app.core.rate_limit import EMAIL_LIMIT, limiter
from app.engine.models import Evidence, Signal
from app.engine.policy import decision_from_score
from app.engine.profiles import PolicyProfile
from app.engine.scoring import confidence_from_signals, score_from_signals
from app.engine.checks import _ip_signals, apply_profile
from app.services.dns_resolver import resolve_mx_hosts, resolve_a
from app.services.email_smtp import random_user, smtp_rcpt_probe


router = APIRouter()


@router.get("/check/email/{email}")
@limiter.limit(EMAIL_LIMIT)
async def check_email(
    email: str,
    request: Request,
    _key: str = Depends(require_api_key),
    profile: PolicyProfile = Depends(get_profile),
):
    t0 = time.time()
    settings = request.app.state.settings
    store = request.app.state.store
    index = request.app.state.index
    if index:
        index.maybe_reload(settings.index_dir)

    signals: list[Signal] = []
    evidence: list[Evidence] = []
    enrichment = {
        "email": email,
        "domain": None,
        "mx_hosts": [],
        "mx_ips": [],
        "deliverability": "unknown",
        "is_catchall": False,
        "smtp": {"attempted": False, "code": None, "message": None},
    }

    try:
        v = validate_email(email, check_deliverability=False)
        dom = v.domain.lower()
        local = v.local_part
    except EmailNotValidError:
        dom = None
        local = None

    if not dom:
        signals.append(
            Signal(
                id="email:invalid_syntax",
                category="syntax",
                weight=5,
                match=email,
                source="validator",
                severity="low",
            )
        )
        evidence.append(Evidence(source="validator", category="syntax", match=email, weight=5))
    else:
        enrichment["domain"] = dom
        # Domain list signals
        for cat in ("disposable", "free_mail"):
            domset = (index.domains or {}).get(cat, set()) if index else set()
            if dom in domset:
                w = 40 if cat == "disposable" else 10
                signals.append(
                    Signal(
                        id=f"email_domain:{cat}",
                        category=cat,
                        weight=w,
                        match=dom,
                        source="domain_list",
                        severity="high" if w >= 30 else "low",
                    )
                )
                evidence.append(Evidence(source="domain_list", category=cat, match=dom, weight=w))

        # MX
        try:
            mx_hosts = resolve_mx_hosts(dom)
        except Exception:
            mx_hosts = []
        enrichment["mx_hosts"] = mx_hosts

        mx_ips: list[str] = []
        for host in mx_hosts[:5]:
            try:
                mx_ips.extend(resolve_a(host))
            except Exception:
                continue
        enrichment["mx_ips"] = mx_ips

        for ip in mx_ips:
            s, e = _ip_signals(index, ip)
            signals.extend(s)
            evidence.extend(e)

        # Catch-all caching
        is_catchall_cached = await store.catchall_get(dom)
        if is_catchall_cached:
            enrichment["is_catchall"] = True
            enrichment["deliverability"] = "deliverable"
        else:
            # SMTP probes (only if we have MX)
            if mx_hosts and settings.smtp_enabled:
                mx = mx_hosts[0]
                fake_rcpt = f"{random_user(10)}@{dom}"
                probe = smtp_rcpt_probe(settings, mx, fake_rcpt)
                enrichment["smtp"] = probe.__dict__
                if probe.code == 250:
                    enrichment["is_catchall"] = True
                    enrichment["deliverability"] = "deliverable"
                    await store.catchall_touch(dom)
                else:
                    # Try real recipient
                    rcpt = f"{local}@{dom}" if local else email
                    probe2 = smtp_rcpt_probe(settings, mx, rcpt)
                    enrichment["smtp"] = probe2.__dict__
                    if probe2.code == 250:
                        enrichment["deliverability"] = "deliverable"
                    elif probe2.code is None:
                        enrichment["deliverability"] = "unknown"
                    else:
                        enrichment["deliverability"] = "undeliverable"
            else:
                enrichment["deliverability"] = "unknown"

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
