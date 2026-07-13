"""
LLM-based cognitive scoring via NVIDIA NIM (OpenAI-compatible endpoint).

Changes from v1 that matter in production:
  1. AsyncOpenAI, not OpenAI. The sync client's .create() call blocks the
     whole event loop while it waits on the network — inside an `async def`
     FastAPI route that stalls every other in-flight request on the worker.
  2. Structured `tips` in the response, not a single ai_insight string.
     "Tips to improve the profile" is the actual product — a paragraph of
     prose isn't something a UI can render as a checklist.
  3. Explicit completion params. deepseek-v4-flash is a reasoning model, and
     on NIM it's gated by `extra_body.chat_template_kwargs` rather than a
     plain `reasoning_effort` field — omitting it means relying on an
     undocumented default, which some integrations report as hangs or empty
     reasoning_content. max_tokens is set explicitly for the same reason:
     with thinking enabled, the reasoning trace consumes tokens *before* the
     final JSON is generated, so a too-low budget silently truncates the
     answer instead of the thinking.

Note on sampling: DeepSeek recommends temperature=1.0 / top_p=1.0 for their
reasoning modes — low temperature can make some reasoning models degrade or
loop mid-thought. We follow that recommendation here and lean on
response_format=json_object plus the deterministic math score (see
scoring_service.py) to keep the *product* consistent, rather than fighting
the model's training distribution with temperature.
"""

import json
import logging

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)
_settings = get_settings()

_client = AsyncOpenAI(
    base_url=_settings.nvidia_base_url,
    api_key=_settings.nvidia_api_key,
    timeout=_settings.llm_request_timeout,
)

_SYSTEM_PROMPT = """\
You are a senior technical recruiter reviewing a GitHub profile for a {role} role.

Score the developer's pinned repositories:
1. Technical Complexity (0-25): basic tutorials or copy-paste clones score low;
   original systems, non-trivial architecture, or real infrastructure score high.
2. Originality (0-25): standard bootcamp/course clones score low; a unique
   problem or unusual approach scores high.

Also produce 2-4 concrete, actionable tips the candidate could act on this week.
Every tip must reference something specific you actually observed (a repo name,
a missing README, a missing license, a thin description) — no generic advice
like "write more code" or "contribute to open source."

Return ONLY valid JSON, no markdown fences, exactly matching this shape:
{{
  "complexity_score": <int 0-25>,
  "originality_score": <int 0-25>,
  "cognitive_total": <int, sum of the two above>,
  "ai_insight": "<one paragraph summary of the profile>",
  "tips": [
    {{"issue": "<string>", "action": "<string>", "impact": "high" | "medium" | "low"}}
  ]
}}
"""

_FALLBACK = {
    "complexity_score": 0,
    "originality_score": 0,
    "cognitive_total": 0,
    "ai_insight": "AI evaluation is unavailable right now — showing the deterministic score only.",
    "tips": [],
}

_README_EXCERPT_CHARS = 1200  # keep token usage predictable regardless of README length


def _strip_json_fences(text: str) -> str:
    """
    response_format=json_object should prevent this, but reasoning models
    occasionally wrap output in ```json fences anyway — strip defensively
    rather than let a stray fence blow up json.loads.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        text = text.removeprefix("json").strip()
    return text


def _extract_readme_text(repo: dict) -> str:
    """
    readme_md / readme_lower come back from the GraphQL query as Blob objects
    (`{"text": "..."}`), or None if the repo has no README at that path — not
    plain strings. Unwrap here so callers just get text.
    """
    readme_obj = repo.get("readme_md") or repo.get("readme_lower")
    if isinstance(readme_obj, dict):
        return readme_obj.get("text") or ""
    return ""


def _prune_repo(repo: dict) -> dict:
    readme = _extract_readme_text(repo)
    topics = [
        node["topic"]["name"]
        for node in ((repo.get("repositoryTopics") or {}).get("nodes") or [])
    ]
    return {
        "name": repo.get("name"),
        "description": repo.get("description"),
        "language": (repo.get("primaryLanguage") or {}).get("name"),
        "has_license": bool(repo.get("licenseInfo")),
        "topics": topics,
        "readme_excerpt": readme[:_README_EXCERPT_CHARS],
    }


async def get_cognitive_score(pinned_repos: list[dict], target_role: str | None) -> dict:
    if not pinned_repos:
        return {
            **_FALLBACK,
            "ai_insight": "No pinned repos to analyze — pin 4-6 of your strongest projects first.",
        }

    pruned = [_prune_repo(r) for r in pinned_repos]
    role_label = target_role or "general software engineering"

    extra_body = {}
    if _settings.nvidia_thinking_enabled:
        extra_body["chat_template_kwargs"] = {
            "thinking": True,
            "reasoning_effort": _settings.nvidia_reasoning_effort,
        }

    try:
        response = await _client.chat.completions.create(
            model=_settings.nvidia_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT.format(role=role_label)},
                {"role": "user", "content": json.dumps(pruned)},
            ],
            temperature=_settings.nvidia_temperature,
            top_p=_settings.nvidia_top_p,
            max_tokens=_settings.nvidia_max_tokens,
            response_format={"type": "json_object"},
            extra_body=extra_body,
        )
        message = response.choices[0].message

        # Reasoning trace is useful for debugging/prompt-tuning during dev — log it,
        # never return it to the API caller (it's not part of the product, and it's
        # extra tokens the client has no use for).
        reasoning = getattr(message, "reasoning", None) or getattr(message, "reasoning_content", None)
        if reasoning:
            logger.debug("NIM reasoning trace: %s", reasoning)

        parsed = json.loads(_strip_json_fences(message.content))
        parsed.setdefault("tips", [])
        parsed.setdefault("ai_insight", "")
        return parsed
    except (json.JSONDecodeError, KeyError, IndexError, AttributeError) as exc:
        # Model returned something we couldn't parse as the expected JSON shape.
        logger.warning("LLM response did not match expected shape: %s", exc)
        return _FALLBACK
    except Exception as exc:  # noqa: BLE001 — deliberately broad: any NIM/network failure
        # should degrade to the math score, never take the whole request down.
        logger.warning("LLM call failed: %s", exc)
        return _FALLBACK