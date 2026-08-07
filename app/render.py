"""Draws the yearly commit-dot wallpaper with Pillow.

Layout mirrors thelifecalendar's approach: N dots for N days, auto-arranged
into a grid that best fills the requested (width, height) canvas, rather than
a fixed 7-column week grid. Each dot is colored by that day's GitHub
contribution intensity; days after "today" are rendered dim since they have
no data yet.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .clock import today as clock_today
from .github_client import YearContributions, days_in_year
from .themes import (
    DEFAULT_BG,
    DEFAULT_FOOTER_PRIMARY,
    DEFAULT_FOOTER_SECONDARY,
    DEFAULT_FUTURE_COLOR,
    DEFAULT_LEVEL_COLORS,
    DEFAULT_TODAY_COLOR,
    parse_hex_color,
    parse_level_colors,
)

RGBA = tuple[int, int, int, int]

# All layout ratios (margins, dot size, font sizes, gaps...) are tuned against
# this reference canvas. In fixed-column mode we size everything from these
# constants rather than the live width/height, then center the resulting
# fixed-pixel block in whatever canvas is actually requested — so an iPhone
# 15 Pro Max wallpaper shows the exact same size grid as an iPhone 15 one,
# just with more blank margin around it, matching how thelifecalendar itself
# scales across device resolutions (confirmed by measuring their own
# per-resolution reference renders rather than stretching the design).
_REFERENCE_WIDTH = 1179
_REFERENCE_HEIGHT = 2556

_FONTS_DIR = Path(__file__).parent / "assets" / "fonts"
_REGULAR_FONT_CANDIDATES = [
    str(_FONTS_DIR / "MonaSans-Regular.ttf"),
    "arial.ttf",
    "DejaVuSans.ttf",
    "LiberationSans-Regular.ttf",
]
_BOLD_FONT_CANDIDATES = [
    str(_FONTS_DIR / "MonaSans-SemiBold.ttf"),
    "arialbd.ttf",
    "DejaVuSans-Bold.ttf",
    "LiberationSans-Bold.ttf",
]


@dataclass
class WallpaperOptions:
    width: int = 1179
    height: int = 2556
    shape: str = "rounded"  # "rounded" | "square" | "circle"
    bg_color: RGBA = field(default_factory=lambda: parse_hex_color(DEFAULT_BG))
    level_colors: list[RGBA] = field(
        default_factory=lambda: parse_level_colors(",".join(DEFAULT_LEVEL_COLORS))
    )
    future_color: RGBA = field(default_factory=lambda: parse_hex_color(DEFAULT_FUTURE_COLOR))
    today_color: RGBA | None = field(default_factory=lambda: parse_hex_color(DEFAULT_TODAY_COLOR))
    fill_ratio: float = 0.82
    margin_ratio: float = 0.105
    top_margin_ratio: float = 0.25
    # Footer ratios below are all relative to `cell` (the actual rendered dot
    # size), not canvas width/height — so text and avatar stay proportional to
    # the grid itself in both fixed-column (portrait) and auto-fit (landscape)
    # modes, instead of ballooning when the grid doesn't fill the canvas.
    footer_font_ratio: float = 0.684
    footer_gap_ratio: float = 1.03
    columns: int | None = 15
    show_footer: bool = True
    footer_template: str = "{commits} commits"
    footer_secondary_template: str = "this year"
    footer_primary_color: RGBA = field(
        default_factory=lambda: parse_hex_color(DEFAULT_FOOTER_PRIMARY)
    )
    footer_secondary_color: RGBA = field(
        default_factory=lambda: parse_hex_color(DEFAULT_FOOTER_SECONDARY)
    )
    show_profile: bool = True
    avatar_size_ratio: float = 0.854
    profile_font_ratio: float = 0.494
    profile_gap_ratio: float = 0.741
    profile_row_gap_ratio: float = 0.19


def _best_grid(total: int, usable_w: float, usable_h: float) -> tuple[int, int, float]:
    """Pick (columns, rows, cell_size) that best fills usable_w x usable_h."""
    aspect = usable_w / usable_h
    guess = max(1, round(math.sqrt(total * aspect)))

    best = None
    for columns in range(max(1, guess - 3), min(total, guess + 3) + 1):
        rows = math.ceil(total / columns)
        cell = min(usable_w / columns, usable_h / rows)
        if best is None or cell > best[2]:
            best = (columns, rows, cell)
    assert best is not None
    return best


def _load_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    for name in (_BOLD_FONT_CANDIDATES if bold else _REGULAR_FONT_CANDIDATES):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _circular(image: Image.Image, diameter: int) -> Image.Image:
    image = image.convert("RGBA").resize((diameter, diameter), Image.LANCZOS)
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter, diameter), fill=255)
    image.putalpha(mask)
    return image


def render_wallpaper(
    contrib: YearContributions,
    options: WallpaperOptions,
    avatar_bytes: bytes | None = None,
) -> Image.Image:
    year = contrib.year
    total_days = days_in_year(year)
    today = clock_today()

    img = Image.new("RGBA", (options.width, options.height), options.bg_color)
    draw = ImageDraw.Draw(img)

    if options.columns and options.height >= options.width:
        # Fixed-column mode (the default): size the grid from the reference
        # canvas, not the live one, so it stays a constant pixel size across
        # resolutions, then center that fixed block in the live canvas.
        # Only applies to portrait/square canvases — the reference canvas is
        # portrait, so centering its fixed block in a wide landscape (Mac)
        # canvas would push it off the top instead of filling the screen.
        ref_margin_x = _REFERENCE_WIDTH * options.margin_ratio
        ref_usable_w = _REFERENCE_WIDTH - 2 * ref_margin_x
        columns = options.columns
        rows = math.ceil(total_days / columns)
        cell = ref_usable_w / columns
        grid_w = cell * columns
        grid_h = cell * rows
        offset_x = (options.width - grid_w) / 2
        offset_y = _REFERENCE_HEIGHT * options.top_margin_ratio + (
            options.height - _REFERENCE_HEIGHT
        ) / 2
    else:
        # Auto-fit mode: pack the grid into whatever live canvas it's given,
        # instead of holding it to a fixed pixel size. Used for landscape
        # (Mac/desktop) canvases — margins are symmetric and the whole
        # grid+footer block is vertically centered, unlike the portrait
        # layout which anchors near the top to clear a lock-screen clock.
        margin_x = options.width * options.margin_ratio
        margin_y = options.height * options.margin_ratio
        usable_w = options.width - 2 * margin_x
        footer_reserve = options.height * 0.14 if options.show_footer else 0
        usable_h = options.height - 2 * margin_y - footer_reserve
        columns, rows, cell = _best_grid(total_days, usable_w, usable_h)
        grid_w = cell * columns
        grid_h = cell * rows
        offset_x = margin_x + (usable_w - grid_w) / 2
        # Footer height estimate (gap + commits line + gap + avatar row) for
        # centering purposes only — a few px off if there's no avatar is fine.
        footer_h = cell * 3.4 if options.show_footer else 0
        offset_y = (options.height - grid_h - footer_h) / 2

    radius = cell * options.fill_ratio / 2
    commits_so_far = 0

    for i in range(total_days):
        day = date(year, 1, 1) + timedelta(days=i)
        row, col = divmod(i, columns)
        cx = offset_x + col * cell + cell / 2
        cy = offset_y + row * cell + cell / 2

        is_today = day == today
        is_future = day > today

        if is_future:
            color = options.future_color
        else:
            data = contrib.days.get(day)
            level = data.level if data else 0
            level = max(0, min(level, len(options.level_colors) - 1))
            color = options.level_colors[level]
            if data and data.count:
                commits_so_far += data.count

        if is_today and options.today_color is not None:
            color = options.today_color

        bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
        if options.shape == "circle":
            draw.ellipse(bbox, fill=color)
        elif options.shape == "square":
            draw.rectangle(bbox, fill=color)
        else:
            draw.rounded_rectangle(bbox, radius=radius * 0.4, fill=color)

    if options.show_footer:
        days_elapsed = min(max((today - date(year, 1, 1)).days + 1, 0), total_days)
        percent = round(days_elapsed / total_days * 100)
        format_args = dict(
            commits=commits_so_far,
            percent=percent,
            days_elapsed=days_elapsed,
            days_left=total_days - days_elapsed,
            total_days=total_days,
            username=contrib.username,
            year=year,
        )
        primary_text = options.footer_template.format(**format_args)
        secondary_text = (
            options.footer_secondary_template.format(**format_args)
            if options.footer_secondary_template
            else ""
        )

        primary_font = _load_font(max(10, round(cell * options.footer_font_ratio)), bold=False)
        secondary_font = primary_font

        line_top = offset_y + grid_h + cell * options.footer_gap_ratio - 3
        part_gap = draw.textlength(" ", font=primary_font)

        primary_bbox = draw.textbbox((0, 0), primary_text, font=primary_font)
        primary_w = primary_bbox[2] - primary_bbox[0]
        secondary_bbox = (
            draw.textbbox((0, 0), secondary_text, font=secondary_font)
            if secondary_text
            else (0, 0, 0, 0)
        )
        secondary_w = secondary_bbox[2] - secondary_bbox[0] if secondary_text else 0

        total_w = primary_w + (part_gap + secondary_w if secondary_text else 0)
        # Both parts share one font, so drawing them at the same y (using PIL's
        # default ascender-based anchor) keeps them on the same line — no need
        # to align via each string's own bbox, which varies with descenders.
        cursor_x = options.width / 2 - total_w / 2
        draw.text(
            (cursor_x - primary_bbox[0], line_top),
            primary_text,
            font=primary_font,
            fill=options.footer_primary_color,
        )
        if secondary_text:
            cursor_x += primary_w + part_gap
            draw.text(
                (cursor_x - secondary_bbox[0], line_top),
                secondary_text,
                font=secondary_font,
                fill=options.footer_secondary_color,
            )

        if options.show_profile and avatar_bytes:
            primary_h = primary_bbox[3] - primary_bbox[1]
            avatar_diameter = round(cell * options.avatar_size_ratio)
            avatar = _circular(Image.open(io.BytesIO(avatar_bytes)), avatar_diameter)

            username_text = f"@{contrib.username}"
            profile_font = _load_font(max(10, round(cell * options.profile_font_ratio)))
            username_bbox = draw.textbbox((0, 0), username_text, font=profile_font)
            username_w = username_bbox[2] - username_bbox[0]
            username_h = username_bbox[3] - username_bbox[1]

            profile_gap = cell * options.profile_row_gap_ratio
            row_w = avatar_diameter + profile_gap + username_w
            row_top = line_top + primary_h + cell * options.profile_gap_ratio
            row_x = options.width / 2 - row_w / 2

            img.paste(avatar, (round(row_x), round(row_top)), avatar)
            text_y = row_top + (avatar_diameter - username_h) / 2 - username_bbox[1]
            draw.text(
                (row_x + avatar_diameter + profile_gap - username_bbox[0], text_y),
                username_text,
                font=profile_font,
                fill=options.footer_secondary_color,
            )

    return img.convert("RGB")


def render_wallpaper_png(
    contrib: YearContributions,
    options: WallpaperOptions,
    avatar_bytes: bytes | None = None,
) -> bytes:
    img = render_wallpaper(contrib, options, avatar_bytes)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    center_x: float,
    top_y: float,
    max_width: float,
    fill: RGBA,
) -> float:
    """Draws centered, word-wrapped text; returns the y just below it."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)

    line_height = font.size * 1.35
    y = top_y
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        draw.text((center_x - line_w / 2 - bbox[0], y - bbox[1]), line, font=font, fill=fill)
        y += line_height
    return y


