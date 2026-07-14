import logging

from fastapi import FastAPI, HTTPException

from app.core.cache import cache_key, profile_cache, stats_cache, stats_cache_key
from app.core.exceptions import GithubApiError, GithubUserNotFoundError
from app.core.logging_config import setup_logging
from app.core.middleware import AccessLogMiddleware
from app.schemas import AnalyzeRequest, AnalyzeResponse, ProfileStatsResponse
from app.services import analyze_service, stats_service

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="GitHub Profile Analyzer")
app.add_middleware(AccessLogMiddleware)


@app.post("/api/v1/analyze", response_model=AnalyzeResponse)
async def analyze_profile(request: AnalyzeRequest) -> AnalyzeResponse:
    username = request.github_username.strip()
    key = cache_key(username, request.target_role)

    if key in profile_cache:
        logger.info("Cache hit for %s", key)
        return AnalyzeResponse(**profile_cache[key], cached=True)

    logger.info("Fetching fresh data for %s", key)

    try:
        response, ai_degraded = await analyze_service.build_analyze_response(username, request.target_role)
    except GithubUserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GithubApiError as exc:
        raise HTTPException(status_code=502, detail=f"GitHub is unavailable right now: {exc}") from exc

    if ai_degraded:
        logger.warning("Not caching %s — AI scoring degraded this request", key)
    else:
        profile_cache[key] = response.model_dump(exclude={"cached"})

    return response


@app.get("/api/v1/profile/{username}", response_model=ProfileStatsResponse)
async def get_profile_stats(username: str) -> ProfileStatsResponse:
    username = username.strip()
    key = stats_cache_key(username)

    if key in stats_cache:
        logger.info("Stats cache hit for %s", key)
        return ProfileStatsResponse(**stats_cache[key], cached=True)

    logger.info("Fetching fresh stats for %s", key)

    try:
        response = await stats_service.build_stats_response(username)
    except GithubUserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GithubApiError as exc:
        raise HTTPException(status_code=502, detail=f"GitHub is unavailable right now: {exc}") from exc

    stats_cache[key] = response.model_dump(exclude={"cached"})
    return response


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}