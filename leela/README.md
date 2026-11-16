# lc0-viz

A live dashboard for the games your Lc0 training client plays, styled like a chess.com analysis board.

The training client (`lc0-training-client.exe`) plays self-play games and uploads them to the Leela
servers, where the network is actually trained. Each finished game sits briefly in the client's
`data-*` folder as a v6 training chunk, then gets deleted after upload. This tool copies each one into
`archive/` before that happens, decodes it and serves a replay page.

## Run

`leela.ps1` starts and stops everything, like the `fishtest` command:

```powershell
C:\DEV\Playground\lc0-viz\leela.ps1          # training client (-train-only) + dashboard
C:\DEV\Playground\lc0-viz\leela.ps1 stop     # stop the client and free the GPU; dashboard keeps running
C:\DEV\Playground\lc0-viz\leela.ps1 stop all # also stop the dashboard
C:\DEV\Playground\lc0-viz\leela.ps1 status   # what's running, GPU load, URLs
```

Stopping drops only the ~32 games in progress: finished training games are uploaded the moment
they end. Or run just the dashboard by hand:

```powershell
cd C:\DEV\Playground\lc0-viz
python lc0viz.py
```

Then open <http://127.0.0.1:8765/live> (live boards) or <http://127.0.0.1:8765> (analysis). Python 3.9+, standard library only.

Options: `--client-dir <folder with lc0-training-client.exe>` (defaults to the v0.33.0-rc0 folder in
Downloads), `--port 8765`.

Games are only saved while the script runs: anything the client uploads while it's stopped is gone.

### From your phone (Tailscale)

The server listens on 127.0.0.1 only. It's shared with your own tailnet devices on its own port, so
it doesn't collide with the other apps served on this PC (443, 8443, 8444, 10443):

```powershell
tailscale serve --bg --https=8445 http://127.0.0.1:8765
```

Then open `https://<pc-name>.<tailnet>.ts.net:8445/stats` (`leela status` prints the exact address).
To stop sharing (only this port):

```powershell
tailscale serve --https=8445 off
```

Never use `tailscale serve reset`: it removes the other apps' serves too.

**Install it as an app**: open that address in Samsung Internet or Chrome and tap *Install app* in
the top bar (or the browser menu's *Add page to → Home screen*). It opens full screen on the
Dashboard, with long-press shortcuts to Live boards, Analysis and Net. The service worker (`sw.js`)
caches nothing, so the numbers are always live; when the PC is unreachable it shows a short "Your
PC isn't reachable" page instead of a browser error. Icons are made by `make_icons.py` from the
terminal favicon design.

## What you see

### Live boards (`/live`)

A grid of 4–12 boards, each replaying a game that just finished, at the pace it was played. The pace
is measured from your own output: lc0 plays `--parallelism` games side by side (read from the running
`lc0.exe` command line), so one game moves every `parallelism / positions per second` seconds, which
comes to about 5 s at 800 visits. When a board's game ends it shows the result, then picks up the
newest game no other board is showing.

It can't be truly live: lc0 keeps a game in memory until it ends, so a game only becomes visible once
it's over. Each board says how long ago the move on screen was actually played, which is usually
about one game-length (≈12 min). Speed 2× or 5× catches up faster. Click a board to open that
position in Analysis.

### Dashboard (`/stats`)

The pill in the top bar pauses and resumes the training client (also from the phone app). It runs
`leela.ps1 stop` / `leela.ps1`, the same as the `leela` command, asks before pausing (the ~32 games in
progress are dropped), and only accepts requests from the dashboard's own page (`X-Lc0viz` header),
so other websites open in your browser can't press it.

Every number the data supports, refreshed every 15 s:

- **Headline tiles**: games and positions saved, games/hour, search speed (visits/s), your rank on
  training.lczero.org's Active Users, client mode and uptime, GPU now, energy used, archive size.
- **Throughput** per 10 minutes and **results**, split into training and match games. A game counts
  as a match game if it stays on the search's best move through its first 20 plies (temperature 0).
- **GPU history**: utilisation, temperature and power from `nvidia-smi` every 10 s, kept for 24 h
  in `cache/gpu.jsonl`, plus average power and Wh per game.
- **Game length** histogram and a per-move **search** table: visits, legal moves, top-move share,
  off-best rate, policy KLD.
- **Network quality**: calibration of the value head and the draw head (predicted vs actual), and
  the moves-left head's error.
- **Habits**: a heatmap of destination squares, moves by piece, castling, promotions and
  underpromotions, Leela's first moves from the starting position, and records (longest game,
  biggest comeback…) that open in Analysis.

