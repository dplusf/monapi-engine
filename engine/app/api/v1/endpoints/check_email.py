from __future__ import annotations

import time
from fastapi import APIRouter, Depends, Request

from email_validator import EmailNotValidError, validate_email

from app.adapters.base import NullVerifier
from app.api.deps import get_profile
from app.core.auth import require_api_key
from app.core.rate_limit import EMAIL_LIMIT, limiter
from app.engine.models import Evidence, Signal
from app.engine.policy import decision_from_score
from app.engine.profiles import PolicyProfile
from app.engine.scoring import confidence_from_signals, score_from_signals
from app.engine.checks import _ip_signals, apply_profile
from app.services.dns_resolver import resolve_mx_hosts, resolve_a
from app.services.email_checks import is_role_account, typo_suggestion


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
    store = request.app.state.store
    index = request.app.state.index
    verifier = request.app.state.email_verifier
    if index:
        index.maybe_reload(request.app.state.settings.index_dir)

    signals: list[Signal] = []
    evidence: list[Evidence] = []
    enrichment = {
        "email": email,
        "domain": None,
        "mx_hosts": [],
        "mx_ips": [],
        "deliverability": "unknown",
        "is_catchall": False,
        "is_role_account": False,
        "did_you_mean": None,
        "verifier": {"verifier": "none"},
    }

    try:
        v = validate_email(email, check_deliverability=False)
        dom = v.domain.lower()
        local = v.local_part
    except EmailNotValidError:
        dom = None
        local = None

    if not dom:
        enrichment["deliverability"] = "undeliverable"
        signals.append(
            Signal(
                id="email:invalid_syntax",
                category="syntax",
                weight=50,
                match=email,
                source="validator",
                severity="high",
            )
        )
        evidence.append(Evidence(source="validator", category="syntax", match=email, weight=50))
    else:
        enrichment["domain"] = dom

        # Domain list signals (all categories: disposable, phishing, malware, ...)
        hits = (index.domains or {}).get(dom, {}) if index else {}
        for cat, info in hits.items():
            w = int(info.get("weight", 10))
            src = ",".join(info.get("feeds", ["domain_list"]))
            signals.append(
                Signal(
                    id=f"email_domain:{cat}",
                    category=cat,
                    weight=w,
                    match=dom,
                    source=src,
                    severity="high" if w >= 30 else "low",
                )
            )
            evidence.append(Evidence(source=src, category=cat, match=dom, weight=w))

        # Role account (info@, support@, ...)
        if local and is_role_account(local):
            enrichment["is_role_account"] = True
            signals.append(
                Signal(
                    id="email:role_account",
                    category="role_account",
                    weight=5,
                    match=local,
                    source="static_list",
                    severity="low",
                )
            )
            evidence.append(Evidence(source="static_list", category="role_account", match=local, weight=5))

        # Typo detection (gamil.com -> gmail.com), only if the domain isn't
        # already flagged by any list — no point piling on.
        if not hits:
            suggestion = typo_suggestion(dom)
            if suggestion:
                enrichment["did_you_mean"] = suggestion
                signals.append(
                    Signal(
                        id="email:domain_typo",
                        category="typo",
                        weight=10,
                        match=f"{dom}~{suggestion}",
                        source="static_list",
                        severity="low",
                    )
                )
                evidence.append(
                    Evidence(
                        source="static_list",
                        category="typo",
                        match=dom,
                        weight=10,
                        note=f"did_you_mean:{suggestion}",
                    )
                )

        # MX + implicit-MX (A record) checks
        try:
            mx_hosts = resolve_mx_hosts(dom)
        except Exception:
            mx_hosts = []
        enrichment["mx_hosts"] = mx_hosts

        a_records: list[str] = []
        if not mx_hosts:
            try:
                a_records = resolve_a(dom)
            except Exception:
                a_records = []

        if not mx_hosts and not a_records:
            # No MX and no A fallback: mail to this domain cannot be delivered.
            enrichment["deliverability"] = "undeliverable"
            signals.append(
                Signal(
                    id="email:no_mx",
                    category="mx",
                    weight=30,
                    match=dom,
                    source="dns",
                    severity="high",
                )
            )
            evidence.append(Evidence(source="dns", category="mx", match=dom, weight=30))
        elif not mx_hosts:
            # RFC 5321 implicit MX via A record — deliverable in theory.
            enrichment["deliverability"] = "unknown"
            signals.append(
                Signal(
                    id="email:implicit_mx",
                    category="mx",
                    weight=5,
                    match=dom,
                    source="dns",
                    severity="low",
                )
            )
            evidence.append(Evidence(source="dns", category="mx", match=dom, weight=5))

        # MX host IPs -> feed reputation
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

        # Catch-all cache (populated out-of-band)
        if await store.catchall_get(dom):
            enrichment["is_catchall"] = True
            enrichment["deliverability"] = "catchall"

        # External verifier (opt-in, e.g. Reoon). Overrides DNS heuristics
        # when it returns a definitive answer.
        if not isinstance(verifier, NullVerifier):
            result = await verifier.verify(email)
            enrichment["verifier"] = result.detail
            if result.status != "unknown":
                enrichment["deliverability"] = result.status
                if result.status == "catchall":
                    enrichment["is_catchall"] = True

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
