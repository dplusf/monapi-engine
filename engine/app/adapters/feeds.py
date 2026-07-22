from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.storage.sqlite import SqliteStore


@dataclass(frozen=True)
class FeedDef:
    name: str
    url: str
    type: str  # ip|cidr|domain
    category: str
    weight: int
    format: str  # text|json|hostfile


def feed_suffix(fmt: str) -> str:
    return {"json": ".json", "hostfile": ".hosts"}.get(fmt, ".txt")


def load_feed_defs(path: str) -> list[FeedDef]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    feeds = data.get("feeds", [])
    out: list[FeedDef] = []
    for item in feeds:
        out.append(
            FeedDef(
                name=str(item["name"]),
                url=str(item["url"]),
                type=str(item["type"]),
                category=str(item["category"]),
                weight=int(item["weight"]),
                format=str(item.get("format", "text")),
            )
        )
    return out


async def download_feed(
    store: SqliteStore,
    feed: FeedDef,
    raw_dir: Path,
    timeout_seconds: int = 30,
) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / f"{feed.name}{feed_suffix(feed.format)}"

    meta = await store.get_feed_meta(feed.name)
    headers: dict[str, str] = {}
    if meta and meta.get("etag"):
        headers["If-None-Match"] = meta["etag"]
    if meta and meta.get("last_modified"):
        headers["If-Modified-Since"] = meta["last_modified"]

    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout_seconds) as client:
        resp = await client.get(feed.url, headers=headers)
        if resp.status_code == 304 and dest.exists():
            return dest
        resp.raise_for_status()
        content = resp.content
        dest.write_bytes(content)

        fetched_at = dt.datetime.utcnow().isoformat() + "Z"
        await store.upsert_feed_meta(
            name=feed.name,
            url=feed.url,
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
            fetched_at=fetched_at,
            sha256_hex=SqliteStore.sha256_bytes(content),
        )
        return dest