The rank request fetches the public Active Users page and matches your username locally; nothing
about you is sent. Per-game stats are cached in `cache/` (bump `STATS_VERSION` in `lc0viz.py` after
changing `stats.py`).

### Net (`/net`)

A Figma-style canvas of the network lc0 is running right now (input → embedding → 15 encoder
layers → policy, value and moves-left heads), evaluated on any saved position:

- **Canvas**: wheel or trackpad to pan, Ctrl+wheel or trackpad pinch to zoom, drag anywhere
  (blocks included) to pan, click or tap a block to select it, drag a block's title bar to move it
  (positions are remembered), Shift+1 to fit. "Flow" steps through the layers.
- **Touch** (phones, tablets): one finger pans, two fingers pinch-zoom, tap selects, double-tap
  empty canvas fits. The page stacks into one column (position, canvas, inspector) and the layer
  list folds away; the view refits on rotation unless you've moved it.
- **Block colours**: *Change* (how much each layer updated each square, the default), *Size* (the
  representation's size after the layer, kept nearly flat by LayerNorm) or *Neurons* (share of the
  layer's 1,536 feed-forward neurons firing). The blue bars under a block show how focused each of
  its 32 attention heads is.
- **Inspector**: *Activity* (click a square to list the neurons firing hardest there), *Neuron*
  (one neuron across the board), *Attention* (click a square to see where all 32 heads look from
  it). The policy head compares the raw net with the 800-visit search and shows where it wants a
  clicked piece to go; the value and moves-left heads compare raw, searched and actual.
- Open any position from Analysis with the **Net ↗** button.

How it runs: the first visit converts the current net with lc0's own `leela2onnx` and exposes its
inner layers (`nets/<net>.onnx`, ~0.7 GB each, the two newest kept). A helper process
(`networker.py`, CPU only, ~90 ms per position) loads it using about 0.8 GB of RAM, and **exits after
5 idle minutes** (or on *Unload*) so the memory goes back to Windows. It needs the project venv:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-net.txt
```

### Pieces (`/pieces`)

A gallery of 37 piece sets. Hover one to preview it on the big board, click to use it everywhere.
Each card shows the set's author and licence, and "Open licence" hides the non-commercial and
freeware ones.

### Analysis (`/`)

- **Top strip**: games saved, games and positions in the last hour, average length, results
  (white win / draw / black win), and GPU load from `nvidia-smi`.
- **Board**: the position, the last move highlighted, and orange arrows for Leela's top candidate
  moves, sized by their share of the search (800 visits per move).
- **Eval bar and chip**: root Q converted to a pawn-style number (display only), with W/D/L.
- **Move list**: `?!` marks moves where the played move differs from the move the search rated best.
- **Eval graph**: hover for the move and eval, click to jump there. Yellow dots are the `?!` moves.

Keys: ←/→ step, Home/End, F flips the board.

## Files

- `collector.py`: copies finished games into `archive/`. It only reads from the client folder.
- `decoder.py`: parses v6 training records (input format 1) and rebuilds boards, moves, SAN and evals.
  Running `python decoder.py archive/*.gz` checks every decoded move against the next stored board.
- `lc0viz.py`: HTTP server, game store with a disk cache, GPU sampler, client info, rank fetcher.
- `net.html`, `netapi.py`, `networker.py`: the Net explorer page, its server side, and the
  on-demand helper process that runs the net (`requirements-net.txt`, `.venv/`, `nets/`).
- `stats.py` + `stats.html`: per-game statistics, their aggregation, and the Dashboard page.
- `index.html`: the Analysis page.
- `live.html` + `board.js`: the Live boards page and its animated board component.
- `favicons/`: four tab icons. `FAVICON` at the top of `lc0viz.py` picks which one is served
  (default `terminal`; also `neural-ring`, `ring`, `board`). Restart the server after changing it.
- `pieces.html` + `pieceset.js`: the piece gallery and the shared piece-set choice (stored in the
  browser's localStorage, so every page and open tab follows it).
- `pieces/<set>/`: 37 piece sets from lichess-org/lila, with authors and licences in
  `pieces/sets.json`. `python fetch_pieces.py` re-downloads them. Sets that lila lists without a
  licence aren't included. Many sets are CC BY-NC-SA (non-commercial), which covers personal use like
  this; check the licence before reusing them elsewhere.

## Not shown

Which of the two nets played white isn't stored in the training data, so the page doesn't show it.
For the server-side training progress (Elo of each net, loss curves) see <https://training.lczero.org>.
