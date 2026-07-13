class GithubUserNotFoundError(Exception):
    """The GitHub user doesn't exist, was renamed, or the profile is inaccessible."""


class GithubApiError(Exception):
    """Transient GitHub failure — timeout, rate limit, 5xx. Safe to retry."""
