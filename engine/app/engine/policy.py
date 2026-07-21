from __future__ import annotations

from app.engine.models import Decision, DecisionAction
from app.engine.profiles import PolicyProfile, default_profile


def decision_from_score(
    score: int, profile: PolicyProfile | None = None
) -> tuple[Decision, DecisionAction | None]:
    p = profile or default_profile()
    if score >= p.block:
        return "block", None
    if score >= p.challenge:
        return (
            "challenge",
            DecisionAction(
                type="soft_block",
                retry_after_seconds=300,
                reason="score_in_challenge_band",
            ),
        )
    return "allow", None
