from __future__ import annotations

import time

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
    settings = request.app.state.settings
    if index:
        index.maybe_reload(settings.index_dir)

    sqlite_ok = True
    try:
        await store.init_schema()
    except Exception:
        sqlite_ok = False

    meta = getattr(index, "meta", {}) or {}
    built_at = meta.get("built_at")

    # Index must have actual data — not just an empty shell.
    entries_v4 = 0
    entries_v6 = 0
    domains = 0
    if index:
        try:
            entries_v4 = len(list(index.ip_trie))
        except Exception:
            pass
        try:
            entries_v6 = len(list(index.ip6_trie))
        except Exception:
            pass
        domains = len(index.domains)
    index_populated = (entries_v4 + entries_v6 + domains) > 0

    # Stale if older than 2 worker cycles plus download buffer.
    stale = False
    if built_at:
        try:
            import calendar
            parsed = time.strptime(built_at, "%Y-%m-%dT%H:%M:%SZ")
            age = time.time() - calendar.timegm(parsed)
            max_age = int(settings.worker_interval_seconds) * 2 + 300
            stale = age > max_age
        except (ValueError, OSError):
            pass

    ok = sqlite_ok and index_populated and not stale
    if not sqlite_ok:
        status = "unhealthy"
    elif not index_populated or stale:
        status = "degraded"
    else:
        status = "ok"

    return {
        "status": status,
        "sqlite_ok": sqlite_ok,
        "index_populated": index_populated,
        "index_entries_v4": entries_v4,
        "index_entries_v6": entries_v6,
        "index_domains": domains,
        "feeds_built_at": built_at,
        "stale": stale,
    }
