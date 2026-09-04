// Cloudflare Worker: safely lets the public "Refresh Program" button on
// https://noxvfx.github.io/view2026-schedule/ trigger the site's GitHub
// Action, without ever exposing the GitHub token to the browser.
//
// Deployed via the Cloudflare API (see ../README.md for the exact commands).
// Bindings expected at runtime:
//   - RATELIMIT   (KV namespace) — stores the last-triggered timestamp
//   - GITHUB_TOKEN (secret)      — fine-grained PAT, Actions: read/write,
//                                  scoped only to noxvfx/view2026-schedule

const COOLDOWN_MS = 15 * 60 * 1000; // 15 minutes
const ALLOWED_ORIGINS = new Set([
  "https://noxvfx.github.io",
]);
const REPO_OWNER = "noxvfx";
const REPO_NAME = "view2026-schedule";
const WORKFLOW_FILE = "refresh.yml";
const KV_KEY = "lastTriggered";

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin": ALLOWED_ORIGINS.has(origin) ? origin : "null",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

function json(body, status, headers) {
  return new Response(JSON.stringify(body), {
    status,
    headers: Object.assign({ "Content-Type": "application/json" }, headers),
  });
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const headers = corsHeaders(origin);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers });
    }
    if (request.method !== "POST") {
      return json({ error: "method_not_allowed" }, 405, headers);
    }
    if (!ALLOWED_ORIGINS.has(origin)) {
      return json({ error: "origin_not_allowed" }, 403, headers);
    }

    const now = Date.now();
    const lastRaw = await env.RATELIMIT.get(KV_KEY);
    const last = lastRaw ? parseInt(lastRaw, 10) : 0;
    const elapsed = now - last;

    if (elapsed < COOLDOWN_MS) {
      return json({ ok: false, reason: "cooldown", waitSeconds: Math.ceil((COOLDOWN_MS - elapsed) / 1000) }, 429, headers);
    }

    let ghResp;
    try {
      ghResp = await fetch(
        `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
        {
          method: "POST",
          headers: {
            "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
            "Accept": "application/vnd.github+json",
            "User-Agent": "view2026-refresh-relay",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ ref: "main" }),
        }
      );
    } catch (e) {
      return json({ ok: false, reason: "network_error" }, 502, headers);
    }

    if (ghResp.status !== 204) {
      const detail = await ghResp.text().catch(function () { return ""; });
      return json({ ok: false, reason: "github_error", status: ghResp.status, detail: detail.slice(0, 300) }, 502, headers);
    }

    await env.RATELIMIT.put(KV_KEY, String(now));
    return json({ ok: true }, 200, headers);
  },
};
