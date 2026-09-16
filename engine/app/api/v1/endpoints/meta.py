"""Discovery endpoints: what this instance can emit and how it decides.

Both are per-instance facts — feeds and profiles are configuration, so a
client cannot hardcode them. Agents and client libraries read these
instead of the source.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.auth import require_api_key
from app.engine.profiles import PolicyProfile


router = APIRouter()


def _profile_dict(p: PolicyProfile) -> dict:
    return {
        "name": p.name,
        "thresholds": {"challenge": p.challenge, "block": p.block},
        "weights": dict(p.weights),
        "ignore": sorted(p.ignore),
    }


@router.get("/signals")
async def list_signals(request: Request, _key: str = Depends(require_api_key)):
    """The signal catalogue: every signal id this engine can emit.

    Reference material, identical for every caller. `signal` narrows the
    response to the one entry matching a concrete id from a decision —
    exact ids win, patterns match by prefix, so `feed:tor_exits:0`
    resolves to the `feed:<feed_name>:<n>` entry.
    """
    catalogue = request.app.state.signals
    wanted = request.query_params.get("signal")
    if wanted:
        entry = catalogue.lookup(wanted)
        if entry is None:
            return {
                "version": catalogue.version,
                "query": wanted,
                "found": False,
                "signals": [],
            }
        # A pattern entry names several categories in prose
        # ("abuse | anonymizer | datacenter"); include each one that is
        # actually documented rather than requiring an exact match.
        named = str(entry.get("category", ""))
        return {
            "version": catalogue.version,
            "query": wanted,
            "found": True,
            "signals": [entry],
            "categories": {
                k: v for k, v in catalogue.categories.items() if k in named
            },
        }
    return catalogue.as_dict()


@router.get("/profiles")
async def list_profiles(request: Request, _key: str = Depends(require_api_key)):
    """Policy profiles configured on this instance, selectable via ?profile=.

    Thresholds, weight overrides and ignored categories as loaded from
    policies.yaml — what a caller needs to pick the right profile without
    guessing at its behaviour.
    """
    profiles = getattr(request.app.state, "profiles", None) or {}
    return {
        "default": "default",
        "profiles": [_profile_dict(p) for _, p in sorted(profiles.items())],
    }
