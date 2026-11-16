"""Download piece sets from lichess-org/lila into ./pieces/<set>/ and write pieces/sets.json.

Only sets whose author and licence are listed in lila's COPYING.md are included; sets listed without
a licence (governor, kosal, reillycraig, riohacha) are left out, as are mono (one shape for
both colours) and disguised (blank pieces by design). Re-running skips files already there.
"""
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "pieces"
BASE = "https://raw.githubusercontent.com/lichess-org/lila/master/public/piece"
PIECES = [c + p for c in "wb" for p in "KQRBNP"]

# name: (author, licence) — copied from lila's COPYING.md
SETS = {
    "cburnett": ("Colin M.L. Burnett", "GPLv2+"),
    "merida": ("Armando Hernandez Marroquin", "GPLv2+"),
    "chessnut": ("Alexis Luengas", "Apache 2.0"),
    "letter": ("usolando", "AGPLv3+"),
    "pirouetti": ("pirouetti", "AGPLv3+"),
    "pixel": ("therealqtpi", "AGPLv3+"),
    "shapes": ("flugsio", "CC BY-SA 4.0"),
    "rhosgfx": ("RhosGFX", "CC0 1.0"),
    "california": ("Jerry S.", "CC BY-NC-SA 4.0"),
    "caliente": ("avi", "CC BY-NC-SA 4.0"),
    "maestro": ("sadsnake1", "CC BY-NC-SA 4.0"),
    "fantasy": ("Maurizio Monge", "MIT"),
    "spatial": ("Maurizio Monge", "MIT"),
    "celtic": ("Maurizio Monge", "MIT"),
    "fresca": ("sadsnake1", "CC BY-NC-SA 4.0"),
    "cardinal": ("sadsnake1", "CC BY-NC-SA 4.0"),
    "icpieces": ("sadsnake1", "CC BY-NC-SA 4.0"),
    "gioco": ("sadsnake1", "CC BY-NC-SA 4.0"),
    "tatiana": ("sadsnake1", "CC BY-NC-SA 4.0"),
    "staunty": ("sadsnake1", "CC BY-NC-SA 4.0"),
    "dubrovny": ("sadsnake1", "CC BY-NC-SA 4.0"),
    "anarcandy": ("caderek", "CC BY-NC-SA 4.0"),
    "kiwen-suwi": ("neverRare", "CC BY 4.0"),
    "mpchess": ("Maxime Chupin", "GPLv3+"),
    "cooke": ("fejfar", "CC BY-NC-SA 4.0"),
    "monarchy": ("slither77", "CC BY-NC-SA 4.0"),
    "xkcd": ("Randall Munroe", "CC BY-NC-SA 2.5"),
    "firi": ("James Faure", "CC BY 4.0"),
    "minimal-warmth": ("blunder_reign", "CC BY-NC-SA 4.0"),
    "horsey": ("cham, michael1241", "CC BY-NC-SA 4.0"),
    "totoy": ("Kosal Sen", "CC BY 4.0"),
    "papercut": ("Nikolay Anzarov", "CC BY 4.0"),
    "alpha": ("Eric Bentzen", "free for personal non-commercial use"),
    "chess7": ("Style-7", "freeware"),
    "companion": ("David L. Brown", "freeware"),
    "leipzig": ("Armando Hernandez Marroquin", "freeware"),
    "shahi-ivory-brown": ("Tamer Karatekin", "Şahî font licence (free, no modification)"),
}


def main():
    ok = {}
    for name, (author, lic) in SETS.items():
        d = ROOT / name
        d.mkdir(parents=True, exist_ok=True)
        good, ext = True, "svg"
        for p in PIECES:
            have = [f for f in (d / f"{p}.svg", d / f"{p}.webp") if f.exists() and f.stat().st_size > 0]
            if have:
                ext = have[0].suffix[1:]
                continue
            for ext in ("svg", "webp"):  # most sets are SVG; a few (monarchy) ship webp
                try:
                    with urllib.request.urlopen(f"{BASE}/{name}/{p}.{ext}", timeout=20) as r:
                        data = r.read()
                except Exception:
                    continue
                if (ext == "svg" and b"<svg" in data[:4000]) or (ext == "webp" and data[8:12] == b"WEBP"):
                    (d / f"{p}.{ext}").write_bytes(data)
                    break
            else:
                print(f"  {name}/{p}: no usable file")
                good = False
        if good:
            ok[name] = {"author": author, "license": lic, "ext": ext}
        print(("ok   " if good else "FAIL ") + name, flush=True)
    (ROOT / "sets.json").write_text(json.dumps(ok, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(ok)} sets written to pieces/sets.json")


if __name__ == "__main__":
    main()
