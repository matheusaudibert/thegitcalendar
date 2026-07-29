# [gitcallendar](https://thegitcallendar.vercel.app/)

Backend API that turns a GitHub username into a **yearly commit wallpaper**, one commit dot per day of the year, colored by that day's GitHub contribution
intensity.

This repo is **backend only**: it renders the image. 

## Endpoints

### `GET /graph`

Renders the wallpaper image. `username` is the only required param, everything else, including it, is passed as a query param:

| Param | Default | Description |
|---|---|---|
| `username` | _(required)_ | GitHub username to render |
| `height` | `2556` | Output height in px. |
| `width` | `1179` | Output width in px. |
| `shape` | `rounded` | Shape of the commit: `rounded` (rounded-corner squares, like GitHub), `square` (sharp corners), or `circle`. |
| `background` | `github` | Named background preset: `github` (`#0d1117`), `dark` (`#1a1a1a`), or `light` (`#ffffff`). |
| `color` | _(none)_ | Named theme for commit levels 1-4: `green`, `blue`, `purple`, `red`, `yellow`, `orange`, `pink`, `white`, `black` |

Example:

```
GET https://gitcallendar-image.vercel.app/graph?username=matheusaudibert
```

Example with all params: 
```
GET https://gitcallendar-image.vercel.app/graph?username=matheusaudibert&background=github&color=green&shape=rounded&height=2556&width=1179
```

#### Resolutions

Supports multiple resolutions, for both iPhone and Android devices. All available resolutions are listed in [RESOLUTIONS.md](RESOLUTIONS.md).

#### Support
If you're using this repo, feel free to show support and give this repo a ⭐ star! It means a lot, thank you :)
