"""LLM-written "road to the final" blurbs, one per team, via the Anthropic API.

Each blurb is a short sports-desk paragraph: the knockout match the team is about
to play, then the shape of the path that could lie beyond it. We generate them
with Claude Sonnet and cache the text in data/blurbs.json keyed by a fingerprint
of the facts that went into the prompt — so a team's blurb is only regenerated
when its situation actually changes (its match is played, or its next opponent
resolves). render.py just reads the cache; it never calls the API at build time.
"""
from __future__ import annotations

import hashlib
import json
import os

from . import bracket, data

# The user explicitly asked for a Sonnet call.
MODEL = "claude-sonnet-4-6"
BLURBS_PATH = "data/blurbs.json"
# Bump when the prompt changes so cached blurbs regenerate even if the facts
# (and therefore the brief) are unchanged.
PROMPT_VERSION = "2"

_ORDINAL = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}
_ROUND = {"Round of 32": "Round of 32", "Round of 16": "Round of 16",
          "Quarter-final": "quarterfinal", "Semi-final": "semifinal", "Final": "final"}


def _kickoff_pt(m):
    """'Wed Jul 1 17:00 PT' — reuse the renderer's Pacific conversion."""
    from . import render
    day, time = render._pt_parts(m)
    if not day:
        return None
    return f"{day} {time} PT" if time else day


def _scorers(match, side):
    out = []
    for x in (match.get(side) or []):
        nm = (x.get("name") or "").split()[-1]
        mn = x.get("minute", "")
        tag = f"{nm} {mn}'" if mn else nm
        if x.get("penalty"):
            tag += " (pen)"
        if tag:
            out.append(tag)
    return out


def _last_match(ctx, team):
    """The team's most recent completed match, oriented to them, with the goal
    timeline so the model can judge HOW it went (comfortable, late, a scare)."""
    _, recent = ctx.team_fixtures(team)
    if recent is None:
        return None
    g1, g2 = data.final_score(recent)
    home = recent.get("team1") == team
    opp = recent.get("team2") if home else recent.get("team1")
    ts, os_ = (g1, g2) if home else (g2, g1)
    result = "win" if ts > os_ else ("loss" if ts < os_ else "draw")
    rd = recent.get("round", "")
    stage = "group stage" if str(rd).startswith("Matchday") else _ROUND.get(rd, rd)
    out = {
        "opponent": opp,
        "result": result,
        "score": f"{ts}-{os_}",
        "stage": stage,
        "their_goals": _scorers(recent, "goals1" if home else "goals2"),
        "opponent_goals": _scorers(recent, "goals2" if home else "goals1"),
    }
    pens = (recent.get("score") or {}).get("p")
    if pens:
        pt, po = (pens[0], pens[1]) if home else (pens[1], pens[0])
        out["result"] = "win on penalties" if pt > po else "loss on penalties"
        out["penalty_shootout"] = f"{pt}-{po}"
    return out


def _status(proj):
    st = proj["status"]
    if st.get("won_group"):
        return f'won {proj["group"]}'
    if st.get("clinched_top2"):
        return f'qualified from {proj["group"]}'
    if proj["rank"] >= 3:
        return f'advanced as a best third-placed team out of {proj["group"]}'
    return f'{_ORDINAL.get(proj["rank"], "")} in {proj["group"]}'


def team_brief(ctx, team):
    """Assemble the structured facts the prompt is built from — strictly things
    we know, so the model has a factual spine and nothing to invent."""
    proj = ctx.projections[team]
    row = proj["row"]
    g = proj["group_letter"]
    ko = bracket.find_ko_match(ctx.matches, team)
    knocked = ctx.knocked_out(team)

    brief = {
        "team": team,
        "group": proj["group"],
        "finish": f'{_ORDINAL.get(proj["rank"], "")} place',
        "record": f'{row["W"]}W-{row["D"]}D-{row["L"]}L, {row["GF"]}-{row["GA"]} GD, {row["Pts"]} pts',
        "status": _status(proj),
        "eliminated": bool(knocked),
        "last_match": _last_match(ctx, team),
    }
    if knocked or ko is None:
        return brief

    entry = f'{proj["rank"]}{g}' if proj["rank"] in (1, 2) else None
    path = bracket.project_path(team, ctx.matches, ctx.analyses, g, entry) or []
    by_num = bracket.index_matches(ctx.matches)
    rounds = []
    for step in path:
        m_obj = by_num.get(step["num"])
        if m_obj is not None and data.has_result(m_obj):
            continue  # already played — that's the recap (last_match), not the road ahead
        opp = step["opponent"]
        m = {"date": step.get("date"), "time": step.get("time")}
        entry_round = {"round": _ROUND.get(step["round"], step["round"]),
                       "when": _kickoff_pt(m)}
        if opp["team"]:
            entry_round["opponent"] = opp["team"]
            entry_round["decided"] = True
        else:
            cands = sorted(opp.get("candidates") or [])
            entry_round["possible_opponents"] = cands
            entry_round["decided"] = False
        rounds.append(entry_round)
    if rounds:
        brief["road"] = rounds
    return brief


