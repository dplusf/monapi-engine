"""Adapter interfaces for pluggable external data sources.

Concrete implementations are wired in Phase 1b (GeoIP enricher, Reoon
email verifier). The null implementations here are the safe defaults:
they add no signals and never fail requests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class FeedSource(Protocol):
    """A reputation data feed (IP/CIDR/domain list) synced by the worker."""

    name: str
    url: str
    type: str  # ip | cidr | domain
    category: str
    weight: int
    format: str  # text | json


@dataclass(frozen=True)
class VerificationResult:
    status: str  # deliverable | undeliverable | catchall | unknown
    detail: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class EmailVerifier(Protocol):
    """External email verification service (e.g. Reoon). No SMTP probing."""

    async def verify(self, email: str) -> VerificationResult: ...


class NullVerifier:
    """Default verifier: no external calls, always unknown."""

    async def verify(self, email: str) -> VerificationResult:
        return VerificationResult(status="unknown", detail={"verifier": "none"})


@runtime_checkable
class Enricher(Protocol):
    """Adds context (Geo/ASN/rDNS) to IPs and domains. Must never raise."""

    async def enrich_ip(self, ip: str) -> dict[str, Any]: ...

    async def enrich_domain(self, domain: str) -> dict[str, Any]: ...


class NullEnricher:
    """Default enricher: returns empty context."""

    async def enrich_ip(self, ip: str) -> dict[str, Any]:
        return {}

    async def enrich_domain(self, domain: str) -> dict[str, Any]:
        return {}
