"""Decode Lc0 v6 training chunks (input format 1) into replayable games."""
import gzip
import struct
from pathlib import Path

RECORD = 8356
FILES = "abcdefgh"

# v6 layout after probs[1858] (4+4+7432 bytes) and planes[104] u64 (832 bytes)
_TAIL = struct.Struct("<4B4B7f2f3f3fI2HfI")
_HEAD = struct.Struct("<II")
assert _HEAD.size + 1858 * 4 + 104 * 8 + _TAIL.size == RECORD


def sq(name):
    return FILES.index(name[0]) + 8 * (int(name[1]) - 1)


def sqname(s):
    return FILES[s % 8] + str(s // 8 + 1)


def _build_policy_table():
    """Lc0's 1858-move policy index: queen-line + knight moves per from-square
    (sorted by to-square), then rank-7 underpromotions to q/r/b (knight = plain move)."""
    moves = []
    for f in range(64):
        fx, fy = f % 8, f // 8
        tos = set()
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]:
            x, y = fx + dx, fy + dy
            while 0 <= x < 8 and 0 <= y < 8:
                tos.add(x + 8 * y)
                x, y = x + dx, y + dy
        for dx, dy in [(1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1)]:
            x, y = fx + dx, fy + dy
            if 0 <= x < 8 and 0 <= y < 8:
                tos.add(x + 8 * y)
        moves += [sqname(f) + sqname(t) for t in sorted(tos)]
    for fx in range(8):
        for tx in (fx - 1, fx, fx + 1):
            if 0 <= tx < 8:
                for p in "qrb":
                    moves.append(f"{FILES[fx]}7{FILES[tx]}8{p}")
    assert len(moves) == 1858, len(moves)
    return moves


POLICY = _build_policy_table()


def flip_uci(m):
    return m[0] + str(9 - int(m[1])) + m[2] + str(9 - int(m[3])) + m[4:]


def _plane_squares(v):
    """Training planes store each rank byte with its bits reversed (MSB = a-file)."""
    out = []
    for rank in range(8):
        byte = (v >> (8 * rank)) & 0xFF
        for file in range(8):
            if byte & (0x80 >> file):
                out.append(file + 8 * rank)
    return out


# ---------------------------------------------------------------- tiny chess
# board: list of 64, '.' or piece letter (upper = white)

def _attacks(board, s, piece):
    x, y = s % 8, s // 8
    p = piece.lower()
    out = []
    if p == "p":
        d = 1 if piece.isupper() else -1
        for dx in (-1, 1):
            if 0 <= x + dx < 8 and 0 <= y + d < 8:
                out.append(x + dx + 8 * (y + d))
        return out
    if p == "n":
        steps, slide = [(1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1)], False
    elif p == "k":
        steps, slide = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)], False
    else:
        steps = []
        if p in "rq":
            steps += [(1, 0), (-1, 0), (0, 1), (0, -1)]
        if p in "bq":
            steps += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
        slide = True
    for dx, dy in steps:
        nx, ny = x + dx, y + dy
        while 0 <= nx < 8 and 0 <= ny < 8:
            t = nx + 8 * ny
            out.append(t)
            if not slide or board[t] != ".":
                break
            nx, ny = nx + dx, ny + dy
    return out


def _in_check(board, white):
    k = "K" if white else "k"
    if k not in board:
        return False
    ks = board.index(k)
    for s, pc in enumerate(board):
        if pc != "." and pc.isupper() != white and ks in _attacks(board, s, pc):
            return True
    return False


