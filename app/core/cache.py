"""
In-memory TTL cache. Fine for a single dev/staging instance.

The moment you run more than one uvicorn worker or more than one replica,
each process gets its own cache and your hit rate quietly collapses — swap
this module for a Redis-backed version at that point. Nothing outside this
file needs to change: main.py only calls cache_key() / dict-style get-set.
"""

from cachetools import TTLCache

from app.config import get_settings

_settings = get_settings()

profile_cache: TTLCache = TTLCache(maxsize=_settings.cache_maxsize, ttl=_settings.cache_ttl_seconds)

# Separate cache/TTLCache instance from profile_cache: the raw stats endpoint has no
# target_role dimension and a different response shape, so it gets its own namespace
# rather than sharing keys with the AI-scored /analyze cache.
stats_cache: TTLCache = TTLCache(maxsize=_settings.cache_maxsize, ttl=_settings.cache_ttl_seconds)


def cache_key(username: str, target_role: str | None) -> str:
    """
    GitHub usernames are case-insensitive ('Torvalds' == 'torvalds') but a plain
    dict/TTLCache key is not — normalize or you silently double your cache misses.
    target_role is folded in because the same profile can score differently
    depending on which role the AI layer is asked to evaluate it against.
    """
    normalized_role = (target_role or "").strip().lower()
    return f"{username.strip().lower()}:{normalized_role}"


def stats_cache_key(username: str) -> str:
    return username.strip().lower()
