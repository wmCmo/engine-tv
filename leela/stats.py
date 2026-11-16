"""Per-game statistics (computed once per game, cached on disk) and their aggregation for /stats."""
import time
from collections import Counter, defaultdict

from decoder import sq

STARTPOS = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
CAL_BINS = 10      # value-head calibration: side-to-move Q in 10 bins over [-1, 1]
DRAW_BINS = 10     # draw-head calibration: predicted D in 10 bins over [0, 1]
ML_BUCKET = 20     # moves-left error, bucketed by actual plies remaining
ML_BUCKETS = 11    # 0-19, 20-39, ... 200+
PIECE_VAL = {"p": 1, "n": 3, "b": 3, "r": 5, "q": 9, "k": 0}


def game_stats(g):
    """Everything the dashboard needs from one decoded game (small, JSON-serialisable)."""
    plies = g["plies"]
    n = len(plies)
    res_white = {"1-0": 1, "0-1": -1}.get(g["result"], 0)
    # Match games run at temperature 0 and almost never leave the search's best move early on;
    # training games use temperature, so they do (0-1 vs 3+ off-best in the first 20 plies on real data).
    early_off = sum(1 for p in plies[:20] if p["move"] != p["best"])
    mode = "training" if early_off >= 3 else "match"

    captures = checks = 0
    castles = {"w_short": 0, "w_long": 0, "b_short": 0, "b_long": 0}
    promotions = []
    pieces = Counter()
    dest = [0] * 64
    cal = [[0, 0.0, 0.0] for _ in range(CAL_BINS)]      # n, sum predicted score, sum actual score
    draw = [[0, 0.0, 0] for _ in range(DRAW_BINS)]      # n, sum predicted D, actual draws
    ml = [[0, 0.0, 0.0] for _ in range(ML_BUCKETS)]     # n, sum |err|, sum signed err (pred - actual)
    top_share = kld = legal = visits = 0.0
    off_best = 0
    lead_changes, last_sign = 0, 0
    for i, p in enumerate(plies):
        s = p["san"]
        wtm = p["white_to_move"]
        if "x" in s:
            captures += 1
        if "+" in s:
            checks += 1
        if s.startswith("O-O"):
            castles[("w_" if wtm else "b_") + ("long" if s.startswith("O-O-O") else "short")] += 1
            pieces["K"] += 1
        else:
            pieces[s[0] if s[0] in "KQRBN" else "P"] += 1
        if "=" in s:
            promotions.append(s.split("=")[1][0])
        dest[sq(p["move"][2:4])] += 1
        if p["move"] != p["best"]:
            off_best += 1
        # calibration, all from the side to move
        q_stm = p["q"] if wtm else -p["q"]
        r_stm = res_white if wtm else -res_white
        b = min(CAL_BINS - 1, int((q_stm + 1) / 2 * CAL_BINS))
        cal[b][0] += 1; cal[b][1] += (q_stm + 1) / 2; cal[b][2] += (r_stm + 1) / 2
        db = min(DRAW_BINS - 1, max(0, int(p["d"] * DRAW_BINS)))
        draw[db][0] += 1; draw[db][1] += p["d"]; draw[db][2] += 1 if res_white == 0 else 0
        remaining = n - i
        mb = min(ML_BUCKETS - 1, remaining // ML_BUCKET)
        err = p["m"] - remaining
        ml[mb][0] += 1; ml[mb][1] += abs(err); ml[mb][2] += err
        top_share += p["cands"][0]["p"] if p["cands"] else 0
        kld += p["kld"]; legal += p["legal"]; visits += p["visits"]
        sign = 1 if p["q"] > 0.25 else -1 if p["q"] < -0.25 else 0
        if sign and last_sign and sign != last_sign:
            lead_changes += 1
        if sign:
            last_sign = sign
    qs = [p["q"] for p in plies]
    # biggest comeback: the winner's worst eval (from the winner's side) in a game they still won
    worst_for_winner = min(q * res_white for q in qs) if res_white and qs else None
    final_material = sum(PIECE_VAL[c.lower()] for c in g["final_fen"] if c.isalpha())
    return {
        "mode": mode, "result": g["result"], "plies": n,
        "captures": captures, "checks": checks, "castles": castles, "promotions": promotions,
        "pieces": dict(pieces), "dest": dest, "cal": cal, "draw": draw, "ml": ml,
        "top_share": top_share / n if n else 0, "kld": kld / n if n else 0,
        "legal": legal / n if n else 0, "visits": visits / n if n else 0,
        "off_best": off_best, "lead_changes": lead_changes,
        "max_abs_q": max((abs(q) for q in qs), default=0),
        "worst_for_winner": worst_for_winner,
        "from_startpos": g["start_fen"] == STARTPOS,
        "first_move": plies[0]["san"] if plies else "",
        "final_material": final_material,
    }


def _bucket(t, size):
    return int(t // size * size)


def aggregate(entries, now=None):
    """entries: list of (summary, stats). Returns the /api/dashboard payload (minus live system info)."""
    now = now or time.time()
    modes = ("training", "match")
    out = {"modes": {}}
    by_mode = defaultdict(list)
    for s, st in entries:
        by_mode[st["mode"]].append((s, st))
    for m in modes + ("all",):
        es = entries if m == "all" else by_mode[m]
        if not es:
            out["modes"][m] = None
            continue
        res = Counter(st["result"] for _, st in es)
        lengths = sorted(st["plies"] for _, st in es)
        npos = sum(lengths)
        def avg(key):
            return sum(st[key] for _, st in es) / len(es)
        def wavg(key):  # per-position average weighted by game length
            return sum(st[key] * st["plies"] for _, st in es) / npos
        out["modes"][m] = {
            "games": len(es), "positions": npos,
            "results": {"1-0": res["1-0"], "1/2-1/2": res["1/2-1/2"], "0-1": res["0-1"]},
            "plies_avg": npos / len(es), "plies_median": lengths[len(lengths) // 2],
            "plies_min": lengths[0], "plies_max": lengths[-1],
            "captures_per_game": avg("captures"), "checks_per_game": avg("checks"),
            "lead_changes_per_game": avg("lead_changes"),
            "top_share": wavg("top_share"), "kld": wavg("kld"), "legal": wavg("legal"), "visits": wavg("visits"),
            "off_best_rate": sum(st["off_best"] for _, st in es) / npos,
            "decisive_rate": (res["1-0"] + res["0-1"]) / len(es),
        }
    allst = [st for _, st in entries]
    if not allst:
        return out

    # time series: 10-minute buckets over the last 24 h, games and positions per mode
    size = 600
    start = _bucket(now - 24 * 3600, size)
    first = min((s["time"] for s, _ in entries), default=now)
    start = max(start, _bucket(first, size))
    nb = int((_bucket(now, size) - start) // size) + 1
    series = {m: {"games": [0] * nb, "positions": [0] * nb} for m in modes}
    draws_hour = defaultdict(lambda: [0, 0])
    for s, st in entries:
        if s["time"] >= start:
            k = int((s["time"] - start) // size)
            if 0 <= k < nb:
                series[st["mode"]]["games"][k] += 1
                series[st["mode"]]["positions"][k] += st["plies"]
        h = _bucket(s["time"], 3600)
        draws_hour[h][0] += 1
        draws_hour[h][1] += st["result"] == "1/2-1/2"
    out["throughput"] = {"start": start, "size": size, "series": series}
    out["draw_rate_hourly"] = [[h, d / g, g] for h, (g, d) in sorted(draws_hour.items())]

    # rates over the last hour (or since the first game, if newer)
    window = [(s, st) for s, st in entries if now - s["time"] < 3600]
    span = max(60.0, min(3600.0, now - first))
    out["rates"] = {
        "games_per_hour": len(window) * 3600 / span,
        "positions_per_hour": sum(st["plies"] for _, st in window) * 3600 / span,
        "positions_per_sec": sum(st["plies"] for _, st in window) / span,
        "visits_per_sec": sum(st["plies"] * st["visits"] for _, st in window) / span,
        "window_games": len(window),
    }

    # length histogram, 10-ply bins, stacked by mode
    hb = 10
    maxlen = max(st["plies"] for st in allst)
    nh = maxlen // hb + 1
    hist = {m: [0] * nh for m in modes}
    for st in allst:
        hist[st["mode"]][st["plies"] // hb] += 1
    out["length_hist"] = {"bin": hb, "series": hist}

    # calibration and moves-left, summed over every position
    def sum_bins(key, width):
        acc = [[0, 0.0, 0.0] for _ in range(width)]
        for st in allst:
            for i, row in enumerate(st[key]):
                for j in range(3):
                    acc[i][j] += row[j]
        return acc
    out["calibration"] = [[n, sp / n, sa / n] if n else [0, None, None] for n, sp, sa in sum_bins("cal", CAL_BINS)]
    out["draw_calibration"] = [[n, sp / n, sa / n] if n else [0, None, None] for n, sp, sa in sum_bins("draw", DRAW_BINS)]
    out["moves_left"] = {"bucket": ML_BUCKET,
                         "rows": [[n, a / n, e / n] if n else [0, None, None] for n, a, e in sum_bins("ml", ML_BUCKETS)]}

    # board & move habits
    dest = [0] * 64
    pieces = Counter()
    castles = Counter()
    promos = Counter()
    for st in allst:
        for i, v in enumerate(st["dest"]):
            dest[i] += v
        pieces.update(st["pieces"])
        castles.update(st["castles"])
        promos.update(st["promotions"])
    out["dest_heatmap"] = dest
    out["piece_moves"] = {k: pieces.get(k, 0) for k in "PNBRQK"}
    games = len(allst)
    out["castling"] = {k: castles.get(k, 0) / games for k in ("w_short", "w_long", "b_short", "b_long")}
    out["promotions"] = {k: promos.get(k, 0) for k in "QNRB"}

    # first moves from the standard start (training games start there; match games start from a book)
    fm = defaultdict(lambda: [0, 0.0])
    for st in allst:
        if st["from_startpos"]:
            fm[st["first_move"]][0] += 1
            fm[st["first_move"]][1] += {"1-0": 1, "1/2-1/2": 0.5}.get(st["result"], 0)
    out["first_moves"] = sorted(([k, n, sc / n] for k, (n, sc) in fm.items()), key=lambda r: -r[1])[:10]

    # records, each linked to its game
    def rec(label, pick, value, fmt):
        if not pick:
            return None
        s, st = pick
        return {"label": label, "id": s["id"], "game": s["game"], "value": value(st), "fmt": fmt}
    decisive = [e for e in entries if e[1]["result"] != "1/2-1/2"]
    comeback = [e for e in decisive if e[1]["worst_for_winner"] is not None]
    out["records"] = [r for r in [
        rec("Longest game", max(entries, key=lambda e: e[1]["plies"]), lambda st: st["plies"], "plies"),
        rec("Shortest decisive game", min(decisive, key=lambda e: e[1]["plies"]) if decisive else None, lambda st: st["plies"], "plies"),
        rec("Biggest comeback", min(comeback, key=lambda e: e[1]["worst_for_winner"]) if comeback else None,
            lambda st: st["worst_for_winner"], "q"),
        rec("Most lead changes", max(entries, key=lambda e: e[1]["lead_changes"]), lambda st: st["lead_changes"], "count"),
        rec("Most captures", max(entries, key=lambda e: e[1]["captures"]), lambda st: st["captures"], "count"),
        rec("Most checks", max(entries, key=lambda e: e[1]["checks"]), lambda st: st["checks"], "count"),
        rec("Most search deviations", max(entries, key=lambda e: e[1]["off_best"] / max(1, e[1]["plies"])),
            lambda st: st["off_best"] / max(1, st["plies"]), "pct"),
    ] if r]
    under = [(s, st) for s, st in entries if any(p != "Q" for p in st["promotions"])]
    out["underpromotions"] = [{"id": s["id"], "game": s["game"], "pieces": [p for p in st["promotions"] if p != "Q"]}
                              for s, st in sorted(under, key=lambda e: -e[0]["time"])[:8]]
    return out
