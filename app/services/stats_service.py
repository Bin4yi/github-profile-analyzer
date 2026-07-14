"""
Raw GitHub stats — the deterministic counterpart to ai_service's scored output.

This module owns the full /api/v1/profile response: it fetches raw data via
github_service, does all the pure aggregation (streak, language %, top repos,
calendar), asks ai_service for short "impact" one-liners on recent activity, and
returns the assembled ProfileStatsResponse. main.py only handles caching + HTTP
error mapping — it doesn't know how any of these numbers are derived.
"""

from app.schemas import ContributionDay, ProfileStatsResponse, RecentActivityItem, TopRepo
from app.services import ai_service, github_service

_TOP_REPOS_LIMIT = 5
_RECENT_ACTIVITY_LIMIT = 10
_LANGUAGE_TOP_N = 6


def _flatten_calendar(contributions_collection: dict) -> list[dict]:
    weeks = ((contributions_collection.get("contributionCalendar") or {}).get("weeks")) or []
    days: list[dict] = []
    for week in weeks:
        for day in week.get("contributionDays") or []:
            days.append({"date": day.get("date"), "count": day.get("contributionCount") or 0})
    return days


def _compute_streak(calendar: list[dict]) -> int:
    """
    Trailing count of consecutive count>0 days, walking backward from the most
    recent entry. Must stay in lockstep with the calendar array — a UI that pads
    the calendar and shows N green trailing days should always see this equal N.
    """
    streak = 0
    for day in reversed(calendar):
        if day["count"] > 0:
            streak += 1
        else:
            break
    return streak


def _commit_counts_by_repo(contributions_collection: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in contributions_collection.get("commitContributionsByRepository") or []:
        repo_name = (entry.get("repository") or {}).get("name")
        if repo_name:
            counts[repo_name] = (entry.get("contributions") or {}).get("totalCount") or 0
    return counts


def _compute_top_repos(repo_nodes: list[dict], commit_counts: dict[str, int]) -> list[TopRepo]:
    top = []
    for repo in repo_nodes[:_TOP_REPOS_LIMIT]:
        name = repo.get("name")
        top.append(
            TopRepo(
                name=name,
                description=repo.get("description"),
                language=(repo.get("primaryLanguage") or {}).get("name"),
                stars=repo.get("stargazerCount") or 0,
                commits=commit_counts.get(name, 0),
            )
        )
    return top


def _compute_language_breakdown(repo_nodes: list[dict]) -> dict[str, float]:
    totals: dict[str, int] = {}
    for repo in repo_nodes:
        for edge in (repo.get("languages") or {}).get("edges") or []:
            name = (edge.get("node") or {}).get("name")
            size = edge.get("size") or 0
            if name:
                totals[name] = totals.get(name, 0) + size

    total_size = sum(totals.values())
    if total_size == 0:
        return {}

    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    entries = ranked[:_LANGUAGE_TOP_N]
    other_size = sum(size for _, size in ranked[_LANGUAGE_TOP_N:])
    if other_size > 0:
        entries = [*entries, ("Other", other_size)]

    # Largest-remainder rounding so percentages always sum to exactly 100, not ~100.
    raw_pcts = [size / total_size * 100 for _, size in entries]
    floors = [int(pct) for pct in raw_pcts]
    remainder = 100 - sum(floors)
    order_by_frac = sorted(range(len(entries)), key=lambda i: raw_pcts[i] - floors[i], reverse=True)
    for i in range(remainder):
        floors[order_by_frac[i % len(entries)]] += 1

    return {entries[i][0]: float(floors[i]) for i in range(len(entries))}


def _build_activity_candidates(pull_requests: dict, repo_nodes: list[dict]) -> list[dict]:
    """
    Merged PRs are the primary source (clean prRef, one item per PR). For repos
    with zero merged PRs — solo projects with no PR workflow — fall back to their
    single most recent default-branch commit so those repos aren't invisible in
    recentActivity. Combined list is capped and sorted most-recent-first.
    """
    candidates: list[dict] = []
    repos_with_prs: set[str] = set()

    for pr in pull_requests.get("nodes") or []:
        repo_name = (pr.get("repository") or {}).get("name")
        merged_at = pr.get("mergedAt")
        if not repo_name or not merged_at:
            continue
        repos_with_prs.add(repo_name)
        candidates.append(
            {
                "repo": repo_name,
                "prRef": f"PR #{pr.get('number')}",
                "message": pr.get("title") or "",
                "body": pr.get("bodyText") or "",
                "date": merged_at[:10],
                "_sort_key": merged_at,
            }
        )

    for repo in repo_nodes:
        repo_name = repo.get("name")
        if not repo_name or repo_name in repos_with_prs:
            continue
        history_nodes = (((repo.get("defaultBranchRef") or {}).get("target") or {}).get("history") or {}).get(
            "nodes"
        ) or []
        if not history_nodes:
            continue
        commit = history_nodes[0]
        committed_at = commit.get("committedDate")
        if not committed_at:
            continue
        candidates.append(
            {
                "repo": repo_name,
                "prRef": "Commit",
                "message": commit.get("messageHeadline") or "",
                "body": "",
                "date": committed_at[:10],
                "_sort_key": committed_at,
            }
        )

    candidates.sort(key=lambda item: item["_sort_key"], reverse=True)
    return candidates[:_RECENT_ACTIVITY_LIMIT]


async def build_stats_response(username: str) -> ProfileStatsResponse:
    github_data = await github_service.fetch_profile_stats_data(username)

    repositories = github_data.get("repositories") or {}
    repo_nodes = repositories.get("nodes") or []
    pull_requests = github_data.get("pullRequests") or {}
    contributions_collection = github_data.get("contributionsCollection") or {}

    calendar = _flatten_calendar(contributions_collection)
    commit_counts = _commit_counts_by_repo(contributions_collection)
    activity_candidates = _build_activity_candidates(pull_requests, repo_nodes)

    impacts = await ai_service.summarize_activity_impacts(
        [{"repo": item["repo"], "message": item["message"], "body": item["body"]} for item in activity_candidates]
    )

    recent_activity = [
        RecentActivityItem(
            repo=item["repo"],
            prRef=item["prRef"],
            message=item["message"],
            impact=impacts[i] if i < len(impacts) else item["message"],
            date=item["date"],
        )
        for i, item in enumerate(activity_candidates)
    ]

    return ProfileStatsResponse(
        username=username,
        totalRepos=repositories.get("totalCount") or 0,
        totalCommits=contributions_collection.get("totalCommitContributions") or 0,
        contributionStreakDays=_compute_streak(calendar),
        topRepos=_compute_top_repos(repo_nodes, commit_counts),
        recentActivity=recent_activity,
        languageBreakdownPct=_compute_language_breakdown(repo_nodes),
        contributionCalendar=[ContributionDay(**day) for day in calendar],
        cached=False,
    )
