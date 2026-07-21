from __future__ import annotations

import datetime as dt
import hashlib
from typing import Optional

import aiosqlite


class SqliteStore:
    def __init__(self, path: str):
        self.path = path

    def connect(self) -> aiosqlite.Connection:
        # aiosqlite connections are awaitable and async-context-managers.
        # Do NOT await here; await happens in __aenter__.
        return aiosqlite.connect(self.path)

    async def init_schema(self) -> None:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                  key_hash TEXT PRIMARY KEY,
                  label TEXT,
                  created_at TEXT NOT NULL,
                  disabled INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS feed_meta (
                  name TEXT PRIMARY KEY,
                  url TEXT NOT NULL,
                  etag TEXT,
                  last_modified TEXT,
                  fetched_at TEXT,
                  sha256 TEXT
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS catchall_domains (
                  domain TEXT PRIMARY KEY,
                  created_at TEXT NOT NULL,
                  last_seen_at TEXT NOT NULL
                )
                """
            )
            await db.commit()

    async def api_key_is_valid(self, key_hash: str) -> bool:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT key_hash FROM api_keys WHERE key_hash=? AND disabled=0", (key_hash,)
            )
            row = await cur.fetchone()
            return row is not None

    async def upsert_api_key(self, key_hash: str, label: str = "") -> None:
        now = dt.datetime.utcnow().isoformat() + "Z"
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            await db.execute(
                """
                INSERT INTO api_keys(key_hash, label, created_at, disabled)
                VALUES(?,?,?,0)
                ON CONFLICT(key_hash) DO UPDATE SET label=excluded.label
                """,
                (key_hash, label, now),
            )
            await db.commit()

    async def get_feed_meta(self, name: str) -> Optional[dict]:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM feed_meta WHERE name=?", (name,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def upsert_feed_meta(
        self,
        name: str,
        url: str,
        etag: str | None,
        last_modified: str | None,
        fetched_at: str | None,
        sha256_hex: str | None,
    ) -> None:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            await db.execute(
                """
                INSERT INTO feed_meta(name, url, etag, last_modified, fetched_at, sha256)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET
                  url=excluded.url,
                  etag=excluded.etag,
                  last_modified=excluded.last_modified,
                  fetched_at=excluded.fetched_at,
                  sha256=excluded.sha256
                """,
                (name, url, etag, last_modified, fetched_at, sha256_hex),
            )
            await db.commit()

    async def catchall_get(self, domain: str) -> bool:
        domain = domain.lower().strip()
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT domain FROM catchall_domains WHERE domain=?", (domain,))
            return (await cur.fetchone()) is not None

    async def catchall_touch(self, domain: str) -> None:
        domain = domain.lower().strip()
        now = dt.datetime.utcnow().isoformat() + "Z"
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            await db.execute(
                """
                INSERT INTO catchall_domains(domain, created_at, last_seen_at)
                VALUES(?,?,?)
                ON CONFLICT(domain) DO UPDATE SET last_seen_at=excluded.last_seen_at
                """,
                (domain, now, now),
            )
            await db.commit()

    @staticmethod
    def sha256_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()
