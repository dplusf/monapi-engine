from __future__ import annotations

from app.engine.models import Decision, DecisionAction


def decision_from_score(score: int) -> tuple[Decision, DecisionAction | None]:
    if score >= 80:
        return "block", None
    if score >= 30:
        return (
            "challenge",
            DecisionAction(
                type="soft_block",
                retry_after_seconds=300,
                reason="score_in_challenge_band",
            ),
        )
    return "allow", None
