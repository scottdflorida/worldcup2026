"""Time & timezone helpers: kickoff labels and the Pulse band's monotonic
data-ts. Pure leaf module (stdlib only, no other wc imports).

`E = html.escape` lives here — the lowest shared layer — so every module imports
one definition instead of re-aliasing it.
"""
from __future__ import annotations

import html
import os
from datetime import date, datetime, timedelta, timezone

E = html.escape


def _epoch(m):
    """A monotonic sort key (epoch-ish int) from a match's date + kickoff time.

    Local kickoff strings look like '13:00 UTC-6'; we fold the offset back to a
    single comparable instant so the Pulse ribbon is time-ordered across hosts.
    """
    d = m.get("date") or "9999-12-31"
    t = m.get("time") or "00:00"
    try:
        dt = datetime.strptime(d, "%Y-%m-%d")
        base = int(dt.replace(tzinfo=timezone.utc).timestamp())
    except (ValueError, TypeError):
        return 0
    hh = mm = 0
    off = 0
    try:
        clock = t.split()[0]
        hh, mm = (int(x) for x in clock.split(":")[:2])
        if "UTC" in t:
            sign = -1 if "UTC-" in t else 1
            off = sign * int("".join(ch for ch in t.split("UTC")[1] if ch.isdigit()) or 0)
    except (ValueError, IndexError):
        pass
    return base + hh * 3600 + mm * 60 - off * 3600


# US Pacific is UTC-7 (PDT) for the entire tournament window (Jun 11 – Jul 19,
# 2026 are all inside US daylight time), so a fixed offset is exact here.
PT_OFFSET_HOURS = -7
PT_LABEL = "PT"


def today_pt():
    """Today's date in US Pacific — the single 'now' the build embeds (Matchday
    Pulse window, calendar today-cell). WC_TODAY (an ISO date) pins it for tests;
    unset, it is behavior-identical to the previous inline computation."""
    ov = os.environ.get("WC_TODAY")
    if ov:
        return date.fromisoformat(ov)
    return (datetime.now(timezone.utc) + timedelta(hours=PT_OFFSET_HOURS)).date()


def _pt_datetime(m):
    """Fold a match's local kickoff ('13:00 UTC-6') into a single instant shifted
    to US Pacific. Returns (pt_datetime, has_clock). pt_datetime is date-only
    (midnight) when the feed carries no usable clock; None when there's no date."""
    d = m.get("date")
    if not d:
        return None, False
    try:
        base_day = datetime.strptime(d, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None, False
    t = m.get("time") or ""
    hh = mm = 0
    off = None
    has_time = False
    try:
        clock = t.split()[0]
        hh, mm = (int(x) for x in clock.split(":")[:2])
        has_time = True
    except (ValueError, IndexError):
        has_time = False
    if has_time and "UTC" in t:
        sign = -1 if "UTC-" in t else 1
        off = sign * int("".join(ch for ch in t.split("UTC")[1] if ch.isdigit()) or 0)
    if has_time and off is not None:
        utc = datetime(base_day.year, base_day.month, base_day.day, hh, mm,
                       tzinfo=timezone.utc) - timedelta(hours=off)
        return (utc + timedelta(hours=PT_OFFSET_HOURS)).replace(tzinfo=None), True
    return base_day, False


def _pt_parts(m):
    """(day, time) for display, e.g. ('Sat Jun 27', '12:00'); time None if absent."""
    pt, has_clock = _pt_datetime(m)
    if pt is None:
        return None, None
    day = f"{pt.strftime('%a %b')} {pt.day}"
    return day, (f"{pt.hour:02d}:{pt.minute:02d}" if has_clock else None)


def _utc_iso(m):
    """The match's kickoff as a UTC instant ('2026-06-27T19:00:00Z'), or None when
    the feed carries no usable clock+offset (date-only). This is the raw timestamp
    the client uses to re-render times in the viewer's chosen time zone."""
    d = m.get("date")
    if not d:
        return None
    try:
        base = datetime.strptime(d, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    t = m.get("time") or ""
    if "UTC" not in t:
        return None
    try:
        hh, mm = (int(x) for x in t.split()[0].split(":")[:2])
    except (ValueError, IndexError):
        return None
    sign = -1 if "UTC-" in t else 1
    off = sign * int("".join(ch for ch in t.split("UTC")[1] if ch.isdigit()) or 0)
    utc = datetime(base.year, base.month, base.day, hh, mm,
                   tzinfo=timezone.utc) - timedelta(hours=off)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def kickoff_label(m, sep=" "):
    """Inline 'Sat Jun 27 12:00PT' with day/time spans for typographic contrast."""
    day, time = _pt_parts(m)
    if not day:
        return ""
    utc = _utc_iso(m)
    if time and utc:
        return (f'<span class="ko" data-utc="{utc}" data-tfmt="daytime">'
                f'<span class="ko-day">{E(day)}</span>{sep}'
                f'<span class="ko-time">{E(time)}<span class="ko-tz tz">{PT_LABEL}</span>'
                f'</span></span>')
    return f'<span class="ko"><span class="ko-day">{E(day)}</span></span>'


def kickoff_time_pt(m):
    """Bare Pacific clock for the focal 'score-or-time' slot, e.g. '12:00PT'."""
    _, time = _pt_parts(m)
    return f'{time}{PT_LABEL}' if time else ""
