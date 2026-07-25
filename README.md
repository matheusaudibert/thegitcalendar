# gitcallendar

Backend API that turns a GitHub username into a **yearly commit wallpaper** —
one dot per day of the year, colored by that day's GitHub contribution
intensity, in the style of [thelifecalendar](https://thelifecal-virid.vercel.app/).
Days after today are dimmed (no data yet); today is highlighted.

This repo is **backend only**: it renders the PNG and exposes the raw data
behind it. A separate repo is expected to own the frontend / wallpaper
automation (e.g. an iOS Shortcut or Android widget that calls this API on a
schedule and sets the result as the lock screen).

No GitHub token needed — it reads the same public contribution graph fragment
GitHub renders on profile pages (`github.com/users/{username}/contributions`),
so it only works for a user's **public** contributions.

## Running locally

```bash
python -m venv .venv
.venv/Scripts/activate   # or `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload
```

There's no interactive docs UI (`/docs`/`/redoc`/`/openapi.json` are all
disabled) — this API has one route.

## Endpoints

### `GET /graph`

Renders the wallpaper image. `username` is the only required param — everything
else, including it, is passed as a query param:

| Param | Default | Description |
|---|---|---|
| `username` | _(required)_ | GitHub username to render |
| `year` | current year | Calendar year to render |
| `width` | `1179` | Output width in px — must pair with a matching `height` from the [supported resolutions](#resolutions-iphone); an unrecognized pair silently falls back to `1179x2556`, no error |
| `height` | `2556` | Output height in px; see `width` |
| `shape` | `rounded` | `rounded` (rounded-corner squares, like GitHub), `square` (sharp corners), or `circle` |
| `background` | `github` | Named background preset: `github` (`#0d1117`), `dark` (`#1a1a1a`), or `light` (`#ffffff`). Falls back to `github` if unrecognized, no error |
| `color` | _(none)_ | Named theme for commit levels 1-4: `green`, `blue`, `purple`, `red`, `yellow`, `orange`, `pink`, `white`, `black`. `blue` is GitHub's own colorblind-friendly palette; the rest are custom. Level 0 (no commits) always comes from `background` instead, so it blends in regardless of the color chosen. Falls back to `green` if unrecognized, no error |
| `colors` | _(none)_ | Full manual override: 5 comma-separated hex colors for levels 0-4. Ignored if `color` is set; if neither is set, defaults to green with level 0 from `background`. |
| `future_color` | _(none)_ | Color for days after today; defaults to a shade of `background` |
| `today_color` | _(none)_ | Highlight color for today; defaults to a neutral gray tuned for `background` (dark bg → light gray, light bg → dark gray). Pass `none` to disable |
| `fill_ratio` | `0.82` | Dot/square size relative to its grid cell (0-1) |
| `margin_ratio` | `0.105` | Left/right margin relative to width |
| `top_margin_ratio` | `0.25` | Space above the grid relative to height |
| `footer_gap_ratio` | `0.025` | Gap between grid and footer text relative to height |
| `columns` | `15` | Fixed number of dots/squares per row |
| `footer` | `true` | Show the stats footer |
| `footer_template` | `{commits} commits` | Primary (colored) footer text. Placeholders: `commits`, `percent`, `days_elapsed`, `days_left`, `total_days`, `username`, `year` |
| `footer_secondary_template` | `this year` | Second part of the footer line (same placeholders), drawn right after the primary text in a different color |
| `footer_primary_color` | `39d353` | Primary footer text color |
| `footer_secondary_color` | `8b8b8b` | Secondary footer text color |
| `profile` | `true` | Show the user's GitHub avatar + `@username` below the footer text |

Example:

```
GET /graph?username=torvalds&year=2026&width=1179&height=2556
```

#### Resolutions (iPhone)

The default layout (`columns=15`, i.e. fixed-grid mode) is tuned against a
1179×2556 reference canvas — the grid, footer and avatar are sized in fixed
pixels from that reference and then centered in whatever `width`×`height` you
actually request, instead of stretching. That means the calendar renders at
the *same physical size* on every phone, just with more or less blank margin
around it depending on the screen — exactly how
[thelifecalendar](https://thelifecal-virid.vercel.app/) itself scales across
devices. Pass the matching `width`/`height` pair for the target iPhone:

| Device | `width` | `height` |
|---|---|---|
| iPhone 13 mini | `1080` | `2340` |
| iPhone 13 / 13 Pro / 14 / 14 Pro | `1170` | `2532` |
| iPhone 13 Pro Max / 14 Plus / 14 Pro Max | `1284` | `2778` |
| iPhone 15 / 15 Pro / 16 / 17 (default) | `1179` | `2556` |
| iPhone 15 Plus / 15 Pro Max / 16 Plus | `1290` | `2796` |
| iPhone 16 Pro / 17 Pro | `1206` | `2622` |
| iPhone 16 Pro Max / 17 Pro Max | `1320` | `2868` |

`/graph` is the only route this API exposes for now — more are planned.
Any other path returns a plain-text `Not found. Try /graph` (404) instead of
a JSON 404 body.

## Notes

- Responses for a given `username` + `year` (and avatars) are cached in-memory
  for 1 hour (`GITCALLENDAR_CACHE_TTL` env var to change) to avoid hitting
  github.com on every automation run.
- `/graph` never returns a bare JSON error body — any failure (invalid
  username, user not found, invalid color/param, GitHub fetch/parse error,
  invalid query params) still renders a themed PNG explaining the error, at
  the requested `width`/`height`, using `background`/`color` when they were
  valid. This is so automation expecting an image (e.g. an iOS Shortcut that
  sets the wallpaper on a schedule) never breaks on a failed request — the
  HTTP status code (400/404/422/502) is still set correctly for anything that
  does check it.
- An unrecognized `width`/`height`, `background`, or `color` is *not* treated
  as an error, though — each just silently falls back to its default
  (`1179x2556`, `github`, `green`) and still renders normally.
- 404 is returned if the GitHub username doesn't exist; 502 if GitHub's markup
  can't be parsed (e.g. if they change the contribution graph HTML).
- The avatar comes from `github.com/{username}.png` (GitHub's public avatar
  redirect, no auth needed). If it fails to fetch, the footer just skips it.
- Footer text uses Mona Sans, GitHub's own open-source typeface (SIL OFL,
  bundled in `app/assets/fonts/`, see `LICENSE.txt` there).
- Each `background` preset has its own hand-tuned "empty" (no commits),
  "future", and "today" shades, instead of those staying a fixed dark gray
  regardless of the chosen background.
- The grid/footer/avatar are a constant pixel size regardless of `width`/
  `height` — see [Resolutions (iPhone)](#resolutions-iphone) — rather than
  stretching to fill the requested canvas.
