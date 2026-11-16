"""Copy finished Lc0 training-client games into ./archive before the client uploads and deletes them.

Read-only toward the client folder: it never writes, locks or deletes anything there.
"""
import gzip
import hashlib
import os
import shutil
import threading
import time
from pathlib import Path

RECORD = 8356  # bytes per position in a v6 training chunk

def find_client_dir():
    """The training client's folder: LC0_CLIENT_DIR if set, otherwise the newest lc0 release unpacked in
    Downloads that contains lc0-training-client.exe (e.g. Downloads\\lc0-v0.33.0-rc0-windows-gpu-nvidia-cuda12)."""
    if os.environ.get("LC0_CLIENT_DIR"):
        return Path(os.environ["LC0_CLIENT_DIR"])
    found = sorted(Path.home().glob("Downloads/lc0-*/lc0-training-client.exe"), key=lambda p: p.stat().st_mtime)
    return found[-1].parent if found else Path.home() / "Downloads"


DEFAULT_CLIENT_DIR = find_client_dir()
ARCHIVE = Path(__file__).resolve().parent / "archive"


def data_dirs(client_dir: Path):
    return [p for p in client_dir.glob("data-*") if p.is_dir()]


class Collector:
    # Training games are uploaded and deleted within seconds of finishing (match games stay until the
    # match ends), so scan often and copy as soon as the gzip stream is complete; a half-written file
    # fails to decompress and is retried on the next scan.
    def __init__(self, client_dir=DEFAULT_CLIENT_DIR, archive=ARCHIVE, interval=0.25, stable=0.0):
        self.client_dir = Path(client_dir)
        self.archive = Path(archive)
        self.archive.mkdir(exist_ok=True)
        self.interval = interval
        self.stable = stable
        self.seen = {}  # src path -> (size, mtime) already archived
        self.hashes = {self._hash(p.read_bytes()) for p in self.archive.glob("*.gz")}
        self.on_new = None  # callback(path)
        self.last_scan = 0.0
        self.copied = 0

    @staticmethod
    def _hash(b: bytes) -> str:
        return hashlib.sha1(b).hexdigest()

    def scan_once(self):
        now = time.time()
        for d in data_dirs(self.client_dir):
            for src in d.glob("game_*.gz"):
                try:
                    st = src.stat()
                    key = (st.st_size, st.st_mtime)
                    if self.seen.get(str(src)) == key or now - st.st_mtime < self.stable:
                        continue
                    raw = src.read_bytes()
                    data = gzip.decompress(raw)
                except (OSError, EOFError, gzip.BadGzipFile):
                    continue  # vanished (uploaded) or still being written
                if not data or len(data) % RECORD:
                    continue
                self.seen[str(src)] = key
                h = self._hash(raw)
                if h in self.hashes:
                    continue
                self.hashes.add(h)
                stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(st.st_mtime))
                dst = self.archive / f"{stamp}_{h[:8]}_{src.name}"
                tmp = dst.with_suffix(".part")
                tmp.write_bytes(raw)
                os.replace(tmp, dst)
                self.copied += 1
                if self.on_new:
                    self.on_new(dst)
        self.last_scan = now

    def run_forever(self):
        while True:
            try:
                self.scan_once()
            except Exception as e:  # keep collecting whatever happens
                print("collector error:", e, flush=True)
            time.sleep(self.interval)

    def start(self):
        t = threading.Thread(target=self.run_forever, daemon=True)
        t.start()
        return t


if __name__ == "__main__":
    c = Collector()
    c.on_new = lambda p: print("archived", p.name, flush=True)
    c.run_forever()
