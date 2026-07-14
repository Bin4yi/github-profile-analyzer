"""
Deterministic scoring — no LLM involved, so it's free, instant, and
consistent (same input always gives the same score, which matters if a user
compares two runs and asks "why did my score change").

The point values below are a v1 rubric, not a calibrated model — tune the
constants once you have real profile data to check the tiers against.
MATH_MAX / AI_MAX are computed from the constants so main.py's tier logic
never drifts out of sync with this file.
"""

from datetime import datetime, timezone

# --- point budget (documented so the constants stay honest) ---
_BIO_PRESENT = 5
_FOLLOWERS_OVER_10 = 5
_ACCOUNT_AGE_2Y_PLUS = 5
_PINNED_COUNT_PER_REPO = 2          # capped
_PINNED_COUNT_CAP = 12
_DOCUMENTED_PER_REPO = 1            # capped
_DOCUMENTED_CAP = 5
_LICENSED_PER_REPO = 1              # capped
_LICENSED_CAP = 5
_README_PER_REPO = 2                # capped
_README_CAP = 10
_PR_CONTRIB_HIGH = 20                # >20 authored PRs in the last year
_PR_CONTRIB_MID = 12                 # >5
_PR_CONTRIB_LOW = 6                  # >0
_PR_REVIEW_BONUS = 5                 # reviewed at least one PR — signals collaboration
_COMMIT_HIGH = 10                    # >200 commits in the last year
_COMMIT_MID = 5                      # >50

MATH_MAX = (
    _BIO_PRESENT
    + _FOLLOWERS_OVER_10
    + _ACCOUNT_AGE_2Y_PLUS
    + _PINNED_COUNT_CAP
    + _DOCUMENTED_CAP
    + _LICENSED_CAP
    + _README_CAP
    + _PR_CONTRIB_HIGH
    + _PR_REVIEW_BONUS
    + _COMMIT_HIGH
)  # = 82

AI_MAX = 50  # complexity_score (25) + originality_score (25), see ai_service.py


def _account_age_years(created_at: str | None) -> float:
    if not created_at:
        return 0.0
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - created).days / 365.25


def _has_readme(repo: dict) -> bool:
    return bool(repo.get("readme_md") or repo.get("readme_lower"))


def calculate_math_score(github_data: dict) -> dict:
    score = 0

    if github_data.get("bio"):
        score += _BIO_PRESENT

    if (github_data.get("followers") or {}).get("totalCount", 0) > 10:
        score += _FOLLOWERS_OVER_10

    if _account_age_years(github_data.get("createdAt")) >= 2:
        score += _ACCOUNT_AGE_2Y_PLUS

    pinned = (github_data.get("pinnedItems") or {}).get("nodes") or []
    recent = (github_data.get("repositories") or {}).get("nodes") or []

    showcase_repos = pinned if pinned else recent[:6]

    score += min(len(showcase_repos) * _PINNED_COUNT_PER_REPO, _PINNED_COUNT_CAP)

    documented = sum(1 for r in showcase_repos if r.get("description"))
    score += min(documented * _DOCUMENTED_PER_REPO, _DOCUMENTED_CAP)

    licensed = sum(1 for r in showcase_repos if r.get("licenseInfo"))
    score += min(licensed * _LICENSED_PER_REPO, _LICENSED_CAP)

    with_readme = sum(1 for r in showcase_repos if _has_readme(r))
    score += min(with_readme * _README_PER_REPO, _README_CAP)

    contributions = github_data.get("contributionsCollection") or {}
    pr_count = contributions.get("totalPullRequestContributions", 0)
    review_count = contributions.get("totalPullRequestReviewContributions", 0)
    commit_count = contributions.get("totalCommitContributions", 0)

    if pr_count > 20:
        score += _PR_CONTRIB_HIGH
    elif pr_count > 5:
        score += _PR_CONTRIB_MID
    elif pr_count > 0:
        score += _PR_CONTRIB_LOW

    if review_count > 0:
        score += _PR_REVIEW_BONUS

    if commit_count > 200:
        score += _COMMIT_HIGH
    elif commit_count > 50:
        score += _COMMIT_MID

    return {"math_score": min(score, MATH_MAX)}
