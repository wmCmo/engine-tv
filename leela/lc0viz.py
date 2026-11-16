"""Live dashboard for the Lc0 training client.

    python lc0viz.py [--client-dir PATH] [--port 8765]

Collects every finished game from the client's data-* folder into ./archive (training games are
uploaded and deleted within seconds), decodes them and serves the pages on 127.0.0.1.
Per-game stats are cached in ./cache so restarts don't re-decode everything.
"""
import argparse
import json
import re
import subprocess
import threading
import time
import urllib.request
from collections import OrderedDict, deque
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, parse_qs

from collector import Collector, DEFAULT_CLIENT_DIR, ARCHIVE
from decoder import decode_game
from netapi import NetHelper
from stats import game_stats, aggregate

ROOT = Path(__file__).resolve().parent
SHARED = ROOT.parent / "shared"   # engine-tv/shared: the piece library both apps use
PIECES = SHARED / "pieces"
CACHE = ROOT / "cache"
FAVICON = "terminal"  # any file in favicons/: terminal, neural-ring, ring, board
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
STATS_VERSION = 1     # bump when game_stats changes, to rebuild the cache

PAGES = {"/": "index.html", "/index.html": "index.html", "/live": "live.html", "/live.html": "live.html",
         "/pieces": "pieces.html", "/pieces.html": "pieces.html", "/stats": "stats.html", "/stats.html": "stats.html",
         "/net": "net.html", "/net.html": "net.html",
         "/mock": "stats.html"}  # the design mockup became the dashboard; keep the old link working
# URL -> file; board.js and pieceset.js live in engine-tv/shared (the fishtest TV uses them too)
SCRIPTS = {"/board.js": SHARED / "board.js", "/pieceset.js": SHARED / "pieceset.js", "/pwa.js": ROOT / "pwa.js",
           "/shared/board.js": SHARED / "board.js", "/shared/pieceset.js": SHARED / "pieceset.js"}


# ------------------------------------------------------------------ game store

class Store:
    """Summaries + stats for every archived game, cached on disk; full games decoded on demand."""

    def __init__(self):
        CACHE.mkdir(exist_ok=True)
        self.entries = {}          # id -> (summary, stats)
        self.lock = threading.Lock()
        self.full = OrderedDict()  # small LRU of decoded games
        self.ready = False
        self.bytes = 0             # size of every archived game file

    def _time(self, path):
        try:
            return time.mktime(time.strptime(path.name[:15], "%Y%m%d-%H%M%S"))
        except ValueError:
            return path.stat().st_mtime

    def add(self, path: Path):
        if path.name in self.entries:
            return
        cf = CACHE / (path.name + ".json")
        try:
            data = json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else None
        except ValueError:
            data = None
        if not data or data.get("v") != STATS_VERSION:
            g = self.decode(path)
            summary = {
                "id": path.name,
                "game": path.name.split("_", 2)[-1].removesuffix(".gz"),
                "time": self._time(path),
                "result": g["result"],
                "positions": g["positions"],
                "opening": " ".join(p["san"] for p in g["plies"][:6]),
                "deviations": sum(1 for p in g["plies"] if p["move"] != p["best"]),
                "mismatches": g["mismatches"],
            }
            st = game_stats(g)
            summary["mode"] = st["mode"]
            data = {"v": STATS_VERSION, "summary": summary, "stats": st}
            cf.write_text(json.dumps(data), encoding="utf-8")
        size = path.stat().st_size
        with self.lock:
            if path.name not in self.entries:
                self.bytes += size  # running total, so the dashboard never re-stats the archive
            self.entries[path.name] = (data["summary"], data["stats"])

    def decode(self, path: Path):
        with self.lock:
            if path.name in self.full:
                self.full.move_to_end(path.name)
                return self.full[path.name]
        g = decode_game(path)
        g["id"] = path.name
        with self.lock:
            self.full[path.name] = g
            while len(self.full) > 48:
                self.full.popitem(last=False)
        return g

    def game(self, gid):
        path = ARCHIVE / Path(gid).name
        if not path.is_file():
            return None
        self.add(path)
        g = self.decode(path)
        g["summary"] = self.entries[path.name][0]
        return g

    def warm(self):
        for p in sorted(ARCHIVE.glob("*.gz")):
            try:
                self.add(p)
            except Exception as e:
                print("decode failed", p.name, e, flush=True)
        self.ready = True

    def all(self):
        with self.lock:
            return sorted(self.entries.values(), key=lambda e: e[0]["time"], reverse=True)


