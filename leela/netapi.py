"""Server side of the Net explorer: finds the net lc0 is using, prepares it once, and runs
networker.py as a helper process only while the page is being used (it exits after 5 idle minutes)."""
import base64
import ctypes
import gzip
import json
import math
import subprocess
import sys
import threading
import time
from pathlib import Path

from decoder import (RECORD, parse_record, input_planes, idx_to_uci, normalize_castling, san,
                     fen_placement)

ROOT = Path(__file__).resolve().parent
NETS = ROOT / "nets"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _working_set_mb(pid):
    """Resident memory of another process (Windows), or None."""
    try:
        from ctypes import wintypes as wt

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD)] + \
                       [(n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                                       "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                                       "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        k32.OpenProcess.restype = wt.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        c = PMC(); c.cb = ctypes.sizeof(c)
        ok = psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
        k32.CloseHandle(h)
        return round(c.WorkingSetSize / 2**20) if ok else None
    except Exception:
        return None


class NetHelper:
    def __init__(self, client_dir: Path, client_info):
        self.client_dir = Path(client_dir)
        self.client_info = client_info   # callable -> dict with "nets" (short shas) from the lc0 command line
        self.proc = None
        self.proc_model = None
        self.lock = threading.Lock()
        self.prep = {"state": "idle", "net": None, "error": None, "t": None}
        NETS.mkdir(exist_ok=True)

    # ---------------------------------------------------------------- which net
    def current_weights(self):
        cache = self.client_dir / "client-cache"
        files = [p for p in cache.glob("*") if p.is_file() and len(p.name) == 64 and p.stat().st_size > 1_000_000]
        info = self.client_info() or {}
        for short in info.get("nets") or []:
            for p in files:
                if p.name.startswith(short):
                    return p, "in use by lc0"
        if files:  # lc0 not running: newest fully downloaded net
            return max(files, key=lambda p: p.stat().st_mtime), "newest downloaded"
        return None, None

    def model_path(self, weights: Path):
        return NETS / f"{weights.name[:8]}.onnx"

    # ---------------------------------------------------------------- status
    def status(self):
        w, why = self.current_weights()
        out = {"venv": VENV_PY.exists(), "net": w.name[:8] if w else None, "net_source": why,
               "prepared": bool(w and self.model_path(w).exists()), "prep": self.prep,
               "helper": None}
        p = self.proc
        if p and p.poll() is None:
            out["helper"] = {"pid": self.real_pid, "mem_mb": _working_set_mb(self.real_pid), "model": self.proc_model.name,
                             "up_s": round(time.time() - self.started)}
        return out

    def prepare_async(self):
        w, _ = self.current_weights()
        if not w or not VENV_PY.exists():
            return
        out = self.model_path(w)
        if out.exists() or self.prep["state"] == "preparing":
            return
        self.prep = {"state": "preparing", "net": w.name[:8], "error": None, "t": time.time()}

        def run():
            lc0 = self.client_dir / "lc0.exe"
            p = subprocess.run([str(VENV_PY), str(ROOT / "networker.py"), "prepare", str(lc0), str(w), str(out)],
                               capture_output=True, text=True, creationflags=NOWIN)
            if p.returncode == 0 and out.exists():
                self.prep = {"state": "done", "net": w.name[:8], "error": None, "t": time.time()}
                # keep this net and the previous one; each prepared net is ~0.7 GB
                old = sorted(NETS.glob("*.onnx"), key=lambda f: f.stat().st_mtime, reverse=True)[2:]
                for f in old:
                    if not (self.proc_model and f == self.proc_model and self.proc and self.proc.poll() is None):
                        f.unlink(missing_ok=True)
            else:
                self.prep = {"state": "error", "net": w.name[:8], "error": (p.stdout + p.stderr)[-500:], "t": time.time()}
        threading.Thread(target=run, daemon=True).start()

    # ---------------------------------------------------------------- helper process
    def _ensure_proc(self, model: Path):
        if self.proc and self.proc.poll() is None and self.proc_model == model:
            return
        if self.proc and self.proc.poll() is None:
            self._quit()
        self.proc = subprocess.Popen([str(VENV_PY), str(ROOT / "networker.py"), "serve", str(model)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, bufsize=1, creationflags=NOWIN)
        self.proc_model = model
        ready = json.loads(self.proc.stdout.readline() or "{}")
        if not ready.get("ready"):
            raise RuntimeError("net helper failed to start")
        self.real_pid = ready.get("pid", self.proc.pid)
        self.started = time.time()

    def _quit(self):
        try:
            self.proc.stdin.write('{"op": "quit"}\n'); self.proc.stdin.flush()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()

    def call(self, model: Path, **req):
        with self.lock:
            for attempt in (1, 2):
                self._ensure_proc(model)
                try:
                    self.proc.stdin.write(json.dumps(req) + "\n"); self.proc.stdin.flush()
                    line = self.proc.stdout.readline()
                    if line:
                        return json.loads(line)
                except (BrokenPipeError, OSError):
                    pass
                self.proc = None  # it exited (idle timeout) between requests: start a fresh one
            raise RuntimeError("net helper stopped responding")

    def stop(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                self._quit()
            self.proc = None

    # ---------------------------------------------------------------- requests
    def ready_model(self):
        w, _ = self.current_weights()
        if not w:
            raise RuntimeError("no network found in the client's cache")
        m = self.model_path(w)
        if not m.exists():
            self.prepare_async()
            raise RuntimeError("preparing")
        return m

    def evaluate(self, archive_file: Path, ply: int):
        model = self.ready_model()
        data = gzip.decompress(archive_file.read_bytes())
        n = len(data) // RECORD
        ply = max(0, min(n - 1, ply))
        off = ply * RECORD
        rec = parse_record(data, off)
        key = f"{archive_file.name}:{ply}:{model.stem}"
        r = self.call(model, op="eval", key=key, planes_b64=base64.b64encode(input_planes(data, off)).decode())
        if not r.get("ok"):
            raise RuntimeError(r.get("error"))
        board, black = rec["board"], rec["black"]
        legal = [j for j, p in enumerate(rec["probs"]) if p >= 0]
        logits = [r["policy"][j] for j in legal]
        mx = max(logits)
        ex = [math.exp(v - mx) for v in logits]
        tot = sum(ex)

        def move(j):
            u = normalize_castling(board, idx_to_uci(j, black))
            return {"uci": u, "san": san(board, u)}
        raw = sorted(((ex[k] / tot, legal[k]) for k in range(len(legal))), reverse=True)[:8]
        srch = sorted(((rec["probs"][j], j) for j in legal), reverse=True)[:8]
        played = normalize_castling(board, idx_to_uci(rec["played_idx"], black))
        sign = -1 if black else 1  # report values from White's side, like the rest of the app
        w, d, l = r["wdl"]
        return {
            "key": key, "net": model.stem, "ms": r["ms"], "ply": ply, "plies": n,
            "fen": fen_placement(board), "white_to_move": not black,
            "played": {"uci": played, "san": san(board, played)},
            "raw_policy": [{**move(j), "p": round(p, 4)} for p, j in raw],
            "search_policy": [{**move(j), "p": round(p, 4)} for p, j in srch],
            "raw_wdl_white": [w, d, l] if not black else [l, d, w],
            "raw_q": round(sign * (w - l), 4), "search_q": round(sign * rec["root_q"], 4), "search_d": round(rec["root_d"], 4),
            "raw_mlh": round(r["mlh"], 1), "search_mlh": round(rec["root_m"], 1), "actual_left": n - ply,
            "visits": rec["visits"],
            "layers": r["layers"], "heads": r["heads"], "d_model": r["d_model"], "d_ffn": r["d_ffn"],
            "resid_norm": r["resid_norm"], "resid_delta": r["resid_delta"],
            "ffn_active": r["ffn_active"], "ffn_mean": r["ffn_mean"],
            "attn_entropy": r["attn_entropy"],
        }

    def slice(self, op, key, archive: Path, **kw):
        fname, ply, net = key.rsplit(":", 2)
        model = NETS / (net + ".onnx")
        r = self.call(model, op=op, key=key, **kw)
        if not r.get("ok") and "not loaded" in (r.get("error") or ""):
            # the helper restarted (idle exit) or dropped this position from its small cache: recompute it
            self.evaluate(archive / fname, int(ply))
            r = self.call(model, op=op, key=key, **kw)
        if not r.get("ok"):
            raise RuntimeError(r.get("error"))
        return r
