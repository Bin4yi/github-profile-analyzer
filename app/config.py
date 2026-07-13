"""
Centralized settings. Everything that used to be scattered os.getenv() calls
now lives here and is validated once at startup — a missing GITHUB_TOKEN or
NVIDIA_API_KEY fails fast instead of surfacing as a confusing 500 later.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- GitHub ---
    github_token: str
    github_request_timeout: float = 15.0

    # --- NVIDIA NIM (OpenAI-compatible) ---
    nvidia_api_key: str
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "deepseek-ai/deepseek-v4-flash"

    # deepseek-v4-flash is a reasoning model — NIM gates its <think> behavior on
    # chat_template_kwargs rather than the standard `reasoning_effort` param, and
    # without max_tokens set explicitly you're at the mercy of an undocumented
    # default. Keep these tunable so you're not editing code to A/B them later.
    nvidia_thinking_enabled: bool = True
    nvidia_reasoning_effort: str = "high"  # "high" | "max" ("max" needs a huge context window — avoid)
    nvidia_max_tokens: int = 8192  # thinking tokens + final JSON both count against this
    nvidia_temperature: float = 1.0  # DeepSeek's own recommendation for thinking mode
    nvidia_top_p: float = 0.95

    # Thinking mode adds real latency — 30s was tight even before this.
    llm_request_timeout: float = 60.0

    # --- Cache ---
    cache_maxsize: int = 1000
    cache_ttl_seconds: int = 172_800  # 48 hours


@lru_cache
def get_settings() -> Settings:
    """Cached so Settings() — which reads the environment — only runs once per process."""
    return Settings()
