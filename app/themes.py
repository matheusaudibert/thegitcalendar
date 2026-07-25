"""Color parsing helpers and the built-in default palette.

Every color in the API is fully overridable via query params — these are just
the defaults so a bare request still looks decent.
"""

from __future__ import annotations

DEFAULT_BG = "0d1117"

# Named background presets for the `background` query param, each with its own
# hand-tuned "empty" (level 0 / no commits), "future" (days after today), and
# "today" (highlight) companion shades — otherwise those stayed a fixed dark
# gray no matter the background, which looked wrong on anything but the
# default dark theme.
BACKGROUND_THEMES: dict[str, dict[str, str]] = {
    "github": {"bg": "0d1117", "empty": "161b22", "future": "21262d", "today": "343c47"},
    "dark": {"bg": "1a1a1a", "empty": "242424", "future": "2f2f2f", "today": "404040"},
    "light": {"bg": "ffffff", "empty": "ebedf0", "future": "d8dee4", "today": "d1d1d1"},
}

DEFAULT_WIDTH = 1179
DEFAULT_HEIGHT = 2556

# The exact width/height pairs thelifecalendar itself supports, one per
# distinct iPhone screen resolution (see README's "Resolutions (iPhone)"
# table). Any `width`/`height` pair that isn't one of these — a typo, an
# unsupported device, garbage input — silently falls back to the default
# resolution instead of erroring, same as an unrecognized `background`/`color`.
SUPPORTED_RESOLUTIONS: set[tuple[int, int]] = {
    (1080, 2340),
    (1170, 2532),
    (1284, 2778),
    (DEFAULT_WIDTH, DEFAULT_HEIGHT),
    (1290, 2796),
    (1206, 2622),
    (1320, 2868),
}

DEFAULT_LEVEL_COLORS = ["161b22", "0e4429", "006d32", "26a641", "39d353"]
DEFAULT_FUTURE_COLOR = "21262d"
DEFAULT_TODAY_COLOR = "3c444f"
DEFAULT_FOOTER_PRIMARY = "39d353"
DEFAULT_FOOTER_SECONDARY = "8b8b8b"

# Named color themes for the `color` query param. Level 0 isn't included here
# — it comes from the background theme instead (see BACKGROUND_THEMES), so
# the "no commits" cell always blends with whatever background is picked.
# Blue is GitHub's own colorblind-friendly palette; the rest are ours.
COLOR_THEMES: dict[str, list[str]] = {
    "green": ["0e4429", "006d32", "26a641", "39d353"],
    "blue": ["0a3069", "0969da", "218bff", "54aeff"],
    "purple": ["4c2889", "6e40c9", "8a63d2", "a371f7"],
    "red": ["67060c", "b62324", "da3633", "ff7b72"],
    "yellow": ["3b2900", "744500", "c69026", "e3b341"],
    "orange": ["7a3d00", "a15c00", "d1791b", "ffa657"],
    "pink": ["6e1440", "9e165f", "bf3989", "ff9bce"],
    "white": ["3d444d", "6e7681", "b1bac4", "ffffff"],
    "black": ["1a1a1a", "111111", "080808", "000000"],
}


def parse_hex_color(value: str) -> tuple[int, int, int, int]:
    """Parse 'RGB', 'RRGGBB' or 'RRGGBBAA' (with or without '#') to RGBA."""
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) == 6:
        v += "ff"
    if len(v) != 8:
        raise ValueError(f"Invalid hex color: {value!r}")
    try:
        r, g, b, a = (int(v[i : i + 2], 16) for i in range(0, 8, 2))
    except ValueError as exc:
        raise ValueError(f"Invalid hex color: {value!r}") from exc
    return (r, g, b, a)


def parse_level_colors(value: str) -> list[tuple[int, int, int, int]]:
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 5:
        raise ValueError(
            f"Expected exactly 5 comma-separated colors (levels 0-4), got {len(parts)}"
        )
    return [parse_hex_color(p) for p in parts]
