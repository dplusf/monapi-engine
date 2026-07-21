"""Reoon email verifier adapter (https://reoon.com). Off by default;
enabled via EMAIL_VERIFIER=reoon + REOON_API_KEY. Free tier: 600 credits/month.
"""
from __future__ import annotations

import logging

import httpx

from app.adapters.base import VerificationResult

log = logging.getLogger("monapi")

_API_URL = "https://emailverifier.reoon.com/api/v1/verify"

_STATUS_MAP = {
    "valid": "deliverable",
    "safe": "deliverable",
    "invalid": "undeliverable",
    "disabled": "undeliverable",
    "catch_all": "catchall",
    "role": "deliverable",
    "disposable": "undeliverable",
    "spamtrap": "undeliverable",
    "unknown": "unknown",
}


class ReoonVerifier:
    def __init__(self, api_key: str, mode: str = "quick", timeout: float = 10.0):
        self.api_key = api_key
        self.mode = mode
        self.timeout = timeout

    async def verify(self, email: str) -> VerificationResult:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    _API_URL,
                    params={"email": email, "key": self.api_key, "mode": self.mode},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            log.warning("reoon_verify_failed", extra={"error": str(exc)})
            return VerificationResult(status="unknown", detail={"verifier": "reoon", "error": "request_failed"})

        raw = str(data.get("status", "unknown")).lower()
        status = _STATUS_MAP.get(raw, "unknown")
        detail = {"verifier": "reoon", "raw_status": raw}
        if data.get("overall_score") is not None:
            try:
                detail["score"] = int(data["overall_score"])
            except (TypeError, ValueError):
                pass
        return VerificationResult(status=status, detail=detail)
