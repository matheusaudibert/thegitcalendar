"""Fetches a GitHub user's contribution calendar and profile.

Two sources, fetched together:

- Contributions come from the public HTML fragment at
  ``github.com/users/{username}/contributions`` — the same one embedded on the
  profile page, so the counts match exactly what anyone sees there (including
  anonymized private contributions). The GraphQL calendar undercounts those,
  so it isn't used for the dots. We parse the
  ``<td class="ContributionCalendar-day">`` cells (data-date / data-level) and
  match each one to its ``<tool-tip>`` sibling to recover the exact count.
- The canonical login and avatar URL come from GitHub's authenticated GraphQL
  API (``GITHUB_TOKEN`` env var — a fine-grained token with public read-only
  access and no extra permissions is enough).
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

CONTRIBUTIONS_URL = "https://github.com/users/{username}/contributions"
GRAPHQL_URL = "https://api.github.com/graphql"
USER_AGENT = "gitcalendar/1.0 (+https://github.com/matheusaudibert/thegitcalendar)"
REQUEST_TIMEOUT = 10.0
MAX_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 1.0

_PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) { login avatarUrl(size: 200) }
}
"""

_TD_OPEN_RE = re.compile(r"<td\s+([^>]*)>")
_TOOLTIP_RE = re.compile(r'<tool-tip[^>]*\sfor="([^"]+)"[^>]*>([^<]*)</tool-tip>')
_COUNT_RE = re.compile(r"^\s*(No|\d+)\s+contributions?\s+on\b", re.IGNORECASE)


class GitHubUserNotFoundError(Exception):
    def __init__(self, username: str):
        self.username = username
        super().__init__(f"GitHub user '{username}' not found")


class GitHubFetchError(Exception):
    pass


@dataclass(frozen=True)
class DayData:
    date: date
    level: int  # 0-4, GitHub's own bucketed intensity
    count: int | None  # exact contribution count, if we could parse it


@dataclass(frozen=True)
class YearContributions:
    username: str  # canonical login, spelled the way GitHub does
    avatar_url: str
    year: int
    days: dict[date, DayData]
    fetched_at: float


def _github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise GitHubFetchError("GITHUB_TOKEN is not configured on the server")
    return token


def _attr(attrs: str, name: str) -> str | None:
    m = re.search(rf'{name}="([^"]*)"', attrs)
    return m.group(1) if m else None


def _parse_html(html: str, username: str) -> dict[date, DayData]:
    id_to_date: dict[str, date] = {}
    level_by_date: dict[date, int] = {}

    for m in _TD_OPEN_RE.finditer(html):
        attrs = m.group(1)
        if "ContributionCalendar-day" not in attrs:
            continue
        date_str = _attr(attrs, "data-date")
        level_str = _attr(attrs, "data-level")
        cell_id = _attr(attrs, "id")
        if not date_str or level_str is None:
            continue
        try:
            day = date.fromisoformat(date_str)
            level = int(level_str)
        except ValueError:
            continue
        level_by_date[day] = level
        if cell_id:
            id_to_date[cell_id] = day

    count_by_date: dict[date, int] = {}
    for tm in _TOOLTIP_RE.finditer(html):
        cell_id, text = tm.group(1), tm.group(2)
        day = id_to_date.get(cell_id)
        if day is None:
            continue
        count_m = _COUNT_RE.match(text)
        if not count_m:
            continue
        token = count_m.group(1)
        count_by_date[day] = 0 if token.lower() == "no" else int(token)

    if not level_by_date:
        raise GitHubFetchError(
            f"Could not find any contribution cells for '{username}' — "
            "GitHub may have changed its markup."
        )

    return {
        day: DayData(date=day, level=level, count=count_by_date.get(day))
        for day, level in level_by_date.items()
    }


