from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger("monapi")

# Hard fallback if the config file is missing or broken. Matches the
# original hardcoded thresholds.
DEFAULT_CHALLENGE = 30
DEFAULT_BLOCK = 80


@dataclass(frozen=True)
class PolicyProfile:
    name: str
    challenge: int = DEFAULT_CHALLENGE
    block: int = DEFAULT_BLOCK
    weights: dict[str, int] = field(default_factory=dict)
    ignore: frozenset[str] = frozenset()


def default_profile() -> PolicyProfile:
    return PolicyProfile(name="default")


def load_profiles(path: str) -> dict[str, PolicyProfile]:
    """Load policy profiles from YAML. Always returns at least "default".

    Invalid entries are skipped with a warning; a broken file falls back
    to the built-in default profile. Deliberately no rule language —
    thresholds, weight overrides and category ignores only.
    """
    profiles: dict[str, PolicyProfile] = {"default": default_profile()}

    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except Exception as exc:
        log.warning("policies_load_failed", extra={"path": path, "error": str(exc)})
        return profiles

    for name, spec in (raw.get("profiles") or {}).items():
        try:
            name = str(name)
            spec = spec or {}
            thresholds = spec.get("thresholds") or {}
            challenge = int(thresholds.get("challenge", DEFAULT_CHALLENGE))
            block = int(thresholds.get("block", DEFAULT_BLOCK))
            if not (0 <= challenge < block <= 100):
                raise ValueError(f"invalid thresholds challenge={challenge} block={block}")
            weights = {str(k): int(v) for k, v in (spec.get("weights") or {}).items()}
            ignore = frozenset(str(c) for c in (spec.get("ignore") or []))
            profiles[name] = PolicyProfile(
                name=name, challenge=challenge, block=block, weights=weights, ignore=ignore
            )
        except Exception as exc:
            log.warning("policies_profile_skipped", extra={"profile": str(name), "error": str(exc)})

    log.info("policies_loaded", extra={"profiles": sorted(profiles)})
    return profiles