def fingerprint(brief):
    """Stable hash of the brief (plus prompt version) — the cache key. Changes
    when the facts that shape the blurb change, or when the prompt is revised."""
    blob = PROMPT_VERSION + "\n" + json.dumps(brief, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


SYSTEM = (
    "You write for the sports desk of a World Cup 2026 tracker with a bold, "
    "broadsheet voice — confident, vivid, and knowledgeable, the register of a "
    "great newspaper football writer. No breathless hype, clichés "
    "(\"will be looking to\", \"on a mission\"), or fan-speak.\n\n"
    "Given a JSON brief about one team, write a SHORT blurb: 3-5 sentences, about "
    "70-110 words, present tense, active voice.\n\n"
    "Cover, in order:\n"
    "1. THE LAST MATCH — recap their most recent result (`last_match`): who they "
    "played and the score, plus a qualitative read on HOW IT WENT — comfortable, "
    "hard-fought, a statement, a late twist, a scare, a deserved exit — inferred "
    "from the result, the margin, and the goal timeline (minutes in the scorer "
    "lists). One or two sentences.\n"
    "2. THE NEXT MATCH — the knockout tie they are about to play (the first entry "
    "of `road`): name the opponent, the round, and the kickoff (use `when` "
    "verbatim). Make it compelling by conveying the GENERAL CONSENSUS for the tie "
    "— who is favored and the likely complexion (a routine assignment, a coin-flip, "
    "a real test, an underdog with a puncher's chance) — drawing on widely "
    "understood team reputation and stature together with the form shown in "
    "`last_match`.\n"
    "3. BEYOND — one brief beat on what could lie deeper in the draw, naming one or "
    "two notable possible opponents from later `road` rounds as possibilities, not "
    "certainties.\n\n"
    "If `eliminated` is true (there is no `road`), skip 2 and 3: instead write a "
    "2-3 sentence retrospective — the last match and how it went, then a closing "
    "line on how and where their tournament ended.\n\n"
    "Rules:\n"
    "- The factual spine — opponent, round, kickoff, score, who could be waiting — "
    "comes ONLY from the brief.\n"
    "- You MAY characterize favoritism and expectation from well-known football "
    "reputation, but do NOT cite specific numbers you weren't given (FIFA ranking "
    "positions, betting odds, win percentages), and invent NO scores, players, or "
    "results beyond the brief.\n"
    "- For an undecided round, treat the listed teams as the live candidate pool.\n"
    "- Output the blurb prose only — no headings, no preamble, no quotation marks, "
    "no emoji."
)


def build_messages(brief):
    """Return (system, user_content) for the Messages API."""
    user = ("Write the road-to-the-final blurb for this team.\n\n"
            + json.dumps(brief, indent=2, ensure_ascii=False))
    return SYSTEM, user


def generate_blurb(client, brief):
    system, user = build_messages(brief)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=400,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


# ---- cache I/O ----------------------------------------------------------
def load_cache(path=BLURBS_PATH):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_cache(cache, path=BLURBS_PATH):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=1, ensure_ascii=False, sort_keys=True)


def blurb_for(cache, team):
    """The cached blurb text for a team, or None."""
    entry = cache.get(team)
    return entry.get("text") if entry else None


