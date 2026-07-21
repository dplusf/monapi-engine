"""Geo/ASN/rDNS enrichment backed by a local MMDB file (ip66.dev by default).

The database is downloaded daily by the worker into a shared volume; this
module only reads it. ip66 provides ASN + organization, country + ISO and
continent (no city level). All lookups are defensive: a missing database or
a failed rDNS lookup degrades enrichment, never the decision.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import dns.asyncresolver
import dns.reversename
import httpx
import maxminddb

log = logging.getLogger("monapi")


class GeoIPEnricher:
    """Enricher adapter (see app.adapters.base.Enricher) using a local MMDB."""

    def __init__(self, mmdb_path: str, rdns_enabled: bool = True, rdns_timeout: float = 2.0):
        self.mmdb_path = mmdb_path
        self.rdns_enabled = rdns_enabled
        self.rdns_timeout = rdns_timeout
        self._reader: maxminddb.Reader | None = None
        self._mtime: float | None = None

    def _get_reader(self) -> maxminddb.Reader | None:
        try:
            mtime = os.path.getmtime(self.mmdb_path)
        except OSError:
            return None
        if self._reader is None or self._mtime != mtime:
            try:
                self._reader = maxminddb.open_database(self.mmdb_path)
                self._mtime = mtime
                log.info("geoip_loaded", extra={"path": self.mmdb_path})
            except Exception as exc:
                log.warning("geoip_load_failed", extra={"path": self.mmdb_path, "error": str(exc)})
                self._reader = None
                self._mtime = None
        return self._reader

    def _geo(self, ip: str) -> dict[str, Any]:
        reader = self._get_reader()
        if reader is None:
            return {}
        try:
            rec = reader.get(ip) or {}
        except Exception:
            return {}

        out: dict[str, Any] = {}

        # ip66 MMDB schema (defensive: tolerate MaxMind-style nesting too).
        asn = rec.get("autonomous_system_number") or rec.get("asn")
        org = rec.get("autonomous_system_organization") or rec.get("organization")
        if asn:
            out["asn"] = int(asn)
        if org:
            out["asn_organization"] = str(org)

        country = rec.get("country") or {}
        iso = rec.get("country_iso_code") or (country.get("iso_code") if isinstance(country, dict) else None)
        cname = rec.get("country_name") or (
            (country.get("names") or {}).get("en") if isinstance(country, dict) else None
        )
        if iso:
            out["country_iso"] = str(iso)
        if cname:
            out["country"] = str(cname)

        continent = rec.get("continent") or {}
        cont = rec.get("continent_code") or (
            continent.get("code") if isinstance(continent, dict) else None
        )
        if cont:
            out["continent"] = str(cont)
        return out

    async def _rdns(self, ip: str) -> str | None:
        if not self.rdns_enabled:
            return None
        try:
            name = dns.reversename.from_address(ip)
            resolver = dns.asyncresolver.Resolver()
            resolver.lifetime = self.rdns_timeout
            answer = await resolver.resolve(name, "PTR")
            if answer:
                return str(answer[0]).rstrip(".")
        except Exception:
            return None
        return None

    async def enrich_ip(self, ip: str) -> dict[str, Any]:
        out = self._geo(ip)
        try:
            host = await self._rdns(ip)
        except Exception:
            host = None
        if host:
            out["hostname"] = host
        return out

    async def enrich_domain(self, domain: str) -> dict[str, Any]:
        # Domain-level enrichment is IP-based; endpoints enrich resolved IPs.
        return {}


async def ensure_geoip_fresh(mmdb_path: str, url: str, max_age_seconds: int = 86400) -> bool:
    """Download the MMDB if missing or older than max_age_seconds. Atomic via tmp+rename."""
    try:
        if os.path.exists(mmdb_path):
            age = time.time() - os.path.getmtime(mmdb_path)
            if age < max_age_seconds:
                return True

        dest = Path(mmdb_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".mmdb.tmp")
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            tmp.write_bytes(resp.content)
        tmp.rename(dest)
        log.info("geoip_updated", extra={"path": mmdb_path, "bytes": len(resp.content)})
        return True
    except Exception as exc:
        log.warning("geoip_update_failed", extra={"path": mmdb_path, "error": str(exc)})
        return False
