"""Progressive-web-app assets — the web app manifest and the service worker.

Both are generated into the site by render_site() and are fully deterministic:
the only moving part is the asset fingerprint (art._asset_ver()), which is itself
a pure hash of the CSS/JS/i18n bytes, so identical inputs produce identical bytes.

The service worker precaches the shell assets + an offline core (home, calendar,
bracket), serves hashed /assets/ cache-first and HTML documents network-first
(so a deploy always propagates when online), and NEVER intercepts /api/,
bets-data.json or /ics/ (live/dynamic endpoints).
"""
from __future__ import annotations

import json

# Home-screen / manifest icons. The 192 + 512 PNGs are rasterized from
# wc/assets/favicon.svg (see scripts/og_png.md) and committed as static assets
# under public/assets/ — the build references them here but never rewrites them
# (write_site only clears *.html), exactly like og.png / apple-touch-icon.png.
# This list is a fixed authoring-time decision (not a disk probe) so the manifest
# is byte-identical on every build, including the golden fixtures' empty out dirs.
ICONS = [
    {"src": "/assets/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
    {"src": "/assets/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
    {"src": "/assets/apple-touch-icon.png", "sizes": "180x180", "type": "image/png", "purpose": "any"},
]

# The manifest theme/background commit to the LIGHT paper (a manifest theme_color
# is a single value). The two media <meta name="theme-color"> tags in the page
# head carry the correct dark value for the browser chrome; the manifest can't.
PAPER = "#F4F2EC"


def manifest():
    """The web app manifest (manifest.webmanifest) as pretty-printed JSON."""
    data = {
        "name": "World Cup /26",
        "short_name": "WC26",
        "description": ("Live FIFA World Cup 2026 tracker — groups, standings, a "
                        "connected knockout bracket and a play-money pool, in "
                        "English and Brazilian Portuguese."),
        "lang": "en",
        "dir": "ltr",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": PAPER,
        "theme_color": PAPER,
        "icons": ICONS,
    }
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def precache_urls(version):
    """Shell assets (fingerprinted) + the offline core, root-absolute so the
    service worker can match them regardless of the requesting clean URL."""
    v = "?v=" + version
    return [
        "/",
        "/calendar",
        "/bracket",
        "/assets/style.css" + v,
        "/assets/app.js" + v,
        "/assets/i18n.js" + v,
        "/assets/favicon.svg",
        "/assets/TwemojiCountryFlags.woff2",
    ]


_SW_TEMPLATE = r"""/* World Cup 2026 — service worker (generated from wc/pwa.py; do not edit). */
'use strict';
var VERSION = '__VERSION__';
var CACHE = 'wc26-' + VERSION;
var PRECACHE = __PRECACHE__;

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (c) { return c.addAll(PRECACHE); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        return k === CACHE ? null : caches.delete(k);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

function putInCache(req, res) {
  if (res && res.ok && res.type === 'basic') {
    var copy = res.clone();
    caches.open(CACHE).then(function (c) { c.put(req, copy); });
  }
  return res;
}

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  var p = url.pathname;

  // Never intercept live/dynamic endpoints — always go straight to the network.
  if (p.indexOf('/api/') === 0 || p === '/bets-data.json' || p.indexOf('/ics/') === 0) return;

  // Hashed static assets: cache-first (immutable per fingerprint).
  if (p.indexOf('/assets/') === 0) {
    e.respondWith(
      caches.match(req).then(function (hit) {
        return hit || fetch(req).then(function (res) { return putInCache(req, res); });
      })
    );
    return;
  }

  // HTML documents: network-first so a live deploy always propagates; fall back
  // to cache (then the cached home page) only when the network is unreachable.
  var accept = req.headers.get('accept') || '';
  if (req.mode === 'navigate' || accept.indexOf('text/html') !== -1) {
    e.respondWith(
      fetch(req).then(function (res) { return putInCache(req, res); }).catch(function () {
        return caches.match(req).then(function (hit) { return hit || caches.match('/'); });
      })
    );
    return;
  }

  // Anything else: cache, then network.
  e.respondWith(caches.match(req).then(function (hit) { return hit || fetch(req); }));
});
"""


def service_worker(version):
    """The service worker (sw.js) for this build, versioned by the asset hash."""
    precache = json.dumps(precache_urls(version), indent=2)
    return _SW_TEMPLATE.replace("__VERSION__", version).replace("__PRECACHE__", precache)
