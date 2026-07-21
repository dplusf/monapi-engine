from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.rate_limit import limiter


router = APIRouter()


@router.get("/health")
@limiter.exempt
async def health():
    return {"status": "ok"}


@router.get("/ready")
@limiter.exempt
async def ready(request: Request):
    store = request.app.state.store
    index = request.app.state.index
    if index:
        index.maybe_reload(request.app.state.settings.index_dir)
    ok = True
    try:
        await store.init_schema()
    except Exception:
        ok = False
    meta = getattr(index, "meta", {}) if index else {}
    return {
        "status": "ok" if ok and index else "degraded",
        "sqlite_ok": ok,
        "index_loaded": bool(index),
        "feeds_built_at": meta.get("built_at"),
    }