def refresh_stale(ctx, *, force=False, path=BLURBS_PATH, client=None, log=print):
    """Regenerate every blurb whose fingerprint moved (its match was played, its
    next opponent resolved, a downstream candidate pool shrank, or the prompt was
    revised) and leave the rest untouched. Returns the number regenerated.

    This is what the post-match pipeline calls — one result landing changes the
    fingerprints of exactly the affected teams, so only those hit the API."""
    cache = load_cache(path)
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    changed = 0
    for team in ctx.teams:
        brief = team_brief(ctx, team)
        fp = fingerprint(brief)
        cur = cache.get(team)
        if not force and cur and cur.get("fingerprint") == fp:
            continue
        cache[team] = {"text": generate_blurb(client, brief), "fingerprint": fp}
        changed += 1
        log(f"[blurbs] regenerated {team}")
    save_cache(cache, path)
    return changed


# --------------------------------------------------------------------------
# Brazilian Portuguese (pt-BR) translation of the blurbs.
#
# The site ships a client-side EN/pt-BR toggle (see wc/i18n.py).  The blurbs are
# the only long-form prose, so they get a parallel pt-BR cache, keyed by team and
# stamped with the *English* blurb's fingerprint plus this prompt version.  The
# post-match pipeline calls refresh_pt() right after refresh_stale(), so exactly
# the blurbs that just changed get re-translated — and i18n.py only serves a pt
# blurb when its fingerprint still matches the live English one (else it falls
# back to English), so a translation can never go stale on the page.
# --------------------------------------------------------------------------
BLURBS_PT_PATH = "data/blurbs.pt.json"
TRANSLATE_MODEL = "claude-sonnet-4-6"
# Bump to force every blurb to re-translate even when the English text is unchanged.
TRANSLATE_PROMPT_VERSION = "1"

TRANSLATE_SYSTEM = (
    "You are a professional Brazilian Portuguese (pt-BR) football translator for a "
    "World Cup 2026 tracker. Translate the given English team write-up into natural, "
    "broadcast-quality Brazilian Portuguese — the register of ge.globo / Globo Esporte. "
    "Idiomatic, not word-for-word.\n\n"
    "Rules:\n"
    "- Use Brazilian football vocabulary: fase de grupos, mata-mata, oitavas de final, "
    "quartas, semifinal, classificação, empate, goleada, virada, disputa de pênaltis, "
    "saldo de gols, zagueiro, meio-campo, atacante, técnico, seleção.\n"
    "- Translate national-team / country names to their standard pt-BR forms (Algeria→"
    "Argélia, England→Inglaterra, Netherlands→Holanda, Ivory Coast→Costa do Marfim, "
    "Czech Republic→República Tcheca, DR Congo→RD Congo, South Korea→Coreia do Sul, "
    "USA→Estados Unidos, and so on). Group letters: 'Group J' → 'Grupo J'.\n"
    "- Do NOT translate player names, coach names, stadium names, or city names — keep "
    "them exactly as written.\n"
    "- Keep all scorelines, numbers, percentages, and dates exactly as written.\n"
    "- Preserve paragraph breaks and the em-dash (—) punctuation style.\n"
    "- Output ONLY the translated prose — no preamble, no quotation marks, no notes."
)


def translate_blurb(client, text_en):
    resp = client.messages.create(
        model=TRANSLATE_MODEL,
        max_tokens=500,
        system=TRANSLATE_SYSTEM,
        messages=[{"role": "user",
                   "content": "Translate this to Brazilian Portuguese:\n\n" + text_en}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def refresh_pt(*, force=False, en_path=BLURBS_PATH, pt_path=BLURBS_PT_PATH,
               client=None, log=print):
    """Translate into pt-BR every blurb whose English fingerprint moved (or whose
    translation is missing / from an older translation prompt), leaving the rest
    untouched. Returns the number translated. Run after refresh_stale()."""
    en = load_cache(en_path)
    pt = load_cache(pt_path)
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    changed = 0
    for team, entry in en.items():
        text_en = (entry.get("text") or "").strip()
        if not text_en:
            continue
        fp = entry.get("fingerprint")
        cur = pt.get(team)
        if (not force and cur and cur.get("fingerprint") == fp
                and cur.get("tv") == TRANSLATE_PROMPT_VERSION):
            continue
        pt[team] = {"text": translate_blurb(client, text_en),
                    "fingerprint": fp, "tv": TRANSLATE_PROMPT_VERSION}
        changed += 1
        log(f"[blurbs.pt] translated {team}")
    for team in list(pt):          # drop teams no longer present in the English cache
        if team not in en:
            del pt[team]
    save_cache(pt, pt_path)
    return changed
