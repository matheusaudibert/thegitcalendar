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
# distinct iPhone or Android screen resolution (see README's "Resolutions"
# tables, and lifecalendar_phone_links.txt for the full source list). Any
# `width`/`height` pair that isn't one of these — a typo, an unsupported
# device, garbage input — silently falls back to the default resolution
# instead of erroring, same as an unrecognized `background`/`color`.
SUPPORTED_RESOLUTIONS: set[tuple[int, int]] = {
    (720, 1280),
    (720, 1440),
    (720, 1520),
    (720, 1544),
    (720, 1560),
    (720, 1600),
    (720, 1612),
    (720, 1650),
    (1080, 1920),
    (1840, 2152),
    (1080, 2160),
    (1856, 2160),
    (1812, 2176),
    (1768, 2208),
    (1840, 2208),
    (1080, 2220),
    (1984, 2272),
    (2156, 2272),
    (1080, 2280),
    (2000, 2296),
    (1080, 2340),
    (2156, 2344),
    (1080, 2376),
    (1080, 2388),
    (1080, 2392),
    (1080, 2400),
    (1176, 2400),
    (1080, 2404),
    (1080, 2408),
    (1080, 2412),
    (1084, 2412),
    (1080, 2424),
    (1080, 2448),
    (1080, 2460),
    (1116, 2480),
    (1116, 2484),
    (2268, 2484),
    (2224, 2504),
    (1080, 2520),
    (1170, 2532),
    (DEFAULT_WIDTH, DEFAULT_HEIGHT),
    (1440, 2560),
    (1212, 2616),
    (1206, 2622),
    (1080, 2640),
    (1200, 2652),
    (1200, 2664),
    (1200, 2670),
    (1236, 2676),
    (1216, 2688),
    (1220, 2700),
    (1224, 2700),
    (1228, 2700),
    (1220, 2712),
    (1260, 2720),
    (1240, 2772),
    (1344, 2772),
    (1284, 2778),
    (1264, 2780),
    (1290, 2796),
    (1260, 2800),
    (1280, 2800),
    (1260, 2844),
    (1312, 2848),
    (1280, 2856),
    (1320, 2868),
    (1440, 2880),
    (1440, 2960),
    (1344, 2992),
    (1440, 3040),
    (1440, 3088),
    (1440, 3120),
    (1440, 3168),
    (1440, 3200),
    (1440, 3216),
    (1644, 3840),
    # Mac / desktop screens (landscape: width > height) — auto-fit grid mode
    # kicks in automatically for these in render.py, since the fixed-column
    # portrait layout doesn't fit a wide short canvas.
    (1920, 1080),  # Generic Full HD
    (2560, 1440),  # Generic QHD
    (3840, 2160),  # Generic 4K
    (2560, 1600),  # MacBook Pro 13" (2560x1600) / MacBook Air 13" (older)
    (2560, 1664),  # MacBook Air 13" (M2/M3/M4)
    (2880, 1864),  # MacBook Air 15"
    (3024, 1964),  # MacBook Pro 14"
    (3456, 2234),  # MacBook Pro 16"
    (4480, 2520),  # iMac 24"
    (5120, 2880),  # Studio Display / Generic 5K
    (6016, 3384),  # Pro Display XDR
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
    "black": ["333333", "212121", "121212", "000000"],
}

# The footer's "N commits" normally uses the color theme's brightest shade as
# its accent, but a few background/color pairs make that shade the same as the
# background — white text on the light theme, black text on the dark ones —
# and the text just disappears. For those combos it falls back to the neutral
# gray already used by "this year", so both halves stay readable.
_INVISIBLE_FOOTER_COMBOS: set[tuple[str, str]] = {
    ("light", "white"),
    ("github", "black"),
    ("dark", "black"),
}


def resolve_footer_primary(background: str, color: str | None) -> str:
    """Hex accent for the footer's primary text, given the requested theme."""
    if color is None:
        return DEFAULT_FOOTER_PRIMARY
    if (background, color) in _INVISIBLE_FOOTER_COMBOS:
        return DEFAULT_FOOTER_SECONDARY
    return COLOR_THEMES[color][-1]


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