async def _request_with_retries(
    method: str,
    url: str,
    *,
    client: httpx.AsyncClient,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    json: dict | None = None,
) -> httpx.Response:
    """Sends the request, retrying network errors and 5xx/429 responses a few
    times (GitHub's contributions page returns sporadic 504s). Failures that
    survive every attempt surface as GitHubFetchError instead of leaking raw
    httpx exceptions.
    """
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)
        try:
            resp = await client.request(
                method,
                url,
                params=params,
                json=json,
                headers={"User-Agent": USER_AGENT, **(headers or {})},
            )
        except httpx.HTTPError as exc:
            last_error = exc
            continue
        if resp.status_code >= 500 or resp.status_code == 429:
            last_error = GitHubFetchError(f"GitHub returned HTTP {resp.status_code}")
            continue
        return resp
    raise GitHubFetchError(
        f"Could not reach GitHub after {MAX_ATTEMPTS} attempts: {last_error}"
    ) from last_error


async def _fetch_calendar(
    client: httpx.AsyncClient, username: str, from_date: date, to_date: date
) -> dict[date, DayData]:
    resp = await _request_with_retries(
        "GET",
        CONTRIBUTIONS_URL.format(username=username),
        client=client,
        params={"from": from_date.isoformat(), "to": to_date.isoformat()},
    )
    if resp.status_code == 404:
        raise GitHubUserNotFoundError(username)
    if resp.status_code != 200:
        raise GitHubFetchError(
            f"GitHub returned HTTP {resp.status_code} for user '{username}'"
        )
    days = _parse_html(resp.text, username)
    # Keep only the requested calendar year — GitHub pads the grid with a few
    # extra days from adjacent weeks to keep full week columns.
    return {d: v for d, v in days.items() if from_date <= d <= to_date}


async def _fetch_profile(client: httpx.AsyncClient, username: str) -> tuple[str, str]:
    """Returns (canonical login, avatar URL)."""
    resp = await _request_with_retries(
        "POST",
        GRAPHQL_URL,
        client=client,
        headers={"Authorization": f"Bearer {_github_token()}"},
        json={"query": _PROFILE_QUERY, "variables": {"login": username}},
    )
    if resp.status_code == 401:
        raise GitHubFetchError("GITHUB_TOKEN was rejected by GitHub (invalid or expired)")
    if resp.status_code != 200:
        raise GitHubFetchError(
            f"GitHub API returned HTTP {resp.status_code} for user '{username}'"
        )

    payload = resp.json()
    user = (payload.get("data") or {}).get("user")
    if user is None:
        if any(e.get("type") == "NOT_FOUND" for e in payload.get("errors") or []):
            raise GitHubUserNotFoundError(username)
        raise GitHubFetchError(
            f"GitHub API error for user '{username}': {payload.get('errors')}"
        )
    return user["login"], user["avatarUrl"]


async def fetch_year_contributions(
    username: str, year: int, *, client: httpx.AsyncClient | None = None
) -> YearContributions:
    """Fetch one calendar year (Jan 1 - Dec 31) of contributions, plus the
    user's canonical login and avatar URL."""
    from_date = date(year, 1, 1)
    to_date = date(year, 12, 31)

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True)
    try:
        days, (login, avatar_url) = await asyncio.gather(
            _fetch_calendar(client, username, from_date, to_date),
            _fetch_profile(client, username),
        )
    finally:
        if owns_client:
            await client.aclose()

    return YearContributions(
        username=login,
        avatar_url=avatar_url,
        year=year,
        days=days,
        fetched_at=time.time(),
    )


async def fetch_avatar(avatar_url: str, *, client: httpx.AsyncClient | None = None) -> bytes:
    """Download an avatar image (PNG/JPEG bytes) from GitHub's avatar CDN."""
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True)
    try:
        resp = await _request_with_retries("GET", avatar_url, client=client)
    finally:
        if owns_client:
            await client.aclose()

    if resp.status_code != 200:
        raise GitHubFetchError(f"GitHub returned HTTP {resp.status_code} fetching avatar")
    if not resp.headers.get("content-type", "").startswith("image/"):
        raise GitHubFetchError("GitHub did not return an image for the avatar")
    return resp.content


def days_in_year(year: int) -> int:
    return (date(year + 1, 1, 1) - date(year, 1, 1)).days


def iter_year_dates(year: int):
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    while d <= end:
        yield d
        d += timedelta(days=1)
