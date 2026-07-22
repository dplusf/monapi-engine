"""Prometheus custom gauges — defined here to avoid circular imports
between main.py (instrumentation) and health.py (/ready)."""
from __future__ import annotations

from prometheus_client import Gauge

index_gauge_v4 = Gauge("monapi_index_entries_v4", "IPv4 trie entries")
index_gauge_v6 = Gauge("monapi_index_entries_v6", "IPv6 trie entries")
index_gauge_domains = Gauge("monapi_index_domains", "Domain entries")
index_gauge_stale = Gauge("monapi_index_stale", "Index is stale (1=stale, 0=fresh)")