def normalize_castling(board, uci):
    """Lc0 encodes castling as king-takes-own-rook (e1h1); convert to e1g1 style."""
    f, t = sq(uci[:2]), sq(uci[2:4])
    pc, tgt = board[f], board[t]
    if pc in "Pp" and t // 8 in (0, 7) and len(uci) == 4:
        return uci + "n"  # the plain promotion index means a knight (verified on real games)
    if pc in "Kk" and tgt != "." and tgt.isupper() == pc.isupper() and tgt in "Rr":
        to = (6 if t % 8 > f % 8 else 2) + 8 * (f // 8)
        return uci[:2] + sqname(to)
    return uci


def apply_move(board, uci):
    b = board[:]
    f, t = sq(uci[:2]), sq(uci[2:4])
    pc = b[f]
    if pc in "Kk" and abs(t % 8 - f % 8) == 2:  # castling: move the rook too
        r_from = (7 if t % 8 == 6 else 0) + 8 * (f // 8)
        r_to = (5 if t % 8 == 6 else 3) + 8 * (f // 8)
        b[r_to], b[r_from] = b[r_from], "."
    if pc in "Pp" and f % 8 != t % 8 and b[t] == ".":  # en passant
        b[t - 8 if pc == "P" else t + 8] = "."
    b[t], b[f] = pc, "."
    if pc in "Pp" and t // 8 in (0, 7):
        promo = uci[4:5] or "q"
        b[t] = promo.upper() if pc == "P" else promo
    return b


def san(board, uci):
    f, t = sq(uci[:2]), sq(uci[2:4])
    pc = board[f]
    white = pc.isupper()
    if pc in "Kk" and abs(t % 8 - f % 8) == 2:
        s = "O-O" if t % 8 == 6 else "O-O-O"
    else:
        capture = board[t] != "." or (pc in "Pp" and f % 8 != t % 8)
        if pc in "Pp":
            s = (uci[0] + "x" if capture else "") + uci[2:4]
            if t // 8 in (0, 7):
                s += "=" + (uci[4:5] or "q").upper()
        else:
            others = [o for o, op in enumerate(board) if op == pc and o != f and t in _attacks(board, o, op)
                      and not _in_check(apply_move(board, sqname(o) + sqname(t)), white)]
            dis = ""
            if others:
                if all(o % 8 != f % 8 for o in others):
                    dis = uci[0]
                elif all(o // 8 != f // 8 for o in others):
                    dis = uci[1]
                else:
                    dis = uci[:2]
            s = pc.upper() + dis + ("x" if capture else "") + uci[2:4]
    after = apply_move(board, uci)
    if _in_check(after, not white):
        s += "+"
    return s


def fen_placement(board):
    rows = []
    for rank in range(7, -1, -1):
        row, empty = "", 0
        for file in range(8):
            p = board[file + 8 * rank]
            if p == ".":
                empty += 1
            else:
                row += (str(empty) if empty else "") + p
                empty = 0
        rows.append(row + (str(empty) if empty else ""))
    return "/".join(rows)


# ---------------------------------------------------------------- records

def parse_record(buf, off):
    version, fmt = _HEAD.unpack_from(buf, off)
    probs = struct.unpack_from("<1858f", buf, off + 8)
    planes = struct.unpack_from("<104Q", buf, off + 8 + 1858 * 4)
    t = _TAIL.unpack_from(buf, off + 8 + 1858 * 4 + 832)
    (us_ooo, us_oo, them_ooo, them_oo, stm, rule50, invariance, _dummy,
     root_q, best_q, root_d, best_d, root_m, best_m, plies_left,
     result_q, result_d, played_q, played_d, played_m, orig_q, orig_d, orig_m,
     visits, played_idx, best_idx, policy_kld, _reserved) = t
    black = bool(stm)  # input format 1: side_to_move field
    board = ["."] * 64
    for i, letter in enumerate("PNBRQKpnbrqk"):
        for s in _plane_squares(planes[i]):
            if black:
                s = (7 - s // 8) * 8 + s % 8  # undo the vertical flip
            us = i < 6
            white_piece = us != black
            board[s] = letter.upper() if white_piece else letter.lower()
    return dict(version=version, fmt=fmt, probs=probs, board=board, black=black, rule50=rule50,
                root_q=root_q, best_q=best_q, root_d=root_d, best_d=best_d, root_m=root_m,
                plies_left=plies_left, result_q=result_q, result_d=result_d,
                played_q=played_q, orig_q=orig_q, visits=visits,
                played_idx=played_idx, best_idx=best_idx, policy_kld=policy_kld)


def input_planes(buf, off):
    """The network input lc0 used for this record: 112 planes of 8x8 float32, row-major (plane, rank, file),
    from the side to move's point of view (classical 112-plane format: 8 history steps x 13 planes,
    then castling x4, side to move, rule50, zeros, ones)."""
    from array import array
    planes = struct.unpack_from("<104Q", buf, off + 8 + 1858 * 4)
    us_ooo, us_oo, them_ooo, them_oo, stm, rule50 = struct.unpack_from("<6B", buf, off + 8 + 1858 * 4 + 832)
    x = array("f", bytes(112 * 64 * 4))
    for p, v in enumerate(planes):
        if not v:
            continue
        for rank in range(8):
            byte = (v >> (8 * rank)) & 0xFF
            for file in range(8):
                if byte & (0x80 >> file):
                    x[p * 64 + rank * 8 + file] = 1.0
    for k, val in enumerate((us_ooo, us_oo, them_ooo, them_oo, stm, rule50, 0, 1)):
        for s in range(64):
            x[(104 + k) * 64 + s] = float(val)
    return x.tobytes()


def idx_to_uci(idx, black):
    m = POLICY[idx]
    return flip_uci(m) if black else m


def decode_game(path, top_k=5):
    data = gzip.decompress(Path(path).read_bytes())
    n = len(data) // RECORD
    recs = [parse_record(data, i * RECORD) for i in range(n)]
    plies = []
    mismatches = 0
    for i, r in enumerate(recs):
        b, black = r["board"], r["black"]
        sign = -1 if black else 1  # Q values are from the side to move; report from white
        played = normalize_castling(b, idx_to_uci(r["played_idx"], black))
        best = normalize_castling(b, idx_to_uci(r["best_idx"], black))
        legal = [(p, j) for j, p in enumerate(r["probs"]) if p >= 0]  # illegal moves are -1
        legal.sort(reverse=True)
        cands = []
        for p, j in legal[:top_k]:
            u = normalize_castling(b, idx_to_uci(j, black))
            cands.append({"uci": u, "san": san(b, u), "p": round(p, 4)})
        nxt = apply_move(b, played)
        if i + 1 < n and recs[i + 1]["board"] != nxt:
            mismatches += 1
        plies.append({
            "fen": fen_placement(b),
            "white_to_move": not black,
            "move": played, "san": san(b, played),
            "best": best, "best_san": san(b, best),
            "q": round(sign * r["root_q"], 4),
            "best_q": round(sign * r["best_q"], 4),
            "d": round(r["root_d"], 4),
            "m": round(r["root_m"], 1),
            "visits": r["visits"],
            "kld": round(r["policy_kld"], 4),
            "legal": len(legal),
            "cands": cands,
        })
    last = recs[-1]
    final_board = apply_move(last["board"], normalize_castling(
        last["board"], idx_to_uci(last["played_idx"], last["black"])))
    res_white = (-1 if last["black"] else 1) * last["result_q"]
    result = "1-0" if res_white > 0.5 else "0-1" if res_white < -0.5 else "1/2-1/2"
    return {
        "positions": n,
        "result": result,
        "start_fen": plies[0]["fen"] if plies else "",
        "start_white": plies[0]["white_to_move"] if plies else True,
        "final_fen": fen_placement(final_board),
        "plies": plies,
        "mismatches": mismatches,
        "version": recs[0]["version"],
        "input_format": recs[0]["fmt"],
    }


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        g = decode_game(p)
        print(Path(p).name, g["positions"], g["result"], "mismatches:", g["mismatches"])
        print("  ", " ".join(x["san"] for x in g["plies"][:20]), "...")
