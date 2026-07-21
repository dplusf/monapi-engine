from __future__ import annotations

from fastapi import HTTPException, Query, Request

from app.engine.profiles import PolicyProfile, default_profile


def get_profile(request: Request, profile: str = Query("default")) -> PolicyProfile:
    """Resolve ?profile= against loaded policy profiles. Unknown -> 400."""
    profiles = getattr(request.app.state, "profiles", None) or {"default": default_profile()}
    p = profiles.get(profile)
    if p is None:
        raise HTTPException(
            status_code=400,
            detail={"error": "unknown_profile", "available": sorted(profiles)},
        )
    return p
