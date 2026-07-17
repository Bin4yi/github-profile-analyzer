import logging
import os
import secrets

# Settings() (app/config.py) reads .env via pydantic-settings' own env_file
# mechanism, but that only covers Settings' declared fields -- it doesn't
# populate os.environ. GITHUB_ANALYZER_SHARED_TOKEN below is read directly
# from os.environ, so .env must be loaded into the process explicitly here
# too, before that read happens.
from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, Header, HTTPException

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

# This service holds a real GITHUB_TOKEN and LLM_API_KEY and does real,
# billable work per request -- it must not be an open port. core-api is the
# only intended caller (server-to-server, never exposed to the browser),
# same shared-secret trust model as ai-agents' AGENTS_SHARED_TOKEN.
SHARED_TOKEN = os.environ.get("GITHUB_ANALYZER_SHARED_TOKEN", "dev-only-change-me")


def require_auth(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {SHARED_TOKEN}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.post("/api/v1/analyze", response_model=AnalyzeResponse, dependencies=[Depends(require_auth)])
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


@app.get("/api/v1/profile/{username}", response_model=ProfileStatsResponse, dependencies=[Depends(require_auth)])
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