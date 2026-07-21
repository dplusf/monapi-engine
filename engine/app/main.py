from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.extension import _rate_limit_exceeded_handler

from app.adapters.index import load_index
from app.core.auth import bootstrap_api_keys
from app.core.config import get_settings
from app.core.logging import RequestIdMiddleware, setup_logging
from app.core.rate_limit import limiter
from app.storage.sqlite import SqliteStore
from app.api.v1.router import router as v1_router


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

    app.state.settings = settings
    app.state.store = store
    app.state.index = index

    log.info("api_ready", extra={"index_dir": settings.index_dir, "sqlite_path": settings.sqlite_path})
    yield


app = FastAPI(title="monapi-engine", version="0.1", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestIdMiddleware)

app.include_router(v1_router)
