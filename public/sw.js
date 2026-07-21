/* World Cup 2026 — service worker (generated from wc/pwa.py; do not edit). */
'use strict';
var VERSION = 'd96a6ec622';
var CACHE = 'wc26-' + VERSION;
var PRECACHE = [
  "/",
  "/calendar",
  "/bracket",
  "/assets/style.css?v=d96a6ec622",
  "/assets/app.js?v=d96a6ec622",
  "/assets/i18n.js?v=d96a6ec622",
  "/assets/favicon.svg",
  "/assets/TwemojiCountryFlags.woff2"
];

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
