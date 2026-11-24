"""Product matching: deterministic rules first, optional AI review for ambiguous cases."""

from app.services.matching.engine import SOURCE_REASON, MatchDecision, classify
from app.services.matching.llm_review import (
    CachedReviewer,
    ClaudeMatchReviewer,
    MatchReviewer,
    ReviewBudget,
    review_decision,
)

__all__ = [
    "SOURCE_REASON",
    "CachedReviewer",
    "ClaudeMatchReviewer",
    "MatchDecision",
    "MatchReviewer",
    "ReviewBudget",
    "classify",
    "review_decision",
]
