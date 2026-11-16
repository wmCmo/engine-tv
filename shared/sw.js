// Service worker for both installed phone apps (engine-tv's Stockfish monitor and Lc0 Live). It caches nothing
// on purpose: every page shows live data, and a cached copy would show stale numbers as if they were current.
// Its only job is a clear "PC not reachable" page instead of a browser error when the PC or Tailscale is off.
// The server fills in __APP_NAME__ and __START__ (see sharedfiles.py).
const OFFLINE = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>__APP_NAME__</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#1f1d1b;color:#f3f1ec;
font:15px/1.5 "Segoe UI",system-ui,sans-serif;text-align:center;padding:24px;box-sizing:border-box}
b{font:700 22px/1.3 "Iowan Old Style","Palatino Linotype",Georgia,serif;display:block;margin-bottom:8px}
span{color:#bdb7ad}code{color:#f3f1ec}
button{margin-top:18px;background:#81b64c;color:#1f1d1b;border:0;border-radius:6px;padding:12px 24px;font:inherit;font-weight:700}</style>
</head><body><div><b>Your PC isn't reachable</b><span>__APP_NAME__ runs on your PC. Check that the PC is on, that
Tailscale is connected on this phone, and that the app is running (<code>__START__</code>).</span><br>
<button onclick="location.reload()">Try again</button></div></body></html>`;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  if (e.request.mode !== "navigate") return;  // data, scripts and images go straight to the network
  e.respondWith(fetch(e.request).catch(() =>
    new Response(OFFLINE, { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } })));
});