def render_error_png(
    *,
    width: int,
    height: int,
    bg_color: RGBA,
    accent_color: RGBA,
    message: str,
    detail: str | None = None,
) -> bytes:
    """Renders a themed error placeholder instead of a bare JSON error body,
    so automation expecting an image (e.g. an iOS Shortcut setting the
    wallpaper on a schedule) always gets one, even when the request fails —
    still using the requested `background`/`color` theme where available.
    """
    img = Image.new("RGBA", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    icon_d = width * 0.16
    cx, cy = width / 2, height * 0.42
    stroke = max(2, round(icon_d * 0.055))
    draw.ellipse(
        (cx - icon_d / 2, cy - icon_d / 2, cx + icon_d / 2, cy + icon_d / 2),
        outline=accent_color,
        width=stroke,
    )
    bar_w = max(2, round(icon_d * 0.09))
    draw.rounded_rectangle(
        (cx - bar_w / 2, cy - icon_d * 0.26, cx + bar_w / 2, cy + icon_d * 0.06),
        radius=bar_w / 2,
        fill=accent_color,
    )
    dot_r = bar_w * 0.85
    draw.ellipse(
        (cx - dot_r, cy + icon_d * 0.18 - dot_r, cx + dot_r, cy + icon_d * 0.18 + dot_r),
        fill=accent_color,
    )

    title_font = _load_font(max(14, round(width * 0.05)), bold=True)
    detail_font = _load_font(max(10, round(width * 0.032)))
    max_text_w = width * 0.78

    y = _draw_wrapped_text(draw, message, title_font, width / 2, cy + icon_d * 0.75, max_text_w, accent_color)
    if detail:
        _draw_wrapped_text(
            draw, detail, detail_font, width / 2, y + height * 0.015, max_text_w, (139, 139, 139, 255)
        )

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