STORE = Store()


# ------------------------------------------------------------------ system info

class GpuSampler:
    """nvidia-smi every 10 s; history kept for 24 h in memory and appended to cache/gpu.jsonl."""
    FIELDS = "name,utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu,clocks.sm,fan.speed"

    def __init__(self, every=10):
        self.every = every
        self.file = CACHE / "gpu.jsonl"
        self.hist = deque(maxlen=24 * 3600 // every + 10)
        self.latest = None
        cutoff = time.time() - 24 * 3600
        if self.file.exists():
            for line in self.file.read_text(encoding="utf-8").splitlines()[-self.hist.maxlen:]:
                try:
                    s = json.loads(line)
                    if s["t"] >= cutoff:
                        self.hist.append(s)
                except ValueError:
                    pass

    def sample(self):
        try:
            out = subprocess.run(["nvidia-smi", f"--query-gpu={self.FIELDS}", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=8, creationflags=NOWIN).stdout
            name, util, mu, mt, pw, temp, clk, fan = [x.strip() for x in out.strip().splitlines()[0].split(",")]
            num = lambda x: float(x) if re.fullmatch(r"[\d.]+", x) else None
            return {"t": time.time(), "name": name, "util": num(util), "mem_used": num(mu), "mem_total": num(mt),
                    "power": num(pw), "temp": num(temp), "clock": num(clk), "fan": num(fan)}
        except Exception:
            return None

    def run(self):
        while True:
            s = self.sample()
            if s:
                self.latest = s
                self.hist.append(s)
                try:
                    with self.file.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({k: v for k, v in s.items() if k != "name"}) + "\n")
                except OSError:
                    pass
            time.sleep(self.every)

    def energy_wh(self, since):
        """Integrate power over the samples since `since` (gaps over 60 s count as off)."""
        wh, prev = 0.0, None
        for s in self.hist:
            if s["t"] < since or s.get("power") is None:
                continue
            if prev and s["t"] - prev["t"] <= 60:
                wh += (s["power"] + prev["power"]) / 2 * (s["t"] - prev["t"]) / 3600
            prev = s
        return wh


GPU = GpuSampler()


_client = {"t": 0, "v": None}
_client_version = {"v": None}


def client_info(client_dir: Path):
    """What the training client is doing right now, from the lc0 / client process command lines.
    Each check starts PowerShell (~0.5 s CPU), and this only changes when the client restarts,
    so it's refreshed every 5 minutes."""
    if time.time() - _client["t"] < 300:
        return _client["v"]
    v = {"running": False}
    try:
        ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -in 'lc0.exe','lc0-training-client.exe' } | "
              "Select-Object Name, ProcessId, CommandLine, @{n='Start';e={[DateTimeOffset]$_.CreationDate | "
              "ForEach-Object ToUnixTimeSeconds}} | ConvertTo-Json -Compress")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=20, creationflags=NOWIN).stdout.strip()
        procs = json.loads(out) if out else []
        procs = [procs] if isinstance(procs, dict) else procs
        lc0 = next((p for p in procs if p["Name"] == "lc0.exe"), None)
        cli = next((p for p in procs if p["Name"] == "lc0-training-client.exe"), None)
        v["running"] = bool(cli)
        if cli:
            v["client_start"] = cli["Start"]
            v["train_only"] = "-train-only" in (cli["CommandLine"] or "")
        if lc0:
            cmd = lc0["CommandLine"] or ""
            arg = lambda k: (re.search(rf"--{k}=(\S+)", cmd) or [None, None])[1]
            v["lc0_start"] = lc0["Start"]
            v["mode"] = "match" if "--player1.weights" in cmd else "training"
            v["parallelism"] = int(arg("parallelism") or 0) or None
            v["visits"] = int(arg("visits") or 0) or None
            v["temperature"] = arg("temperature")
            nets = re.findall(r"weights=\S*?([0-9a-f]{64})", cmd)
            v["nets"] = [n[:8] for n in nets]
            m = re.search(r"lc0-(v[\d.]+(?:-rc\d+)?)", cmd)
            v["engine"] = m.group(1) if m else None
    except Exception as e:
        v["error"] = str(e)
    if _client_version["v"] is None:
        try:
            out = subprocess.run([str(client_dir / "lc0-training-client.exe"), "-version"], capture_output=True,
                                 text=True, timeout=10, creationflags=NOWIN)
            m = re.search(r"version (\d+)", out.stdout + out.stderr)
            _client_version["v"] = m.group(1) if m else ""
        except Exception:
            _client_version["v"] = ""
    v["client_version"] = _client_version["v"] or None
    _client.update(t=time.time(), v=v)
    return v


