from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.extension import _rate_limit_exceeded_handler

from app.adapters.base import NullEnricher, NullVerifier
from app.adapters.index import load_index
from app.adapters.reoon import ReoonVerifier
from app.core.auth import bootstrap_api_keys
from app.core.config import get_settings
from app.core.logging import RequestIdMiddleware, setup_logging
from app.core.rate_limit import limiter
from app.engine.profiles import load_profiles
from app.services.enrichment import GeoIPEnricher
from app.storage.sqlite import SqliteStore
from app.api.v1.router import router as v1_router

from prometheus_fastapi_instrumentator import Instrumentator


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    log = logging.getLogger("monapi")

    store = SqliteStore(settings.sqlite_path)
    await store.init_schema()
    await bootstrap_api_keys(settings, store)

    Path(settings.index_dir).mkdir(parents=True, exist_ok=True)
    index = load_index(settings.index_dir)
    profiles = load_profiles(settings.policies_config)

    # Adapter selection.
    if settings.enricher == "geoip":
        enricher = GeoIPEnricher(
            settings.geoip_mmdb_path,
            rdns_enabled=settings.rdns_enabled,
            rdns_timeout=settings.rdns_timeout_seconds,
        )
    else:
        enricher = NullEnricher()

    if settings.email_verifier == "reoon" and settings.reoon_api_key:
        email_verifier = ReoonVerifier(settings.reoon_api_key, mode=settings.reoon_mode)
    else:
        email_verifier = NullVerifier()

    app.state.settings = settings
    app.state.store = store
    app.state.index = index
    app.state.profiles = profiles
    app.state.enricher = enricher
    app.state.email_verifier = email_verifier

    log.info(
        "api_ready",
        extra={
            "index_dir": settings.index_dir,
            "sqlite_path": settings.sqlite_path,
            "profiles": sorted(profiles),
            "enricher": settings.enricher,
            "email_verifier": settings.email_verifier,
        },
    )
    yield


app = FastAPI(title="monapi-engine", version="0.1", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestIdMiddleware)

app.include_router(v1_router)

# Prometheus metrics on /metrics — HTTP request counts, latencies, status codes.
# Also exposes 4 custom monapi_index_* gauges updated by /ready.
Instrumentator().instrument(app).expose(app, include_in_schema=False)
