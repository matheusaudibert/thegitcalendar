# gitcallendar

Backend API that turns a GitHub username into a **yearly commit wallpaper**, one dot per day of the year, colored by that day's GitHub contribution
intensity.

This repo is **backend only**: it renders the PNG and exposes the raw data behind it. 

## Endpoints

### `GET /graph`

Renders the wallpaper image. `username` is the only required param — everything
else, including it, is passed as a query param:

| Param | Default | Description |
|---|---|---|
| `username` | _(required)_ | GitHub username to render |
| `width` | `1179` | Output width in px, must pair with a matching `height` from the [supported resolutions](#resolutions-iphone) |
| `height` | `2556` | Output height in px. |
| `shape` | `rounded` | Shape of the commit: `rounded` (rounded-corner squares, like GitHub), `square` (sharp corners), or `circle`. |
| `background` | `github` | Named background preset: `github` (`#0d1117`), `dark` (`#1a1a1a`), or `light` (`#ffffff`). |
| `color` | _(none)_ | Named theme for commit levels 1-4: `green`, `blue`, `purple`, `red`, `yellow`, `orange`, `pink`, `white`, `black` |

Example:

```
GET /graph?username=torvalds&width=1179&height=2556
```

#### Resolutions (iPhone)

| Device | `width` | `height` |
|---|---|---|
| iPhone 13 mini | `1080` | `2340` |
| iPhone 13 / 13 Pro / 14 / 14 Pro | `1170` | `2532` |
| iPhone 13 Pro Max / 14 Plus / 14 Pro Max | `1284` | `2778` |
| iPhone 15 / 15 Pro / 16 / 17 (default) | `1179` | `2556` |
| iPhone 15 Plus / 15 Pro Max / 16 Plus | `1290` | `2796` |
| iPhone 16 Pro / 17 Pro | `1206` | `2622` |
| iPhone 16 Pro Max / 17 Pro Max | `1320` | `2868` |