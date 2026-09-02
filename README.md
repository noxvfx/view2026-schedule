# VIEW Conference 2026 — Live Schedule

A mobile-first, filterable schedule app for [VIEW Conference 2026](https://www.viewconference.it/)
(Torino, 12–16 Oct), mirroring the official live program page.

Hosted on GitHub Pages, kept in sync with the official schedule by a scheduled
GitHub Action (`.github/workflows/refresh.yml`) that re-scrapes and rebuilds
`index.html` every 12 hours normally, and roughly every 2 hours during the
conference days (Oct 12–16).

## How it's built

- `scripts/parse_schedule.py` — parses the official live program HTML into
  structured JSON (sessions, days, rooms, speakers, ticket access).
- `scripts/template.html` — the app shell (HTML/CSS/JS), with a
  `__SCHEDULE_DATA__` placeholder for the parsed JSON.
- `scripts/refresh.py` — fetches the official page, runs the parser, splices
  the result into the template, and writes `index.html`.

## Manual refresh

Trigger a refresh on demand from the **Actions** tab on GitHub → "Refresh
schedule" → "Run workflow". Or locally:

```
pip install beautifulsoup4 lxml
python scripts/refresh.py
```
