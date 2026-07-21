from __future__ import annotations

import time
from fastapi import APIRouter, Depends, Request

from app.core.auth import require_api_key
from app.engine.checks import check_ip


router = APIRouter()


@router.get("/check/ip/{ip}")
async def check_ip_endpoint(ip: str, request: Request, _key: str = Depends(require_api_key)):
    t0 = time.time()
    index = request.app.state.index
    if index:
        index.maybe_reload(request.app.state.settings.index_dir)
    res = check_ip(index, ip)
    timing_ms = {"total": int((time.time() - t0) * 1000)}
    out = {
        "request_id": getattr(request.state, "request_id", ""),
        "ts": int(time.time()),
        "decision": res.decision,
        "action": res.action.__dict__ if res.action else None,
        "score": res.score,
        "confidence": res.confidence,
        "signals": [s.__dict__ for s in res.signals],
        "evidence": [e.__dict__ for e in res.evidence],
        "enrichment": res.enrichment,
        "timing_ms": timing_ms,
    }
    return out