class RankFetcher:
    """Your row on training.lczero.org/active_users, every 10 minutes. The request carries nothing
    about you: the public page is fetched and your username is matched locally."""

    def __init__(self, client_dir: Path):
        self.user = None
        try:
            self.user = json.loads((client_dir / "lc0-training-client-config.json").read_text())["User"]
        except Exception:
            pass
        self.data = None

    def fetch(self):
        req = urllib.request.Request("https://training.lczero.org/active_users", headers={"User-Agent": "lc0viz"})
        html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
        rows = re.findall(r'<tr>\s*<td><a href="/user/[^"]*">([^<]*)</a></td>\s*<td>(\d+)</td>', html)
        tot = re.search(r"(\d+) users in the last day have played (\d+) games", html)
        users = [(u, int(n)) for u, n in rows]
        me = next(((i + 1, n) for i, (u, n) in enumerate(users) if u == self.user), None)
        return {"t": time.time(), "users": int(tot.group(1)) if tot else len(users),
                "games_day": int(tot.group(2)) if tot else sum(n for _, n in users),
                "rank": me[0] if me else None, "my_games_day": me[1] if me else 0, "listed": bool(me)}

    def run(self):
        while True:
            try:
                self.data = self.fetch()
            except Exception as e:
                self.data = {**(self.data or {}), "error": str(e)}
            time.sleep(600)


# ------------------------------------------------------------------ payloads

def pacing(games, info):
    now = time.time()
    par = (info or {}).get("parallelism") or 32
    window = [s for s, _ in games if now - s["time"] < 3600]
    if len(window) < 3:
        return {"parallelism": par, "sec_per_ply": None, "game_minutes": None}
    span = max(60.0, min(3600.0, now - min(s["time"] for s, _ in games)))
    pos_rate = sum(s["positions"] for s in window) / span
    spp = par / pos_rate
    avg = sum(s["positions"] for s in window) / len(window)
    return {"parallelism": par, "sec_per_ply": round(spp, 2), "game_minutes": round(spp * avg / 60, 1)}


def topbar_stats(games, collector):
    now = time.time()
    res = {"1-0": 0, "0-1": 0, "1/2-1/2": 0}
    for s, _ in games:
        res[s["result"]] += 1
    last_hour = [s for s, _ in games if now - s["time"] < 3600]
    info = client_info(collector.client_dir)
    last_game = max((s["time"] for s, _ in games), default=None)
    return {
        "games": len(games),
        "positions": sum(s["positions"] for s, _ in games),
        "games_last_hour": len(last_hour),
        "positions_last_hour": sum(s["positions"] for s in last_hour),
        "results": res,
        "avg_plies": round(sum(s["positions"] for s, _ in games) / len(games), 1) if games else 0,
        "first_time": min((s["time"] for s, _ in games), default=None),
        "last_game_time": last_game,
        # training games are deleted right after upload, so the newest archived game is the activity signal
        "last_client_write": last_game,
        "last_scan": collector.last_scan,
        "client_dir": str(collector.client_dir),
        "gpu": GPU.latest,
        "pacing": pacing(games, info),
        "loading": not STORE.ready,
    }


_agg = {"key": None, "t": 0, "v": None}


