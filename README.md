# VIEW Conference 2026 — Live Schedule

A mobile-first, filterable schedule app for [VIEW Conference 2026](https://www.viewconference.it/)
(Torino, 12–16 Oct), mirroring the official live program page.

- **Live site**: https://noxvfx.github.io/view2026-schedule/
- **Repo**: https://github.com/noxvfx/view2026-schedule
- Also mirrored (manually, not auto-synced) to a Claude Artifact for preview purposes.

## Architecture at a glance

```
official program page  --curl-->  scripts/refresh.py  --writes-->  index.html  --serves-->  GitHub Pages
   (viewconference.it)                    |
                                  scripts/parse_schedule.py
                                  scripts/template.html (app shell + __SCHEDULE_DATA__ placeholder)
```

The site is fully static — no backend, no database, no accounts. Schedule data
is baked directly into `index.html` as embedded JSON at build time, not
fetched live in the visitor's browser (a browser-side fetch to
viewconference.it would be blocked by CORS anyway, since that site doesn't
opt in to cross-origin requests).

Per-visitor state (favorites, the All Access/Light Pass filter, and the
"have I seen this before" change-detection snapshot) lives entirely in each
visitor's own browser `localStorage` — nothing is shared or synced between
visitors, and none of it is lost when the site rebuilds.

## How it's built

- `scripts/parse_schedule.py` — parses the official live program HTML into
  structured JSON (sessions, days, rooms, speakers, ticket access). Ticket
  access is 3-valued: `light` (Talk/Panel/Keynote, included in Light Pass),
  `all` (All Access only), `separate` (needs an add-on ticket regardless of
  pass — e.g. the Stop-Motion Puppet Lab series).
- `scripts/template.html` — the entire app shell (HTML/CSS/JS) in one file,
  with a `__SCHEDULE_DATA__` placeholder where the parsed JSON gets spliced
  in. **This is the file to edit for any UI/behavior change.**
