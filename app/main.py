"""gitcallendar backend: turns a GitHub username into a yearly commit-dot
wallpaper image (and the raw data behind it). Pure backend — no UI here; a
separate frontend/automation repo is expected to call this API.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .cache import TTLCache
from .github_client import (
    GitHubFetchError,
    GitHubUserNotFoundError,
    YearContributions,
    fetch_avatar,
    fetch_year_contributions,
)
from .render import WallpaperOptions, render_error_png, render_wallpaper_png
from .themes import (
    BACKGROUND_THEMES,
    COLOR_THEMES,
    DEFAULT_FOOTER_PRIMARY,
    DEFAULT_FOOTER_SECONDARY,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    SUPPORTED_RESOLUTIONS,
    parse_hex_color,
    parse_level_colors,
)

app = FastAPI(
    title="gitcallendar",
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

_cache: TTLCache[YearContributions] = TTLCache()
_avatar_cache: TTLCache[bytes] = TTLCache()

USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


def _validate_username(username: str) -> str:
    if not USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail="Invalid GitHub username")
    return username


async def _get_year_contributions(username: str, year: int) -> YearContributions:
    key = f"{username.lower()}:{year}"
    try:
        return await _cache.get_or_fetch(
            key, lambda: fetch_year_contributions(username, year)
        )
    except GitHubUserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GitHubFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _resolve_resolution(width_raw: str | None, height_raw: str | None) -> tuple[int, int]:
    """Snaps to a supported width/height pair, falling back to the default
    resolution (no error) for anything unrecognized — a typo, an unsupported
    device, non-numeric input, or just one of the two missing.
    """
    try:
        width = int(width_raw) if width_raw is not None else DEFAULT_WIDTH
        height = int(height_raw) if height_raw is not None else DEFAULT_HEIGHT
    except (TypeError, ValueError):
        return DEFAULT_WIDTH, DEFAULT_HEIGHT
    if (width, height) not in SUPPORTED_RESOLUTIONS:
        return DEFAULT_WIDTH, DEFAULT_HEIGHT
    return width, height


async def _get_avatar(username: str) -> bytes | None:
    try:
        return await _avatar_cache.get_or_fetch(
            username.lower(), lambda: fetch_avatar(username)
        )
    except (GitHubUserNotFoundError, GitHubFetchError):
        return None


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
    theme = BACKGROUND_THEMES.get(background, BACKGROUND_THEMES["github"])
    accent_hex = COLOR_THEMES[color][-1] if color in COLOR_THEMES else DEFAULT_FOOTER_PRIMARY
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
    year: int = Query(default_factory=lambda: date.today().year),
    width: str | None = Query(
        None,
        description="Output width in px — must pair with a matching `height` from the supported "
        "resolutions (see README); an unrecognized pair silently falls back to the default "
        f"{DEFAULT_WIDTH}x{DEFAULT_HEIGHT} instead of erroring",
    ),
    height: str | None = Query(None, description="Output height in px; see `width`"),
    shape: Literal["rounded", "square", "circle"] = Query(
        "rounded", description="Dot style: 'rounded' (default, rounded-corner squares like GitHub), 'square' (sharp corners), or 'circle'"
    ),
    background: str = Query(
        "github",
        description="Named background preset: github, dark, or light. Falls back to github if unrecognized",
    ),
    colors: str | None = Query(
        None,
        description="5 comma-separated hex colors for contribution levels 0-4 — a full manual "
        "override. If omitted, level 0 follows the `background` theme and levels 1-4 follow "
        "`color` (or green). Ignored if `color` is set.",
    ),
    color: str | None = Query(
        None,
        description="Named color theme for levels 1-4: green, blue, purple, red, yellow, orange, "
        "pink, white, black. Falls back to green if unrecognized; overrides `colors`",
    ),
    future_color: str | None = Query(
        None, description="Color for days after today; defaults to the `background` theme's shade"
    ),
    today_color: str | None = Query(
        None,
        description="Highlight color for today; defaults to a shade that matches `background`. Pass 'none' to disable",
    ),
    fill_ratio: float = Query(0.82, gt=0.05, le=1.0, description="Dot/square size relative to its cell"),
    margin_ratio: float = Query(0.105, ge=0.0, le=0.3, description="Left/right margin relative to width"),
    top_margin_ratio: float = Query(0.25, ge=0.0, le=0.6, description="Space above the grid relative to height"),
    footer_gap_ratio: float = Query(0.025, ge=0.0, le=0.2, description="Gap between grid and footer text relative to height"),
    columns: int = Query(15, ge=1, le=366, description="Fixed number of dots/squares per row"),
    footer: bool = Query(True, description="Show the stats footer text"),
    footer_template: str = Query("{commits} commits"),
    footer_secondary_template: str = Query("this year"),
    footer_primary_color: str | None = Query(
        None, description="Primary footer text color; defaults to the theme's brightest level color, or green"
    ),
    footer_secondary_color: str = Query(DEFAULT_FOOTER_SECONDARY),
    profile: bool = Query(True, description="Show the avatar + @username below the footer text"),
) -> Response:
    width_px, height_px = _resolve_resolution(width, height)
    if background not in BACKGROUND_THEMES:
        background = "github"
    if color is not None and color not in COLOR_THEMES:
        color = None

    try:
        username = _validate_username(username)

        theme = BACKGROUND_THEMES[background]
        resolved_bg = theme["bg"]
        resolved_empty = theme["empty"]
        resolved_future_default = theme["future"]
        resolved_today_default = theme["today"]

        if colors is not None:
            resolved_levels = colors
        else:
            resolved_levels = ",".join([resolved_empty, *COLOR_THEMES[color or "green"]])

        if footer_primary_color is not None:
            resolved_footer_primary = footer_primary_color
        elif color:
            resolved_footer_primary = COLOR_THEMES[color][-1]
        else:
            resolved_footer_primary = DEFAULT_FOOTER_PRIMARY

        resolved_future = future_color if future_color is not None else resolved_future_default
        resolved_today = today_color if today_color is not None else resolved_today_default

        try:
            options = WallpaperOptions(
                width=width_px,
                height=height_px,
                shape=shape,
                bg_color=parse_hex_color(resolved_bg),
                level_colors=parse_level_colors(resolved_levels),
                future_color=parse_hex_color(resolved_future),
                today_color=(
                    None
                    if today_color is not None and today_color.lower() == "none"
                    else parse_hex_color(resolved_today)
                ),
                fill_ratio=fill_ratio,
                margin_ratio=margin_ratio,
                top_margin_ratio=top_margin_ratio,
                footer_gap_ratio=footer_gap_ratio,
                columns=columns,
                show_footer=footer,
                footer_template=footer_template,
                footer_secondary_template=footer_secondary_template,
                footer_primary_color=parse_hex_color(resolved_footer_primary),
                footer_secondary_color=parse_hex_color(footer_secondary_color),
                show_profile=profile,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        contrib = await _get_year_contributions(username, year)
        avatar_bytes = await _get_avatar(username) if profile else None
        png_bytes = render_wallpaper_png(contrib, options, avatar_bytes)

        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=3600"},
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