def dashboard(collector, rank):
    games = STORE.all()
    now = time.time()
    # The aggregate walks every game, so reuse it until a new game arrives (or a minute passes,
    # so the last-hour rates keep sliding even if the client stops).
    key = (len(games), games[0][0]["id"] if games else None)
    if _agg["key"] != key or now - _agg["t"] > 60:
        _agg.update(key=key, t=now, v=aggregate(games, now))
    out = dict(_agg["v"])
    out["now"] = now
    out["loading"] = not STORE.ready
    out["totals"] = {"games": len(games), "positions": sum(s["positions"] for s, _ in games),
                     "first_time": min((s["time"] for s, _ in games), default=None),
                     "last_time": max((s["time"] for s, _ in games), default=None)}
    out["client"] = client_info(collector.client_dir)
    out["rank"] = rank.data
    out["user"] = rank.user
    hist = [s for s in GPU.hist if now - s["t"] <= 6 * 3600]
    step = max(1, len(hist) // 360)  # at most ~360 points per chart
    out["gpu"] = {
        "latest": GPU.latest,
        "history": [{k: s.get(k) for k in ("t", "util", "temp", "power", "mem_used", "clock")} for s in hist[::step]],
        "energy_wh_24h": GPU.energy_wh(now - 24 * 3600),
        "energy_wh_tracked": GPU.energy_wh(0),
        "tracked_since": GPU.hist[0]["t"] if GPU.hist else None,
        "avg_util_1h": _avg([s["util"] for s in GPU.hist if now - s["t"] <= 3600]),
        "avg_power_1h": _avg([s["power"] for s in GPU.hist if now - s["t"] <= 3600]),
        "max_temp_24h": max((s["temp"] or 0 for s in GPU.hist), default=None),
    }
    out["storage"] = {"archive_mb": STORE.bytes / 1e6, "files": len(games)}
    return out


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# ------------------------------------------------------------------ client control (pause / resume)

_control_lock = threading.Lock()


def client_running():
    """Fast check (tasklist, ~0.1 s) of the training client and lc0. client_info() is cached for 5 minutes,
    too slow to reflect a pause/resume button."""
    def up(image):
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=10, creationflags=NOWIN).stdout
        return image.lower() in out.lower()
    return {"client": up("lc0-training-client.exe"), "lc0": up("lc0.exe")}


def control_client(action):
    """Pause or resume through leela.ps1, the same script as the `leela` command, so both behave the same.
    'stop' (not 'stop all') never touches the dashboard itself."""
    shell = "pwsh" if subprocess.run(["where", "pwsh"], capture_output=True, creationflags=NOWIN).returncode == 0 else "powershell"
    arg = {"pause": "stop", "resume": "start"}[action]
    with _control_lock:
        p = subprocess.run([shell, "-NoProfile", "-File", str(ROOT / "leela.ps1"), arg],
                           capture_output=True, text=True, timeout=60, creationflags=NOWIN)
        _client["t"] = 0  # make the next client_info() re-read the process list
        out = re.sub(r"\x1b\[[0-9;]*m", "", p.stdout + p.stderr).strip()
        return {"ok": p.returncode == 0, "output": out, **client_running()}


# ------------------------------------------------------------------ http

