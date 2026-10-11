"""gitcalendar backend: turns a GitHub username into a yearly commit-dot
wallpaper image (and the raw data behind it). Pure backend — no UI here; a
separate frontend/automation repo is expected to call this API.
"""

from __future__ import annotations

import re
from typing import Literal

from dotenv import load_dotenv

# Local dev reads GITHUB_TOKEN from .env; in production (Vercel) the real
# environment variable is used and this is a no-op.
load_dotenv()

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .cache import DEFAULT_TTL_SECONDS, TTLCache
from .clock import today as clock_today
from .github_client import (
    GitHubFetchError,
    GitHubUserNotFoundError,
    ProfileData,
    decode_profile,
    encode_profile,
    fetch_profile,
)
from .shared_cache import SharedCache
from .render import WallpaperOptions, render_error_png, render_wallpaper_png
from .themes import (
    BACKGROUND_THEMES,
    COLOR_THEMES,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    MAX_DIMENSION,
    MIN_DIMENSION,
    parse_hex_color,
    parse_level_colors,
    resolve_footer_primary,
)

app = FastAPI(
    title="gitcalendar",
    description=(
        "Generates a yearly GitHub-commit wallpaper image for a given username, "
        "in the style of thelifecalendar — one dot per day, colored by that "
        "day's commit intensity. Backend only, single route: /graph."
    ),
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Two cache layers in front of GitHub, both keyed only by user + year — never
# by the rendering options — so every personalization of the same profile
# reuses one fetch: an in-process cache (free, but per serverless instance)
# backed by Redis (shared across instances; skipped if not configured).
_cache: TTLCache[ProfileData] = TTLCache()
_shared_cache: SharedCache[ProfileData] = SharedCache.from_env(
    ttl_seconds=DEFAULT_TTL_SECONDS, encode=encode_profile, decode=decode_profile
)

USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


def _validate_username(username: str) -> str:
    if not USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail="Invalid GitHub username")
    return username


async def _get_profile(username: str, year: int) -> ProfileData:
    # The avatar + @username row is a required part of the wallpaper, so a
    # failed avatar fetch fails the whole request (as an error image) rather
    # than silently rendering without it.
    key = f"profile:{username.lower()}:{year}"
    try:
        return await _cache.get_or_fetch(
            key,
            lambda: _shared_cache.get_or_fetch(key, lambda: fetch_profile(username, year)),
        )
    except GitHubUserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GitHubFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _resolve_dimension(raw: str | None, default: int) -> int:
    """Any pixel size goes — there's no list of allowed resolutions. Values
    outside the safe range are clamped to it, and missing or non-numeric input
    falls back to the default (no error), same as an unrecognized
    `background`/`color`.
    """
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return max(MIN_DIMENSION, min(value, MAX_DIMENSION))


def _resolve_resolution(width_raw: str | None, height_raw: str | None) -> tuple[int, int]:
    """Resolves the requested canvas size; the two sides are independent, so
    passing only one keeps the default for the other.
    """
    return (
        _resolve_dimension(width_raw, DEFAULT_WIDTH),
        _resolve_dimension(height_raw, DEFAULT_HEIGHT),
    )


def _error_image_response(
    status_code: int,
    message: str,
    *,
    width: int = 1179,
    height: int = 2556,
    background: str = "github",
    color: str | None = None,
) -> Response:
    """Renders any wallpaper-endpoint failure as a themed PNG instead of a
    JSON body — automation that expects an image (e.g. an iOS Shortcut that
    sets the result as the lock screen on a schedule) still gets one, and it
    still honors `background`/`color` when those were valid.
    """
    if background not in BACKGROUND_THEMES:
        background = "github"
    theme = BACKGROUND_THEMES[background]
    accent_hex = resolve_footer_primary(background, color if color in COLOR_THEMES else None)
    png_bytes = render_error_png(
        width=width,
        height=height,
        bg_color=parse_hex_color(theme["bg"]),
        accent_color=parse_hex_color(accent_hex),
        message=message,
    )
    return Response(content=png_bytes, media_type="image/png", status_code=status_code)


