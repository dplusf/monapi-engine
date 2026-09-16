"""Loader for the signal catalogue (app/data/signals.yaml).

The catalogue is documentation, not logic: nothing here influences a
decision. It exists so that a caller who sees `email:no_mx` in a response
can look up what that means without reading the source — served by
GET /v1/signals, rendered into docs/signals.md, and used by the MCP
server to explain decisions.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("monapi")


@dataclass(frozen=True)
class SignalCatalogue:
    version: int = 0
    categories: dict[str, Any] = field(default_factory=dict)
    signals: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "categories": self.categories,
            "signals": self.signals,
        }

    def lookup(self, signal_id: str) -> dict[str, Any] | None:
        """Resolve a concrete signal id against the catalogue.

        Exact ids win over patterns. Patterns match on the prefix before
        the first placeholder, so `feed:firehol_level2:0` resolves to the
        `feed:<feed_name>:<n>` entry.
        """
        sid = (signal_id or "").strip()
        if not sid:
            return None

        for entry in self.signals:
            if entry.get("id") == sid:
                return entry

        best: dict[str, Any] | None = None
        best_len = -1
        for entry in self.signals:
            pattern = entry.get("id_pattern")
            if not pattern:
                continue
            prefix = pattern.split("<", 1)[0]
            if prefix and sid.startswith(prefix) and len(prefix) > best_len:
                best, best_len = entry, len(prefix)
        return best


def empty_catalogue() -> SignalCatalogue:
    return SignalCatalogue()


def load_catalogue(path: str) -> SignalCatalogue:
    """Load signals.yaml. A missing or broken file degrades to empty.

    The engine must start and decide without the catalogue — it is
    reference material, and an unparseable docs file is never a reason to
    stop answering checks.
    """
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except Exception as exc:
        log.warning("signals_load_failed", extra={"path": path, "error": str(exc)})
        return empty_catalogue()

    signals = [s for s in (raw.get("signals") or []) if isinstance(s, dict)]
    catalogue = SignalCatalogue(
        version=int(raw.get("version", 0)),
        categories=raw.get("categories") or {},
        signals=signals,
    )
    log.info("signals_loaded", extra={"count": len(signals)})
    return catalogue
