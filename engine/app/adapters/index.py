from __future__ import annotations

import ipaddress
import json
import os
import pickle
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytricia

from app.adapters.feeds import FeedDef, feed_suffix


@dataclass
class IndexStore:
    ip_trie: pytricia.PyTricia  # IPv4, 32 bits
    ip6_trie: pytricia.PyTricia  # IPv6, 128 bits
    # domain -> category -> {"weight": int, "feeds": [names]}.
    # One hit per category regardless of how many feeds list the domain;
    # weight is the max feed weight of that category.
    domains: dict[str, dict[str, dict[str, Any]]]
    meta: dict[str, Any]
    meta_path: Path

    def maybe_reload(self, index_dir: str) -> None:
        try:
            mtime = os.path.getmtime(Path(index_dir) / "meta.json")
        except Exception:
            return
        if self.meta.get("_meta_mtime") == mtime:
            return
        loaded = load_index(index_dir)
        self.ip_trie = loaded.ip_trie
        self.ip6_trie = loaded.ip6_trie
        self.domains = loaded.domains
        self.meta = loaded.meta
        self.meta_path = loaded.meta_path

    def trie_for(self, ip: str) -> pytricia.PyTricia | None:
        """Return the trie matching the IP version, or None if unparseable."""
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return None
        return self.ip_trie if addr.version == 4 else self.ip6_trie


def _load_text_lines(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(s)
    return lines


def _parse_domain_file(path: Path, fmt: str) -> set[str]:
    if fmt == "json":
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        if isinstance(data, list):
            return {str(x).strip().lower() for x in data if str(x).strip()}
        return set()
    if fmt == "hostfile":
        # "127.0.0.1 domain.tld" style (e.g. URLhaus hostfile export)
        out: set[str] = set()
        for line in _load_text_lines(path):
            parts = line.split()
            if len(parts) >= 2:
                dom = parts[-1].strip().lower()
                if dom and dom not in ("localhost", "localhost.localdomain"):
                    out.add(dom)
        return out
    return {line.strip().lower() for line in _load_text_lines(path)}


def _parse_ip_cidr_file(path: Path) -> list[str]:
    out: list[str] = []
    for line in _load_text_lines(path):
        # firehol netsets sometimes contain "0.0.0.0/8" style entries.
        token = line.split()[0]
        out.append(token)
    return out


def build_index(
    index_dir: str,
    raw_dir: str,
    feeds: list[FeedDef],
    feed_meta: dict[str, dict[str, Any]],
) -> None:
    index_path = Path(index_dir)
    raw_path = Path(raw_dir)
    tmp = index_path.parent / (index_path.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    trie4 = pytricia.PyTricia(32)
    trie6 = pytricia.PyTricia(128)
    domains: dict[str, dict[str, dict[str, Any]]] = {}

    for feed in feeds:
        if feed.type in ("ip", "cidr"):
            f = raw_path / f"{feed.name}{feed_suffix(feed.format)}"
            if not f.exists():
                continue
            entries = _parse_ip_cidr_file(f)
            for e in entries:
                try:
                    # Normalize: bare IP -> /32 or /128 CIDR; pick trie by version.
                    if "/" not in e:
                        addr = ipaddress.ip_address(e)
                        net = ipaddress.ip_network(f"{e}/{addr.max_prefixlen}")
                    else:
                        net = ipaddress.ip_network(e, strict=False)
                    cidr = str(net)
                    trie = trie4 if net.version == 4 else trie6
                except Exception:
                    continue

                meta_item = {
                    "feed": feed.name,
                    "category": feed.category,
                    "weight": int(feed.weight),
                }
                try:
                    cur = trie[cidr]
                    if isinstance(cur, list):
                        cur.append(meta_item)
                        trie[cidr] = cur
                    else:
                        trie[cidr] = [cur, meta_item]
                except KeyError:
                    trie[cidr] = [meta_item]

        elif feed.type == "domain":
            f = raw_path / f"{feed.name}{feed_suffix(feed.format)}"
            if not f.exists():
                continue
            for dom in _parse_domain_file(f, feed.format):
                cats = domains.setdefault(dom, {})
                entry = cats.get(feed.category)
                if entry is None:
                    cats[feed.category] = {"weight": int(feed.weight), "feeds": [feed.name]}
                else:
                    entry["weight"] = max(entry["weight"], int(feed.weight))
                    if feed.name not in entry["feeds"]:
                        entry["feeds"].append(feed.name)

    # Required by pytricia before pickling.
    trie4.freeze()
    trie6.freeze()

    with open(tmp / "ip_trie.pkl", "wb") as f:
        pickle.dump(trie4, f)
    with open(tmp / "ip6_trie.pkl", "wb") as f:
        pickle.dump(trie6, f)
    with open(tmp / "domains.pkl", "wb") as f:
        pickle.dump(domains, f)

    meta = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "feeds": {
            k: {"url": v.get("url"), "sha256": v.get("sha256"), "fetched_at": v.get("fetched_at")}
            for k, v in feed_meta.items()
        },
    }
    (tmp / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")

    # Atomic swap
    if index_path.exists():
        shutil.rmtree(index_path)
    tmp.rename(index_path)


def load_index(index_dir: str) -> IndexStore:
    index_path = Path(index_dir)
    ip_file = index_path / "ip_trie.pkl"
    ip6_file = index_path / "ip6_trie.pkl"
    dom_file = index_path / "domains.pkl"
    meta_file = index_path / "meta.json"

    trie4 = pytricia.PyTricia(32)
    trie6 = pytricia.PyTricia(128)
    domains: dict[str, dict[str, dict[str, Any]]] = {}
    meta: dict[str, Any] = {}

    if ip_file.exists():
        with open(ip_file, "rb") as f:
            trie4 = pickle.load(f)
    if ip6_file.exists():
        with open(ip6_file, "rb") as f:
            trie6 = pickle.load(f)
    if dom_file.exists():
        with open(dom_file, "rb") as f:
            domains = pickle.load(f)
    if meta_file.exists():
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        try:
            meta["_meta_mtime"] = os.path.getmtime(meta_file)
        except Exception:
            pass

    return IndexStore(ip_trie=trie4, ip6_trie=trie6, domains=domains, meta=meta, meta_path=meta_file)
