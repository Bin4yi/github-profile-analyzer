"""
Centralized settings. Everything that used to be scattered os.getenv() calls
now lives here and is validated once at startup — a missing GITHUB_TOKEN or
LLM_API_KEY fails fast instead of surfacing as a confusing 500 later.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- GitHub ---
    github_token: str
    github_request_timeout: float = 15.0

    # --- LLM provider (any OpenAI-compatible endpoint) ---
    # Primary, currently pointed at Gemini. ai_service.py only talks the OpenAI chat-completions
    # shape. Optional (unlike github_token) since openai_api_key below can run
    # standalone as the only provider -- the AsyncOpenAI client itself fails
    # fast at construction time on an empty-string key, so ai_service.py must
    # skip constructing it entirely when this is unset rather than pass "".
    llm_api_key: str | None = None
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_model: str = "gemini-3.5-flash"

    llm_reasoning_effort: str = "low"  # "minimal" | "low" | "medium" | "high"
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.3  # our own choice for consistent scoring, tune freely
    llm_top_p: float = 0.95
    llm_request_timeout: float = 45.0

    # --- LLM provider, fallback (real OpenAI endpoint) ---
    # Optional -- if set, ai_service tries the primary provider above first and
    # only falls back to this one on failure (bad/expired key, rate limit,
    # outage). Two independent providers means neither one being down takes
    # AI scoring down with it. Uses max_completion_tokens (not max_tokens) and
    # skips reasoning_effort -- gpt-5.4-mini rejects max_tokens outright and
    # doesn't take reasoning_effort as a plain chat-completions param, unlike
    # Gemini's OpenAI-compat layer.
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"

    # --- Cache ---
    cache_maxsize: int = 1000
    cache_ttl_seconds: int = 172_800  # 48 hours

    # --- Logging ---
    log_dir: str = "logs"  
    log_level: str = "INFO"
    log_max_bytes: int = 10_000_000  # 10MB per file before rotating
    log_backup_count: int = 5  # keep 5 rotated files per log (app.log.1, .2, ...)


@lru_cache
def get_settings() -> Settings:
    """Cached so Settings() — which reads the environment — only runs once per process."""
    return Settings()