@app.exception_handler(RequestValidationError)
async def _wallpaper_validation_error_handler(request: Request, exc: RequestValidationError):
    if request.url.path != "/graph":
        return await request_validation_exception_handler(request, exc)

    qp = request.query_params
    width, height = _resolve_resolution(qp.get("width"), qp.get("height"))
    background = qp.get("background", "github")
    if background not in BACKGROUND_THEMES:
        background = "github"
    color = qp.get("color")
    if color not in COLOR_THEMES:
        color = None

    return _error_image_response(
        422,
        "Invalid request parameters",
        width=width,
        height=height,
        background=background,
        color=color,
    )


@app.exception_handler(StarletteHTTPException)
async def _not_found_handler(request: Request, exc: StarletteHTTPException):
    # Only for routes that don't exist at all (Starlette's own routing 404,
    # which always carries its default "Not Found" detail) — anything we
    # raise ourselves (e.g. a 404 for a missing GitHub user) has a specific
    # detail message and keeps its normal JSON/image response untouched.
    if exc.status_code == 404 and exc.detail in (None, "Not Found"):
        return PlainTextResponse("Not found. Try /graph", status_code=404)
    return await http_exception_handler(request, exc)


@app.get("/graph")
async def get_wallpaper(
    username: str = Query(..., description="GitHub username to render"),
    width: str | None = Query(
        None,
        description=f"Output width in px — any value from {MIN_DIMENSION} to {MAX_DIMENSION}, "
        "not just known device resolutions. Out-of-range values are clamped and non-numeric "
        f"input falls back to {DEFAULT_WIDTH} instead of erroring",
    ),
    height: str | None = Query(
        None,
        description=f"Output height in px; see `width` (defaults to {DEFAULT_HEIGHT})",
    ),
    shape: Literal["rounded", "square", "circle"] = Query(
        "rounded", description="Dot style: 'rounded' (default, rounded-corner squares like GitHub), 'square' (sharp corners), or 'circle'"
    ),
    background: str = Query(
        "github",
        description="Named background preset: github, dark, or light. Falls back to github if unrecognized",
    ),
    color: str | None = Query(
        None,
        description="Named color theme for levels 1-4: green, blue, purple, red, yellow, orange, "
        "pink, white, black. Falls back to green if unrecognized",
    ),
) -> Response:
    width_px, height_px = _resolve_resolution(width, height)
    if background not in BACKGROUND_THEMES:
        background = "github"
    if color is not None and color not in COLOR_THEMES:
        color = None

    try:
        username = _validate_username(username)

        theme = BACKGROUND_THEMES[background]
        resolved_levels = ",".join([theme["empty"], *COLOR_THEMES[color or "green"]])
        resolved_footer_primary = resolve_footer_primary(background, color)

        try:
            options = WallpaperOptions(
                width=width_px,
                height=height_px,
                shape=shape,
                bg_color=parse_hex_color(theme["bg"]),
                level_colors=parse_level_colors(resolved_levels),
                future_color=parse_hex_color(theme["future"]),
                today_color=parse_hex_color(theme["today"]),
                footer_primary_color=parse_hex_color(resolved_footer_primary),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        profile = await _get_profile(username, clock_today().year)
        png_bytes = render_wallpaper_png(profile.contributions, options, profile.avatar)

        return Response(
            content=png_bytes,
            media_type="image/png",
            # s-maxage lets Vercel's CDN serve repeat hits of the exact same
            # URL without running the function at all.
            headers={"Cache-Control": "public, max-age=3600, s-maxage=3600"},
        )
    except HTTPException as exc:
        # Always hand back an image, even on failure, so automation that
        # expects one (e.g. an iOS Shortcut setting the wallpaper on a
        # schedule) never breaks on a bare JSON error body — still themed
        # with whatever `background`/`color` was requested.
        return _error_image_response(
            exc.status_code,
            str(exc.detail),
            width=width_px,
            height=height_px,
            background=background,
            color=color,
        )
