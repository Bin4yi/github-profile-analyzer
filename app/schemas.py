from typing import Literal

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    github_username: str = Field(..., min_length=1, max_length=39)
    # Optional — lets the AI layer weight its commentary toward a specific role
    # instead of giving generic feedback. e.g. "backend", "ai engineering".
    target_role: str | None = Field(default=None, max_length=64)


class ProfileTip(BaseModel):
    issue: str
    action: str
    impact: Literal["high", "medium", "low"]


class ScoreBreakdown(BaseModel):
    math_score: int
    cognitive_score: int
    complexity_score: int
    originality_score: int


class AnalyzeResponse(BaseModel):
    username: str
    name: str | None
    final_score: int
    tier: Literal["Exceptional", "Solid", "Needs Work"]
    breakdown: ScoreBreakdown
    ai_insight: str
    tips: list[ProfileTip]
    cached: bool = False


class TopRepo(BaseModel):
    name: str
    description: str | None
    language: str | None
    stars: int
    commits: int


class RecentActivityItem(BaseModel):
    repo: str
    prRef: str
    message: str
    impact: str
    date: str


class ContributionDay(BaseModel):
    date: str
    count: int


class ProfileStatsResponse(BaseModel):
    username: str
    totalRepos: int
    totalCommits: int
    contributionStreakDays: int
    topRepos: list[TopRepo]
    recentActivity: list[RecentActivityItem]
    languageBreakdownPct: dict[str, float]
    contributionCalendar: list[ContributionDay]
    cached: bool = False
