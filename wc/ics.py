"""Build-time iCalendar (ICS, RFC 5545) feed generation — stdlib only.

Emits a full-schedule feed (``ics/all-matches.ics``) plus one per team
(``ics/<slug>.ics``) into ``public/``. Every ``DTSTAMP`` is pinned to the data
feed's last-updated instant — NEVER the wall clock — so rebuilding unchanged
data yields byte-identical files (the golden tests depend on this determinism).

Choices worth stating:
  * Event length: a group game reserves 90 minutes; a knockout tie reserves 120
    (90 + 30, covering extra time). DTENDs are indicative, not authoritative.
  * UID: numbered (knockout) matches use ``wc26-m<num>@…`` per the spec. Group
    games carry no match number in the feed, so they get a stable, content-keyed
    ``wc26-g<date>-<team1>-<team2>@…`` instead (fixed for a given fixture).
  * Line folding: content lines are folded at 75 octets per RFC 5545 (never
    splitting a multi-byte character); TEXT values are escaped (\\ ; , newline).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import bracket, config, util, venues
from .shell import SITE_URL
from .times import _utc_iso

_DOMAIN = "worldcup.sflorida.studio"
_GROUP_MIN = 90
_KO_MIN = 120
_KO_ROUNDS = set(config.KO_ROUNDS_ALL)


# --------------------------------------------------------------------------
# RFC 5545 primitives
# --------------------------------------------------------------------------
def _escape(text):
    """Escape an ICS TEXT value: backslash, semicolon, comma and newline."""
    return (str(text).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n"))


def _fold(line):
    """Fold one content line to <=75 octets (continuations begin with a single
    space), without ever splitting a UTF-8 multi-byte character."""
    out, cur, cur_oct = [], "", 0
    for ch in line:
        o = len(ch.encode("utf-8"))
        if cur_oct + o > 75:
            out.append(cur)
            cur, cur_oct = " " + ch, 1 + o     # leading space counts toward 75
        else:
            cur += ch
            cur_oct += o
    out.append(cur)
    return "\r\n".join(out)


def _basic(dt):
    """A UTC datetime as an ICS basic-format instant, e.g. 20260709T200000Z."""
    return dt.strftime("%Y%m%dT%H%M%SZ")


# --------------------------------------------------------------------------
# Match → VEVENT
# --------------------------------------------------------------------------
def _dtstamp(ctx):
    """The feed's last-updated instant (UTC) as the single DTSTAMP for the whole
    calendar. Deterministic fallback (tournament start) if it's absent/unpar;able."""
    lu = ctx.last_updated
    if lu:
        try:
            dt = datetime.fromisoformat(lu)
            # A naive stamp is treated as UTC rather than astimezone()'d, so the
            # emitted DTSTAMP never depends on the build machine's local zone.
            dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
            return _basic(dt)
        except ValueError:
            pass
    return _basic(datetime(2026, 6, 11, tzinfo=timezone.utc))


def _utc_dt(m):
    iso = _utc_iso(m)
    if not iso:
        return None
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _uid(m):
    num = m.get("num")
    if num is not None:
        return f"wc26-m{num}@{_DOMAIN}"
    key = f"{m.get('date') or 'x'}-{util.slug(str(m.get('team1')))}-{util.slug(str(m.get('team2')))}"
    return f"wc26-g{key}@{_DOMAIN}"


def _side_name(ctx, token):
    """A concrete nation, or a readable slot label (e.g. 'Winner A') when the tie
    isn't resolved yet — so the full-schedule feed still names every event."""
    res = bracket.resolve_slot(token, ctx.analyses, ctx.by_num)
    return res["team"] or res["label"]


def _round_label(m):
    rd = m.get("round", "")
    if rd in _KO_ROUNDS:
        return rd
    return m.get("group") or rd     # group games read as "Group A"


def _location(m):
    stadium, loc = venues.venue(m.get("ground", "") or "")
    return f"{stadium}, {loc}" if loc else stadium


def _vevent(ctx, m, dtstamp, url):
    t1 = _side_name(ctx, m.get("team1"))
    t2 = _side_name(ctx, m.get("team2"))
    summary = f"⚽ {t1} v {t2} — {_round_label(m)}"    # "⚽ A v B — Round"
    lines = ["BEGIN:VEVENT", f"UID:{_uid(m)}", f"DTSTAMP:{dtstamp}"]
    dt = _utc_dt(m)
    if dt is not None:
        mins = _KO_MIN if m.get("round") in _KO_ROUNDS else _GROUP_MIN
        lines.append(f"DTSTART:{_basic(dt)}")
        lines.append(f"DTEND:{_basic(dt + timedelta(minutes=mins))}")
    else:
        day = (m.get("date") or "").replace("-", "")           # date-only fallback
        if day:
            lines.append(f"DTSTART;VALUE=DATE:{day}")
    lines.append("SUMMARY:" + _escape(summary))
    loc = _location(m)
    if loc:
        lines.append("LOCATION:" + _escape(loc))
    if url:
        lines.append("URL:" + url)
    lines.append("STATUS:CONFIRMED")
    lines.append("END:VEVENT")
    return lines


def _wrap(name, body_lines):
    head = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//worldcup.sflorida.studio//WC2026//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:" + _escape(name),
        "NAME:" + _escape(name),
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    all_lines = head + body_lines + ["END:VCALENDAR"]
    # Fold every content line ONCE, centrally (RFC 5545 §3.1): lines >75 octets
    # continue on the next line with a leading space. Folding is applied here so
    # no line is double-folded.
    return "\r\n".join(_fold(line) for line in all_lines) + "\r\n"


# --------------------------------------------------------------------------
# Public feeds
# --------------------------------------------------------------------------
def all_matches_ics(ctx):
    """Every fixture in one subscribable calendar."""
    dtstamp = _dtstamp(ctx)
    url = f"{SITE_URL}/calendar.html"
    body = []
    for m in ctx.sorted_matches():
        body += _vevent(ctx, m, dtstamp, url)
    return _wrap("World Cup 2026 — All matches", body)


def team_ics(ctx, team):
    """One nation's confirmed fixtures (group games always; knockout ties once the
    feed names the team into them)."""
    dtstamp = _dtstamp(ctx)
    url = f"{SITE_URL}/{util.page_for(team)}"
    body = []
    for m in ctx.sorted_matches():
        if team in (m.get("team1"), m.get("team2")):
            body += _vevent(ctx, m, dtstamp, url)
    return _wrap(f"World Cup 2026 — {team}", body)
