"""
GitHub GraphQL fetcher.

Additions vs. the v1 query:
  - contributionsCollection: real PR/review/commit activity (last 12 months,
    which is the collection's default window). This replaces the old
    per-repo "PRs merged into MY OWN repos" count, which mostly measured
    noise, not the user's actual contribution activity.
  - createdAt: account age is a useful normalizer (15 repos in 2 months
    reads very differently than 15 repos over 4 years).
  - licenseInfo / hasIssuesEnabled / repositoryTopics on pinned repos:
    cheap "does this person ship things properly" signals.
  - README text (best-effort, README.md or readme.md) on pinned repos,
    trimmed by the AI layer before it's sent to the LLM — a repo that
    explains itself is a stronger hire-signal than raw code volume.
"""

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.core.exceptions import GithubApiError, GithubUserNotFoundError

_settings = get_settings()

_QUERY = """
query($username: String!) {
  user(login: $username) {
    name
    bio
    createdAt
    followers { totalCount }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      totalIssueContributions
      contributionCalendar { totalContributions }
    }
    pinnedItems(first: 6, types: REPOSITORY) {
      nodes {
        ... on Repository {
          name
          description
          stargazerCount
          hasIssuesEnabled
          primaryLanguage { name }
          licenseInfo { name }
          repositoryTopics(first: 5) {
            nodes { topic { name } }
          }
          readme_md: object(expression: "HEAD:README.md") {
            ... on Blob { text }
          }
          readme_lower: object(expression: "HEAD:readme.md") {
            ... on Blob { text }
          }
        }
      }
    }
    repositories(first: 10, orderBy: {field: PUSHED_AT, direction: DESC}, isFork: false) {
      nodes {
        name
        description
        stargazerCount
        pushedAt
        primaryLanguage { name }
      }
    }
  }
}
"""


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=1, max=8),
    retry=retry_if_exception_type(GithubApiError),
)
async def fetch_github_data(username: str) -> dict:
    """
    Raises:
        GithubUserNotFoundError: user doesn't exist / is inaccessible — not worth retrying.
        GithubApiError: transient failure (timeout, rate limit, 5xx) — retried automatically,
            then re-raised to the caller if retries are exhausted.
    """
    async with httpx.AsyncClient(timeout=_settings.github_request_timeout) as client:
        try:
            response = await client.post(
                "https://api.github.com/graphql",
                headers={
                    "Authorization": f"Bearer {_settings.github_token}",
                    "Content-Type": "application/json",
                },
                json={"query": _QUERY, "variables": {"username": username}},
            )
        except httpx.TimeoutException as exc:
            raise GithubApiError(f"GitHub request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise GithubApiError(f"GitHub request failed: {exc}") from exc

    if response.status_code in (401, 403):
        # Bad/expired token or rate-limited — surfaced distinctly since it needs a human,
        # not just a retry.
        raise GithubApiError(f"GitHub auth/rate-limit error: {response.status_code}")

    if response.status_code == 429 or response.status_code >= 500:
        raise GithubApiError(f"GitHub API returned {response.status_code}")

    payload = response.json()

    if "errors" in payload:
        messages = "; ".join(e.get("message", "unknown error") for e in payload["errors"])
        raise GithubUserNotFoundError(f"GitHub query error for '{username}': {messages}")

    user = (payload.get("data") or {}).get("user")
    if user is None:
        # Query succeeded but returned null — user doesn't exist, was renamed, or is a bot/org
        # edge case the schema doesn't cover.
        raise GithubUserNotFoundError(f"GitHub user '{username}' not found or inaccessible")

    return user
