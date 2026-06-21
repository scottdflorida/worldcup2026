// Cloudflare Pages Function — POST /api/refresh
//
// The on-site "Update now" button calls this. It triggers the GitHub Actions
// "Update site" workflow (workflow_dispatch), which re-fetches the live results
// and publishes only if something changed. The GitHub token stays server-side
// here (a Pages secret) and never reaches the browser.
//
// Required Pages environment variables (Settings -> Environment variables):
//   GH_OWNER          your GitHub username/org        e.g. scottflorida
//   GH_REPO           the repo name                   e.g. worldcup2026
//   GH_DISPATCH_TOKEN fine-grained PAT, Actions: Read & Write on that repo  (secret)
// Optional:
//   GH_WORKFLOW       workflow file name              default: update.yml
//   GH_BRANCH         branch to run on                default: main

const COOLDOWN_SECONDS = 45;
const LOCK_URL = "https://wc-refresh.internal/lock";

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

export async function onRequestPost({ env }) {
  const { GH_OWNER, GH_REPO, GH_DISPATCH_TOKEN } = env;
  if (!GH_OWNER || !GH_REPO || !GH_DISPATCH_TOKEN) {
    return json({ ok: false, error: "not_configured" }, 503);
  }

  // Best-effort per-colo cooldown so the button can't be spammed.
  const cache = caches.default;
  if (await cache.match(LOCK_URL)) {
    return json({ ok: false, error: "cooldown" }, 429);
  }

  const workflow = env.GH_WORKFLOW || "update.yml";
  const branch = env.GH_BRANCH || "main";
  const url = `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/actions/workflows/${workflow}/dispatches`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${GH_DISPATCH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "worldcup-refresh",
    },
    body: JSON.stringify({ ref: branch }),
  });

  if (res.status === 204) {
    await cache.put(
      LOCK_URL,
      new Response("1", { headers: { "Cache-Control": `max-age=${COOLDOWN_SECONDS}` } })
    );
    return json({ ok: true });
  }

  return json({ ok: false, error: `github_${res.status}`, detail: await res.text() }, 502);
}

// A GET is handy for a quick "is this wired up?" check.
export async function onRequestGet({ env }) {
  const configured = Boolean(env.GH_OWNER && env.GH_REPO && env.GH_DISPATCH_TOKEN);
  return json({ ok: true, configured });
}
