// Cloudflare Pages Function — GET /api/live
//
// Proxies ESPN's public (keyless) FIFA World Cup scoreboard and returns a small
// normalized JSON the page polls for live scores. The static site only knows
// FINAL scores (openfootball posts at full time), so this fills the gap *during*
// a match. Edge-cached ~25s so a burst of visitors doesn't multiply upstream
// calls. Best-effort: any failure returns {ok:false} and the page just keeps
// showing kickoff times. Team-name reconciliation (USA↔United States, etc.) is
// done client-side, so this stays a thin pass-through.
//
// Unofficial/undocumented endpoint — not affiliated with ESPN; may change.

const ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard";
const TTL = 25; // seconds

function teamName(c) {
  return (c && c.team && (c.team.displayName || c.team.name || c.team.shortDisplayName)) || "";
}
function num(v) {
  return v == null || v === "" ? null : Number(v);
}

export async function onRequestGet({ request }) {
  const cache = caches.default;
  const cacheKey = new Request(new URL("/api/live", request.url).toString(), { method: "GET" });
  const cached = await cache.match(cacheKey);
  if (cached) return cached;

  let body = { ok: false, matches: [] };
  try {
    const r = await fetch(ESPN, {
      headers: { "User-Agent": "worldcup-sflorida-studio/1.0", accept: "application/json" },
      cf: { cacheTtl: TTL, cacheEverything: true },
    });
    if (r.ok) {
      const d = await r.json();
      const matches = [];
      for (const e of d.events || []) {
        const comp = (e.competitions || [])[0];
        if (!comp) continue;
        const st = (comp.status || e.status || {}).type || {};
        const cs = comp.competitors || [];
        const home = cs.find((c) => c.homeAway === "home") || cs[0];
        const away = cs.find((c) => c.homeAway === "away") || cs[1];
        if (!home || !away) continue;
        matches.push({
          date: (e.date || "").slice(0, 10),
          t1: teamName(home), // ESPN home
          t2: teamName(away), // ESPN away
          s1: num(home.score),
          s2: num(away.score),
          state: st.state || "pre", // pre | in | post
          clock: (comp.status || {}).displayClock || "",
          detail: st.shortDetail || st.detail || "",
        });
      }
      body = { ok: true, matches };
    }
  } catch (err) {
    body = { ok: false, matches: [], error: String((err && err.message) || err) };
  }

  const resp = new Response(JSON.stringify(body), {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": `public, max-age=${TTL}`,
    },
  });
  try {
    await cache.put(cacheKey, resp.clone());
  } catch (e) {
    /* caching is best-effort */
  }
  return resp;
}
