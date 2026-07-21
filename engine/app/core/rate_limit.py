from __future__ import annotations

import os

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


DEFAULT_LIMIT = os.getenv("RATE_LIMIT_DEFAULT", "60/minute")
EMAIL_LIMIT = os.getenv("RATE_LIMIT_EMAIL", "10/minute")


def key_func(request: Request) -> str:
    key_hash = getattr(request.state, "api_key_hash", None)
    if key_hash:
        return key_hash
    return get_remote_address(request)


limiter = Limiter(key_func=key_func, default_limits=[DEFAULT_LIMIT])
