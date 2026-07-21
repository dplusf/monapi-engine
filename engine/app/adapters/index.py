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

from app.adapters.feeds import FeedDef


@dataclass
class IndexStore:
    ip_trie: pytricia.PyTricia
    domains: dict[str, set[str]]
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
        self.domains = loaded.domains
        self.meta = loaded.meta
        self.meta_path = loaded.meta_path


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

    trie = pytricia.PyTricia(32)
    domains: dict[str, set[str]] = {}

    for feed in feeds:
        if feed.type in ("ip", "cidr"):
            suffix = ".json" if feed.format == "json" else ".txt"
            f = raw_path / f"{feed.name}{suffix}"
            if not f.exists():
                continue
            entries = _parse_ip_cidr_file(f)
            for e in entries:
                try:
                    # Normalize IP -> /32 CIDR.
                    if "/" not in e:
                        ipaddress.IPv4Address(e)
                        cidr = f"{e}/32"
                    else:
                        ipaddress.IPv4Network(e, strict=False)
                        cidr = e
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
            suffix = ".json" if feed.format == "json" else ".txt"
            f = raw_path / f"{feed.name}{suffix}"
            if not f.exists():
                continue
            domains.setdefault(feed.category, set()).update(_parse_domain_file(f, feed.format))

    # Required by pytricia before pickling.
    trie.freeze()

    with open(tmp / "ip_trie.pkl", "wb") as f:
        pickle.dump(trie, f)
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
    dom_file = index_path / "domains.pkl"
    meta_file = index_path / "meta.json"

    trie = pytricia.PyTricia(32)
    domains: dict[str, set[str]] = {}
    meta: dict[str, Any] = {}

    if ip_file.exists():
        with open(ip_file, "rb") as f:
            trie = pickle.load(f)
    if dom_file.exists():
        with open(dom_file, "rb") as f:
            domains = pickle.load(f)
    if meta_file.exists():
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        try:
            meta["_meta_mtime"] = os.path.getmtime(meta_file)
        except Exception:
            pass

    return IndexStore(ip_trie=trie, domains=domains, meta=meta, meta_path=meta_file)
