"""Play-money betting pool page + the model/live knockout odds served to the
Pages Functions backend as bets-data.json."""
from __future__ import annotations

from .. import bracket, config, data, util
from .. import odds as odds_api
from ..components import _FB_RND
from ..flags import flag
from ..shell import shell
from ..times import _utc_iso


def _team_ratings(ctx):
    """A rough strength number per team from its group-stage form — the spine of
    the model odds. (Swap in a public odds feed later; the backend just reads
    odds1/odds2 from bets-data.json.)"""
    r = {}
    for info in ctx.analyses.values():
        for row in info["table"]:
            r[row["team"]] = row["Pts"] + 0.35 * row["GD"] + 0.08 * row["GF"]
    return r


def _odds_pair(ra, rb):
    """Two decimal prices from a rating gap, with a small bookmaker margin."""
    import math
    pa = 1.0 / (1.0 + math.exp(-(ra - rb) / 3.0))
    pa = min(max(pa, 0.08), 0.92)
    return (round(max(1.05, (1.0 / pa) * 0.93), 2),
            round(max(1.05, (1.0 / (1.0 - pa)) * 0.93), 2))


def match_settlement(m):
    """(decided, winner) for a knockout match, with the settlement-oracle guard.

    A knockout tie that finished level but has no penalty result in the feed yet
    (winner still unknown) must NOT settle: we emit decided=False so the backend
    never resolves bets against a null winner while the shootout is pending. A bet
    only settles once a concrete winner exists (regulation, extra time or pens)."""
    if not data.has_result(m):
        return False, None
    winner = bracket.match_winner(m)
    return (winner is not None), winner


def betting_data(ctx):
    """Every knockout match whose two sides are known: the matchup, model odds,
    kickoff, and result. The Pages Functions read this to list bettable games,
    snapshot odds onto a wager, and settle once a match is decided."""
    by_num = ctx.by_num
    ratings = _team_ratings(ctx)
    cache = odds_api.load_cache()      # public market odds, when available
    out = []
    for m in ctx.matches:
        if m.get("round") not in config.KO_ROUNDS_ALL:
            continue
        t1 = bracket.resolve_slot(m["team1"], ctx.analyses, by_num)
        t2 = bracket.resolve_slot(m["team2"], ctx.analyses, by_num)
        if not (t1["team"] and t2["team"]):
            continue  # not bettable until both sides are set
        pub = odds_api.pair_odds(cache, t1["team"], t2["team"])
        if pub:
            (o1, o2), src = pub, "live"
        else:
            o1, o2 = _odds_pair(ratings.get(t1["team"], 3), ratings.get(t2["team"], 3))
            src = "model"
        decided, winner = match_settlement(m)
        out.append({
            "num": m["num"], "round": _FB_RND.get(m.get("round"), m.get("round")),
            "team1": t1["team"], "team2": t2["team"], "odds1": o1, "odds2": o2,
            "oddsSrc": src, "kickoff": _utc_iso(m), "decided": decided,
            "winner": winner,
        })
    teams = sorted({x for m in out for x in (m["team1"], m["team2"])})
    return {"matches": out, "flags": {t: flag(t) for t in teams},
            "urls": {t: util.page_for(t) for t in teams}, "stage": ctx.stage()}


def page_betting(ctx):
    body = """
<section class="bet-intro" aria-label="Betting pool">
  <div class="fb-head"><h1>Betting pool</h1></div>
  <p class="muted">Play money. Everyone starts with $100, bet any amount on who wins each
  knockout match, payouts at the listed odds. Hit $0 and you're out.</p>
</section>
<div id="bet-app" class="bet-app" aria-live="polite">
  <p class="muted bet-loading">Loading…</p>
</div>
<div class="fb-modal" id="bet-modal" hidden>
  <div class="fb-modal-back" data-bet-close></div>
  <div class="fb-modal-panel" role="dialog" aria-modal="true" aria-label="Place a bet">
    <div class="fb-modal-head"><span class="fb-modal-k" id="bet-modal-k">Place a bet</span>
      <button class="fb-modal-x" type="button" data-bet-close aria-label="Close">✕</button></div>
    <div class="bet-form" id="bet-form"></div>
  </div>
</div>
"""
    return shell("Betting Pool — World Cup 2026", "betting.html", body, ctx,
                 desc="A play-money World Cup knockout betting pool with friends — $100 to "
                      "start, bet on match winners at model odds, and climb the leaderboard.",
                 page="betting.html")
