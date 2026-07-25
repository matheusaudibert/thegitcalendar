"""Fetches and parses a GitHub user's public contribution calendar.

GitHub renders the profile contribution graph as a server-side HTML fragment at
``github.com/users/{username}/contributions``. No authentication is required
because it's the same fragment embedded on public profile pages. We parse the
``<td class="ContributionCalendar-day">`` cells (data-date / data-level) and
match each one to its ``<tool-tip>`` sibling to recover the exact commit count.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

CONTRIBUTIONS_URL = "https://github.com/users/{username}/contributions"
AVATAR_URL = "https://github.com/{username}.png"
USER_AGENT = "gitcallendar/1.0 (+https://github.com/) contribution-graph-reader"
REQUEST_TIMEOUT = 10.0

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
    username: str
    year: int
    days: dict[date, DayData]
    fetched_at: float


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


async def fetch_year_contributions(
    username: str, year: int, *, client: httpx.AsyncClient | None = None
) -> YearContributions:
    """Fetch and parse one calendar year (Jan 1 - Dec 31) of contributions."""
    from_date = date(year, 1, 1)
    to_date = date(year, 12, 31)

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
    try:
        resp = await client.get(
            CONTRIBUTIONS_URL.format(username=username),
            params={"from": from_date.isoformat(), "to": to_date.isoformat()},
            headers={"User-Agent": USER_AGENT},
        )
    finally:
        if owns_client:
            await client.aclose()

    if resp.status_code == 404:
        raise GitHubUserNotFoundError(username)
    if resp.status_code != 200:
        raise GitHubFetchError(
            f"GitHub returned HTTP {resp.status_code} for user '{username}'"
        )

    days = _parse_html(resp.text, username)
    # Keep only the requested calendar year — GitHub pads the grid with a few
    # extra days from adjacent weeks to keep full week columns.
    days = {d: v for d, v in days.items() if from_date <= d <= to_date}

    return YearContributions(
        username=username, year=year, days=days, fetched_at=time.time()
    )


async def fetch_avatar(
    username: str, *, size: int = 200, client: httpx.AsyncClient | None = None
) -> bytes:
    """Fetch a user's public GitHub avatar image (PNG/JPEG bytes)."""
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True)
    try:
        resp = await client.get(
            AVATAR_URL.format(username=username),
            params={"size": size},
            headers={"User-Agent": USER_AGENT},
        )
    finally:
        if owns_client:
            await client.aclose()

    if resp.status_code == 404:
        raise GitHubUserNotFoundError(username)
    if resp.status_code != 200:
        raise GitHubFetchError(
            f"GitHub returned HTTP {resp.status_code} fetching avatar for '{username}'"
        )
    return resp.content


def days_in_year(year: int) -> int:
    return (date(year + 1, 1, 1) - date(year, 1, 1)).days


def iter_year_dates(year: int):
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    while d <= end:
        yield d
        d += timedelta(days=1)
