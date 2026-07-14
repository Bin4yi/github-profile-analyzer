"""
AI-scored profile analysis — the cognitive counterpart to stats_service's raw
output.

This module owns the full /api/v1/analyze response: it fetches raw data via
github_service, computes the deterministic math score via scoring_service,
asks ai_service for the cognitive score/insight/tips, combines them into a
final score + tier, and returns the assembled AnalyzeResponse. main.py only
handles caching + HTTP error mapping — it doesn't know how any of these
numbers are derived.
"""

from app.schemas import AnalyzeResponse, ProfileTip, ScoreBreakdown
from app.services import ai_service, github_service, scoring_service


def _tier(total_score: int) -> str:
    # Relocated from main.py: tier labeling is response-building logic, not routing.
    max_total = scoring_service.MATH_MAX + scoring_service.AI_MAX
    if total_score >= max_total * 0.75:
        return "Exceptional"
    if total_score >= max_total * 0.45:
        return "Solid"
    return "Needs Work"


async def build_analyze_response(username: str, target_role: str | None) -> tuple[AnalyzeResponse, bool]:
    """
    Returns (response, ai_degraded). main.py uses ai_degraded to decide whether
    to skip caching this result — the same behavior the inline handler used to
    implement by reading ai_result["_ai_degraded"] directly.
    """
    github_data = await github_service.fetch_github_data(username)

    pinned_repos = (github_data.get("pinnedItems") or {}).get("nodes") or []
    recent_repos = (github_data.get("repositories") or {}).get("nodes") or []

    math_result = scoring_service.calculate_math_score(github_data)
    ai_result = await ai_service.get_cognitive_score(pinned_repos, recent_repos, target_role)

    final_score = math_result["math_score"] + ai_result["cognitive_total"]

    response = AnalyzeResponse(
        username=username,
        name=github_data.get("name"),
        final_score=final_score,
        tier=_tier(final_score),
        breakdown=ScoreBreakdown(
            math_score=math_result["math_score"],
            cognitive_score=ai_result["cognitive_total"],
            complexity_score=ai_result.get("complexity_score", 0),
            originality_score=ai_result.get("originality_score", 0),
        ),
        ai_insight=ai_result.get("ai_insight", ""),
        tips=[ProfileTip(**tip) for tip in ai_result.get("tips", [])],
        cached=False,
    )

    return response, ai_result.get("_ai_degraded", False)
