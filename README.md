# World Cup 2026 Tracker → worldcup.sflorida.studio

A self-updating static site that tracks the 2026 FIFA World Cup. Pick **any
team (or teams)** and see their live group situation, their projected **road to
the final**, and **who they could face** at each knockout round based on the
current standings — plus full group tables and the complete bracket.

- **Live data:** [`openfootball/worldcup.json`](https://github.com/openfootball/worldcup.json) — public domain, no API key, updated from official results.
- **Hosting:** Cloudflare Pages (Git integration) on `worldcup.sflorida.studio`.
- **Auto-update:** a GitHub Action refreshes the data and rebuilds the site once a day; Pages redeploys on the push.

---

## How it works

```
wc/            the engine (pure Python, standard library only)
  config.py    data source, tournament meta, default watchlist, team colors
  data.py      fetch / cache / load the live feed
  standings.py group tables, FIFA tiebreakers, clinch/elimination detection
  bracket.py   resolve bracket slots (1C, 2F, 3A/B/C/D/F, W76…) + path projection
  render.py    build the multi-page static site
  flags.py / util.py   emoji flags, slugs, per-team accent colors
scripts/
  fetch.py     refresh the cached feed only
  build.py     render public/ from the cache  (--fetch to refresh first)
  update.py    refresh data AND rebuild  ← the "update on command" entry point
data/          cached copy of the live feed (committed so builds are reproducible)
public/        the generated site that Cloudflare Pages serves
.github/workflows/update.yml   the daily refresh job
```

The bracket and projections are **fully data-driven**: the feed encodes knockout
participants as slots (`2C` = Group C runner-up, `3A/B/C/D/F` = a third-placed
team, `W76` = winner of match 76). As results land, those slots resolve to real
teams automatically — no hand-editing.

## Update the site on command

```bash
python3 scripts/update.py     # pull the latest results and rebuild everything
```

Or just rebuild from the cached data (no network):

```bash
python3 scripts/build.py
```

## Preview locally

```bash
python3 scripts/build.py
python3 -m http.server 8765 --directory public
# open http://localhost:8765
```

## Deploy to Cloudflare Pages (one-time, in the dashboard)

1. Create a GitHub repo and push this project.
2. Cloudflare dashboard → **Workers & Pages → Create → Pages → Connect to Git**, and select the repo.
3. Build settings:
   - **Framework preset:** None
   - **Build command:** *(leave empty)* — the site is pre-built and committed to `public/`
   - **Build output directory:** `public`
4. **Save and Deploy.**
5. In the new Pages project → **Custom domains → Set up a domain →** `worldcup.sflorida.studio` (one click, since `sflorida.studio` is already on Cloudflare).

After that, every push (including the update Action) auto-deploys. The
`functions/` directory is picked up automatically — `POST /api/refresh` becomes
live with no extra config.

> Prefer Cloudflare to build instead of serving the committed output? Set the
> build command to `python3 scripts/build.py` — Python is available in the Pages
> build image.

## Updates: end-of-match + a manual button

**How "update at the end of each match" works.** `.github/workflows/update.yml`
polls the live feed **every ~15 min during the daily match window** (plus a daily
safety run). It rebuilds the site but **commits only when results actually
changed** (`scripts/update.py` keeps the timestamp stable when nothing moved, so
an unchanged poll regenerates byte-identical files and produces no commit). Net
effect: the site republishes within ~15 min of a result landing in the feed, and
**each real result is exactly one Cloudflare deploy** — staying far under the free
tier's 500 deploys/month. (Latency is bounded by the openfootball feed, which
posts results a few minutes after full-time.)

> Tip: a public repo gets unlimited Actions minutes — tighten the cron to `*/5`
> for faster updates. On a private repo the 15-min window stays within the free
> 2,000 min/month.

**The "Update now" button.** The footer button triggers the same workflow
immediately via a Cloudflare Pages Function (`functions/api/refresh.js`) that
holds a GitHub token server-side (never exposed to the browser). To enable it:

1. Create a **fine-grained Personal Access Token** (GitHub → Settings → Developer
   settings → Fine-grained tokens) scoped to this repo with **Actions: Read and
   write**.
2. In the Cloudflare **Pages project → Settings → Environment variables**, add:
   - `GH_OWNER` — your GitHub username/org
   - `GH_REPO` — the repo name (e.g. `worldcup2026`)
   - `GH_DISPATCH_TOKEN` — the token (mark as **encrypted/secret**)
   - *(optional)* `GH_WORKFLOW` (default `update.yml`), `GH_BRANCH` (default `main`)
3. Redeploy. The button now runs an update on click; if nothing changed it simply
   doesn't republish. Until these vars are set, the button shows a friendly
   "auto-updates run every ~15 min" message instead of failing.

You can also update from your machine any time with `python3 scripts/update.py`,
or from the **Actions tab → Update site → Run workflow**.

## Customize

- **Default watchlist** (teams pinned on a first visit): `DEFAULT_WATCH` in `wc/config.py`.
- **Team colors:** add entries to `TEAM_META` in `wc/config.py` (everyone else gets an auto color).
- **Look & feel:** the `STYLE` block in `wc/render.py`.
- **Data source:** `DATA_URL` in `wc/config.py`.