class Handler(BaseHTTPRequestHandler):
    collector = None
    rank = None
    net = None

    def log_message(self, *a):
        pass

    def _send(self, body: bytes, ctype: str, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(json.dumps(obj).encode(), "application/json", code)

    def do_POST(self):
        path = unquote(self.path.split("?")[0])
        if path in ("/api/client/pause", "/api/client/resume"):
            # Only the dashboard's own page sends this header. A cross-site page can't add it without a CORS
            # preflight, which this server never approves, so other websites can't pause or resume the client.
            if self.headers.get("X-Lc0viz") != "1":
                return self._json({"error": "missing X-Lc0viz header"}, 403)
            return self._json(control_client(path.rsplit("/", 1)[1]))
        self._send(b"not found", "text/plain", 404)

    def do_GET(self):
        path = unquote(self.path.split("?")[0])
        if path == "/api/client":
            return self._json(client_running())
        if path in PAGES:
            return self._send((ROOT / PAGES[path]).read_bytes(), "text/html; charset=utf-8")
        if path in SCRIPTS:
            return self._send(SCRIPTS[path].read_bytes(), "text/javascript; charset=utf-8")
        if path == "/shared/theme.css":
            return self._send((SHARED / "theme.css").read_bytes(), "text/css; charset=utf-8")
        m = re.fullmatch(r"/pieces/([a-z0-9-]+)/([wb][KQRBNP])\.(svg|webp)", path)
        if m:
            f = PIECES / m.group(1) / f"{m.group(2)}.{m.group(3)}"
            if f.is_file():
                return self._send(f.read_bytes(), "image/svg+xml" if m.group(3) == "svg" else "image/webp")
        if path == "/manifest.webmanifest":
            return self._send((ROOT / "manifest.webmanifest").read_bytes(), "application/manifest+json")
        if path == "/sw.js":  # served from the root so its scope covers every page
            return self._send((ROOT / "sw.js").read_bytes(), "text/javascript; charset=utf-8")
        m = re.fullmatch(r"/icons/([a-z0-9-]+\.png)", path)
        if m and (ROOT / "icons" / m.group(1)).is_file():
            return self._send((ROOT / "icons" / m.group(1)).read_bytes(), "image/png")
        if path in ("/favicon.svg", "/favicon.ico"):  # .ico: browsers ask for it by default
            return self._send((ROOT / "favicons" / f"{FAVICON}.svg").read_bytes(), "image/svg+xml")
        if path == "/api/piecesets":
            return self._send((PIECES / "sets.json").read_bytes(), "application/json")
        if path == "/api/games":
            games = STORE.all()
            return self._json({"games": [s for s, _ in games[:300]], "stats": topbar_stats(games, self.collector)})
        if path == "/api/dashboard":
            return self._json(dashboard(self.collector, self.rank))
        if path.startswith("/api/game/"):
            g = STORE.game(path[len("/api/game/"):])
            if g:
                return self._json(g)
        if path.startswith("/api/net/"):
            return self._net(path[len("/api/net/"):], {k: v[0] for k, v in parse_qs(self.path.partition("?")[2]).items()})
        self._send(b"not found", "text/plain", 404)

    def _net(self, op, q):
        net = self.net
        try:
            if op == "status":
                return self._json(net.status())
            if op == "prepare":
                net.prepare_async()
                return self._json(net.status())
            if op == "stop":
                net.stop()
                return self._json(net.status())
            if op == "eval":
                f = ARCHIVE / Path(q["game"]).name
                if not f.is_file():
                    return self._json({"error": "unknown game"}, 404)
                return self._json(net.evaluate(f, int(q.get("ply", 0))))
            num = lambda k: int(q[k])
            if op == "neuron":
                return self._json(net.slice("neuron", q["key"], ARCHIVE, kind=q["kind"], layer=num("layer"), neuron=num("neuron")))
            if op == "top":
                return self._json(net.slice("top", q["key"], ARCHIVE, kind=q["kind"], layer=num("layer"), token=num("token")))
            if op == "attn":
                return self._json(net.slice("attn", q["key"], ARCHIVE, layer=num("layer"), token=num("token")))
            if op == "pmap":
                return self._json(net.slice("pmap", q["key"], ARCHIVE, token=num("token")))
        except RuntimeError as e:
            code = 202 if str(e) == "preparing" else 500
            return self._json({"error": str(e), "status": net.status()}, code)
        except (KeyError, ValueError) as e:
            return self._json({"error": f"bad request: {e}"}, 400)
        self._send(b"not found", "text/plain", 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-dir", default=str(DEFAULT_CLIENT_DIR))
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    c = Collector(args.client_dir)

    def on_new(p):
        print("archived", p.name, flush=True)
        try:
            STORE.add(p)
        except Exception as e:
            print("decode failed", p.name, e, flush=True)
    c.on_new = on_new
    c.start()
    rank = RankFetcher(Path(args.client_dir))
    for target in (STORE.warm, GPU.run, rank.run):
        threading.Thread(target=target, daemon=True).start()
    Handler.collector, Handler.rank = c, rank
    Handler.net = NetHelper(Path(args.client_dir), lambda: client_info(Path(args.client_dir)))
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"lc0viz on http://127.0.0.1:{args.port}  (watching {args.client_dir})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
