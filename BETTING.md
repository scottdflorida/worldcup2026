# Betting pool

The `/bets` page and its API (`functions/api/bets/*`) are deployed as part of
the site, but the pool stays in a "not set up yet" state until a **Cloudflare
D1** database is created and bound as `DB`. That's a one-time infra step —
see [`wrangler.toml`](wrangler.toml) and [`scripts/setup-d1.md`](scripts/setup-d1.md)
for the exact commands.

Once it's bound: visit `/bets`, pick a display name + a pool code, share the
code with friends, and you each start with $100.

## How it works

- **Odds** come from [The Odds API](https://the-odds-api.com/) when a key is
  configured, with a model-derived fallback. `wc/odds.py` pulls the public
  h2h market for each knockout tie, de-vigs it, and folds the draw price into
  a 2-way "wins the tie" price (extra time + penalties are treated as close
  to a coin flip). Ties the public market hasn't priced (or when no
  `ODDS_API_KEY` is configured) fall back to odds derived from group-stage
  form. Every match in `public/bets-data.json` carries an `oddsSrc` field —
  `"live"` or `"model"` — so the UI and the API can both tell which kind of
  price a bet was placed against. The odds refresh is TTL-guarded (roughly
  3x/day) to stay well inside the free API quota; `ODDS_API_KEY` is a
  **GitHub Actions secret** used at build time (`.github/workflows/update.yml`),
  not a Cloudflare runtime secret — see `scripts/setup-d1.md` for the
  distinction.
- **Odds are snapshotted** onto each bet when placed, so a later odds move
  doesn't change a standing wager.
- **Settlement is automatic:** whenever anyone loads the pool, every open bet
  on a now-decided match is settled (win → `stake × odds` credited; loss →
  stake gone). Results come from `bets-data.json`, which the daily update job
  republishes.
- **$0 = out** (you can't stake more than your balance), and you can bet any
  amount, any number of times, on any open match.

## Identity: passwordless, name + pool code is the credential

There's no password, no account, no email — on purpose. Joining a pool with a
name and code (`POST /api/bets/join`) does one of two things:

- if that name doesn't exist in that pool yet, it creates a new player with a
  fresh token and a $100 balance;
- if it **does** exist (case-insensitively — "Lo" and "lo" resolve to the same
  player), the join **reclaims** that player and returns their existing
  token, balance, and bet history instead of rejecting the request as
  `name_taken`.

The token is stored client-side (as the active "membership") and mirrored
into a long-lived, `HttpOnly` + `Secure` cookie as a same-device fallback, so
identity survives a `localStorage` wipe on the same browser. But because
reclaiming only needs the name + code — not proof you hold the original
token — **anyone who knows (or guesses) a player's display name and the pool
code can log in as them**, from any device, and see or spend their balance.

That's a deliberate tradeoff, not an oversight: for a friends-scale pool, the
alternative (a real password/account system, or "sorry, that name's taken,
forever, even though it was you") is worse UX for near-zero real stakes. It
means:

- **Don't reuse a pool code as if it were secret-secret** — treat it like a
  shared house key, not a bank PIN. Anyone with the code can join as a new
  name, or reclaim any existing name in that pool.
- **Don't use this for real money.** It's play-money by design; the identity
  model assumes the worst case is "a friend nudges your balance as a joke,"
  not "someone drains a wallet."
- If you want stronger isolation later, the fix is scoped to `join.js` and
  `schema.sql` (e.g. requiring the original token to reclaim, or adding a
  real secret) — not a rewrite of the betting flow.

## Setup

See [`scripts/setup-d1.md`](scripts/setup-d1.md) for the exact commands
(create the D1 database, apply `schema.sql`, bind it in the Pages project,
run it locally with `wrangler pages dev`) and [`wrangler.toml`](wrangler.toml)
for the local Cloudflare config.
