import logging

from fastapi import FastAPI, HTTPException

from app.core.cache import cache_key, profile_cache
from app.core.exceptions import GithubApiError, GithubUserNotFoundError
from app.schemas import AnalyzeRequest, AnalyzeResponse, ProfileTip, ScoreBreakdown
from app.services import ai_service, github_service, scoring_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="GitHub Profile Analyzer")


def _tier(total_score: int) -> str:
    max_total = scoring_service.MATH_MAX + scoring_service.AI_MAX
    if total_score >= max_total * 0.75:
        return "Exceptional"
    if total_score >= max_total * 0.45:
        return "Solid"
    return "Needs Work"


@app.post("/api/v1/analyze", response_model=AnalyzeResponse)
async def analyze_profile(request: AnalyzeRequest) -> AnalyzeResponse:
    username = request.github_username.strip()
    key = cache_key(username, request.target_role)

    if key in profile_cache:
        logger.info("Cache hit for %s", key)
        return AnalyzeResponse(**profile_cache[key], cached=True)

    logger.info("Fetching fresh data for %s", key)

    try:
        github_data = await github_service.fetch_github_data(username)
    except GithubUserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GithubApiError as exc:
        raise HTTPException(status_code=502, detail=f"GitHub is unavailable right now: {exc}") from exc

    pinned_repos = (github_data.get("pinnedItems") or {}).get("nodes") or []

    math_result = scoring_service.calculate_math_score(github_data)
    ai_result = await ai_service.get_cognitive_score(pinned_repos, request.target_role)

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

    if ai_result.get("_ai_degraded", False):
        logger.warning("Not caching %s — AI scoring degraded this request", key)
    else:
        profile_cache[key] = response.model_dump(exclude={"cached"})

    return response


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
