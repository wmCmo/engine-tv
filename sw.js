// Service worker for the installed app. It caches nothing on purpose: every page shows live data,
// and a cached copy would show stale numbers as if they were current. Its only job is to show a
// clear "PC not reachable" page instead of a browser error when the PC (or Tailscale) is off.
const OFFLINE = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Lc0 Live</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#312e2b;color:#fff;
font:15px/1.5 "Segoe UI",system-ui,sans-serif;text-align:center;padding:24px;box-sizing:border-box}
b{font-size:20px;display:block;margin-bottom:6px}span{color:#bababa}
button{margin-top:18px;background:#81b64c;color:#fff;border:0;border-radius:6px;padding:10px 22px;font:inherit;font-weight:700}</style>
</head><body><div><b>Your PC isn't reachable</b><span>The dashboard runs on your PC. Check that it's on,
that Tailscale is connected on this phone, and that the dashboard is running (<code>leela</code> or
<code>leela dashboard</code>).</span><br><button onclick="location.reload()">Try again</button></div></body></html>`;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  if (e.request.mode !== "navigate") return;  // data, scripts and images go straight to the network
  e.respondWith(fetch(e.request).catch(() =>
    new Response(OFFLINE, { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } })));
});
