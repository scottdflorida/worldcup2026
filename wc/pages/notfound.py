"""The 404 page — Cloudflare Pages serves this (with a 404 status) for any path
that doesn't map to a file. Its mere existence turns OFF Pages' default SPA
fallback, which used to return index.html with a 200 for every missing path; a
real 404 is the correct behavior for a static multi-page site.

On-brand "Broadcast Ink": a big mono 404 numeral, a football miss ("Off target")
and two ways back. Rendered through shell() with noindex=True — that adds a
<base href="/"> so the chrome's relative asset/nav URLs resolve even when the
page is served for a deep missing path, plus robots noindex and no canonical.
"""
from __future__ import annotations

from ..shell import shell


def page_notfound(ctx):
    body = """
<section class="nf" data-reveal>
  <p class="nf-eyebrow">Error 404</p>
  <p class="nf-code" aria-hidden="true">404</p>
  <h1 class="nf-title">Off target</h1>
  <p class="nf-sub">That link skied over the bar. The page may have moved, or never existed.</p>
  <nav class="nf-actions" aria-label="404 recovery">
    <a class="nf-btn nf-btn-primary" href="index.html">Back to home</a>
    <a class="nf-btn" href="calendar.html">See the calendar</a>
  </nav>
</section>"""
    return shell(
        "404 — Page not found · World Cup 2026",
        "index.html",
        body,
        ctx,
        desc="This page went off target. Head back to the World Cup 2026 tracker.",
        page="404.html",
        noindex=True,
    )