- `scripts/refresh.py` — orchestrator: fetches the official page, runs the
  parser, splices the result into the template, writes `index.html`. Aborts
  without touching `index.html` if fewer than 30 sessions parse (signals the
  source page's structure changed) or the output size looks wrong.

## How the auto-refresh works

`.github/workflows/refresh.yml` runs `scripts/refresh.py` on a schedule and
commits `index.html` if anything changed:
- Every 12 hours, year-round (`17 */12 * * *` UTC)
- Roughly every 2 hours during the conference itself, Oct 12–16, 8am–8pm
  Rome time (7 explicit UTC cron entries in the workflow) — this is baked
  into the schedule already; nothing needs to be manually switched on/off
  before or after the event.
- On demand: **Actions tab → "Refresh schedule" → Run workflow**, or via the
  in-app "Refresh program data" link (see below).

This is a *scheduled* job, not a change-detector on the source page — it
doesn't know or care whether anything actually changed; it just re-scrapes
blindly at those times. GitHub Pages auto-redeploys on every push to `main`.

**Local manual refresh:**
```
pip install beautifulsoup4 lxml
python scripts/refresh.py
```

**Working on the repo**: `index.html` is a generated file that the bot also
commits to on its own schedule, so a local edit + `git push` will often hit a
conflict. The routine fix: `git pull --rebase origin main`, resolve the
`index.html` conflict by just regenerating it (`python scripts/refresh.py`,
then `git add index.html`, `git rebase --continue`) rather than hand-merging
JSON — the file is fully reproducible from the template + latest scrape, so
there's never anything worth manually merging in it.

## The "Refresh program data" button and its relay

A visitor-facing manual-refresh link lives at the bottom of the page (all
tabs). Since this is a fully static site, that button can't call GitHub's
Actions API directly — doing so would require embedding a GitHub token in
the public page source, which anyone could extract and abuse. Instead:

```
[Refresh button on the page]
        |  POST (no body)
        v
Cloudflare Worker relay  ---holds the GitHub token as an encrypted secret---
 (view2026-refresh-relay)
        |  checks last-triggered time in KV (15 min cooldown, enforced
        |  server-side so it can't be bypassed from the browser)
        |  if allowed: POST to GitHub's workflow_dispatch API
        v
GitHub Actions "Refresh schedule" workflow fires
```

- **Relay source**: `relay/worker.js` in this repo (kept here for reference;
  it isn't deployed by CI — see below).
- **Cloudflare account**: under henrique@noxvfx.com (account id
  `b5b59c748fcecdf7cd97827d376d121d`).
- **Worker URL**: `https://view2026-refresh-relay.noxvfx-view2026.workers.dev`
  — only accepts `POST` requests with `Origin: https://noxvfx.github.io`
  (CORS-gated; any other origin gets a 403).
- **KV namespace**: `VIEW2026_RATELIMIT` (id `05db0802373d4f5397ff0fea36beb5f8`)
  — stores a single key, `lastTriggered`, the epoch-ms timestamp of the last
  successful trigger. This is what makes the 15-minute cooldown real (it's
  server-side state, not a client-side flag someone could clear).
- **GitHub token**: a fine-grained PAT, scoped to *only*
  `noxvfx/view2026-schedule`, with *only* `Actions: read and write`
  permission — it cannot push code, read other repos, or do anything else.
  Stored as an encrypted Cloudflare secret (`GITHUB_TOKEN` binding on the
  Worker), never in this repo or in client-side code.
  **Expires 2026-10-20** (one week after the conference ends) — after that,
  the button will silently stop working until a fresh token is generated
  and re-applied (see "Redeploying the relay" below). This was a deliberate
  choice given the token's narrow scope and the site's limited lifespan.

### Redeploying the relay (e.g. after the token expires, or to change the script)

No `wrangler`/Node.js needed — this environment doesn't have Node installed,
so the relay was deployed directly via Cloudflare's REST API with `curl`.
To redeploy after editing `relay/worker.js`:

```bash
CF_TOKEN='<a Cloudflare API token with Workers Scripts:Edit + Workers KV Storage:Edit>'
GH_RELAY_TOKEN='<a fresh fine-grained GitHub PAT, scoped as described above>'
ACCT='b5b59c748fcecdf7cd97827d376d121d'
KV_ID='05db0802373d4f5397ff0fea36beb5f8'
SCRIPT_NAME='view2026-refresh-relay'

python3 -c "
import json
json.dump({
  'main_module': 'worker.js',
  'compatibility_date': '2024-09-01',
  'bindings': [
    {'type': 'kv_namespace', 'name': 'RATELIMIT', 'namespace_id': '$KV_ID'},
    {'type': 'secret_text', 'name': 'GITHUB_TOKEN', 'text': '$GH_RELAY_TOKEN'}
  ]
}, open('/tmp/relay_metadata.json', 'w'))
"

curl -X PUT "https://api.cloudflare.com/client/v4/accounts/$ACCT/workers/scripts/$SCRIPT_NAME" \
  -H "Authorization: Bearer $CF_TOKEN" \
  -F "metadata=@/tmp/relay_metadata.json;type=application/json" \
  -F "worker.js=@relay/worker.js;type=application/javascript+module"

shred -u /tmp/relay_metadata.json   # it briefly held the raw GitHub token
```

To rotate *just* the GitHub token without touching the script: create a new
fine-grained PAT (same scoping instructions as above — repo access limited
to `noxvfx/view2026-schedule`, Actions: read/write only), then re-run the
same deploy command with the new `GH_RELAY_TOKEN` (the `secret_text` binding
overwrites the old one).

## Change detection (program-updated banner, favorite-change alerts)

The page compares each load's session data against a snapshot saved in
`localStorage` from the visitor's last visit (day/time/room/type/speakers
per session id — deliberately not the always-changing `generatedAt`
timestamp, so this only fires on real content changes, not every scheduled
rebuild). On a real change since last visit:
- A dismissible "Program updated" banner appears.
- Any favorited session whose time/day/room/speakers changed gets a blue
  "Updated since you favorited it" strip on its card.
- Any favorited session removed from the program entirely surfaces as a
  callout at the top of the Favorites tab, with a one-tap dismiss that also
  cleans up the now-defunct favorite from storage.

## Security notes

- All scraped/typed text is HTML-escaped before insertion into the DOM, and
  `href` values (article links, speaker profile links) are validated to be
  `http(s)://` only before being rendered as clickable links — see the `esc()`
  and `safeHref()` helpers in `scripts/template.html`. This guards against a
  compromised or unexpected upstream page injecting markup into every
  visitor's browser via the scrape pipeline.
- CI dependency versions (`beautifulsoup4`, `lxml`) are pinned in
  `.github/workflows/refresh.yml` rather than always pulling latest.
- The scheduled workflow only triggers on `schedule` and `workflow_dispatch`
  — never on `pull_request` — so a malicious fork/PR can't get arbitrary code
  executed in CI. The only way to trigger a run is repo write access (for the
  GitHub-side "Run workflow" button) or the rate-limited public relay above.
- No secrets are committed anywhere in this repo. The only credential in the
  whole system is the narrowly-scoped GitHub PAT held as an encrypted
  Cloudflare secret, described above.
