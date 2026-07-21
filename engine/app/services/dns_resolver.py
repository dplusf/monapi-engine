from __future__ import annotations

import ipaddress
from typing import List

import dns.resolver


def resolve_a(domain: str) -> list[str]:
    out: list[str] = []
    for rr in dns.resolver.resolve(domain, "A", raise_on_no_answer=False):
        s = str(rr).strip()
        try:
            ipaddress.IPv4Address(s)
        except Exception:
            continue
        out.append(s)
    return out


def resolve_mx_hosts(domain: str) -> list[str]:
    out: list[str] = []
    ans = dns.resolver.resolve(domain, "MX", raise_on_no_answer=False)
    for rr in ans:
        host = str(rr.exchange).rstrip(".")
        if host:
            out.append(host)
    return out
