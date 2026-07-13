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
    # Currently pointed at Gemini. ai_service.py only talks the OpenAI chat-completions
    llm_api_key: str
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_model: str = "gemini-3.5-flash"

    llm_reasoning_effort: str = "low"  # "minimal" | "low" | "medium" | "high"
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.3  # our own choice for consistent scoring, tune freely
    llm_top_p: float = 0.95
    llm_request_timeout: float = 45.0

    # --- Cache ---
    cache_maxsize: int = 1000
    cache_ttl_seconds: int = 172_800  # 48 hours


@lru_cache
def get_settings() -> Settings:
    """Cached so Settings() — which reads the environment — only runs once per process."""
    return Settings()