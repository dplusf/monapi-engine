from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.adapters.feeds import download_feed, load_feed_defs
from app.adapters.index import build_index
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.services.enrichment import ensure_geoip_fresh
from app.storage.sqlite import SqliteStore


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    log = logging.getLogger("monapi.worker")

    store = SqliteStore(settings.sqlite_path)
    await store.init_schema()

    feeds = load_feed_defs(settings.feeds_config)
    raw_dir = Path("/data/feeds/raw")
    index_dir = settings.index_dir

    while True:
        try:
            feed_meta = {}
            for feed in feeds:
                try:
                    await download_feed(store, feed, raw_dir)
                except Exception:
                    log.exception("feed_download_failed", extra={"feed": feed.name, "url": feed.url})
                    continue

                m = await store.get_feed_meta(feed.name) or {}
                feed_meta[feed.name] = m
            build_index(index_dir=index_dir, raw_dir=str(raw_dir), feeds=feeds, feed_meta=feed_meta)
            log.info("index_built", extra={"index_dir": index_dir, "feed_count": len(feeds)})

            # Keep the GeoIP database fresh (daily). Only when the geoip
            # enricher is configured — no point downloading 10 MB otherwise.
            if settings.enricher == "geoip":
                await ensure_geoip_fresh(
                    settings.geoip_mmdb_path,
                    settings.geoip_url,
                    max_age_seconds=settings.geoip_max_age_seconds,
                )
        except Exception as e:
            log.exception("worker_tick_failed")

        await asyncio.sleep(int(settings.worker_interval_seconds))
