from __future__ import annotations

import hashlib
from fastapi import Depends, HTTPException, Request
from fastapi.security.api_key import APIKeyHeader

from app.core.config import Settings, get_settings
from app.storage.sqlite import SqliteStore


def _hash_key(raw_key: str, pepper: str) -> str:
    return hashlib.sha256((raw_key + pepper).encode("utf-8")).hexdigest()


def get_store(request: Request) -> SqliteStore:
    return request.app.state.store


async def require_api_key(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: SqliteStore = Depends(get_store),
) -> str:
    header = APIKeyHeader(name=settings.api_key_header, auto_error=False)
    raw_key = await header(request)
    if not raw_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    key_hash = _hash_key(raw_key, settings.api_key_pepper)
    ok = await store.api_key_is_valid(key_hash)
    if not ok:
        raise HTTPException(status_code=403, detail="Invalid API key")

    request.state.api_key_hash = key_hash
    return key_hash


async def bootstrap_api_keys(settings: Settings, store: SqliteStore) -> None:
    keys = [k.strip() for k in (settings.bootstrap_api_keys or "").split(",") if k.strip()]
    for raw in keys:
        await store.upsert_api_key(_hash_key(raw, settings.api_key_pepper), label="bootstrap")
