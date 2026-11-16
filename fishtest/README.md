# fishtest: the Stockfish app

A local dashboard, an across-the-room "TV" view and a phone remote for a [Fishtest](https://tests.stockfishchess.org/)
worker on Windows. It never modifies the worker: it reads the worker's logs and result files, and Fishtest's and
GitHub's public APIs.

## What you get

**Monitor** (`http://127.0.0.1:8787/`)
- Worker status, the current batch's progress and live results (W/L/D, pentanomial, LOS), API response times,
  a game viewer, and the size of the `testing` folder.
- **Your contribution**: every test your PC played games for, grouped by what happened to it. Click a tile to list it.
  - *In Stockfish*: merged into master, matched through the commit message's Fishtest links, or through the
    `closes …/pull/N` line and that PR's test links and branch.
  - *Waiting to merge*: passed the long time control, or has an open pull request. Each row says whether there is a PR.
  - *Still undecided*: the test, or the longer test that followed its STC pass, is still running.
  - *Other passes* / *Not merged*: first-round passes that went no further, research runs, failures.
  - An Elo chart of the merged patches, using Fishtest's own estimate from each patch's LTC test.
- **Watchdog**: if the worker is alive but hasn't reported to Fishtest for 30 minutes, the status shows STUCK and the
  monitor restarts the worker (at most once an hour; after the PC wakes from sleep it waits a full 30 minutes first).
  Every action is logged to `tv-cache\watchdog.log`.

**TV** (`/tv`)
- A fullscreen board to watch from across the room, always oriented from the patch's side, replaying finished games.
- With [Ollama](https://ollama.com/), a "scouting report" that explains what the patch under test changes, written
  from its code diff.
- Works on a phone too (`/tv?phone`).
- The TV used to have football-style spoken commentary; it was removed. `git checkout with-narration` brings back the
  last version that had it.

**Net explorer** (`/net`)
- A Figma-style canvas (drag to pan, Ctrl+scroll or pinch to zoom, click to inspect) of Stockfish's current NNUE:
  input feature sets, feature transformer, layer stacks, with sizes read live from Stockfish's source.
- **The real weights**: all 1,024 feature-transformer neurons as piece-square heatmaps, read from the master net
  file your worker already downloaded. Pick a king square, material block and piece; click a neuron to open it.
- The history of the default net (author, date, LTC Elo) and the latest training experiments on
  [vondele/nettest](https://github.com/vondele/nettest).

**Phone remote** (`/remote`, PIN-protected)
- Start the worker, stop it gracefully, turn the TV on or off, check progress. Installable as a home-screen app.

## Requirements

- Windows, PowerShell 5.1 or 7
- A Fishtest worker running under MSYS2 (`C:\msys64`)
- Python 3.10+ (standard library only)
- Git (for the merge detection and net explorer: a local copy of Stockfish's history, refreshed daily)
- Optional: Ollama (default model `qwen3:8b`) for the scouting reports, Microsoft Edge for the TV, Tailscale for the remote
  away from home

## Usage

If your worker isn't in `C:\fishtest\worker`, set `FISHTEST_WORKER`. A function in your PowerShell profile makes it
one word:

```powershell
function fishtest { & "C:\path\to\fishtest-tv\start-fishtest.ps1" @args }
```

| Command | What it does |
|---|---|
| `fishtest` | Starts the worker, the monitor and the TV (anything already running is left alone), and updates the Ollama models |
| `fishtest worker` | Worker and monitor only |
| `fishtest tv` / `fishtest tvoff` | Opens / closes the TV |
| `fishtest stop` | Stops the worker gracefully: it places `fish.exit`, so the worker reports its finished games first |
| `fishtest remote` | Prints the URL and PIN to open on your phone |

The worker starts **without a window**, with its output in `log.txt` in the worker folder (the previous run's is
kept as `log.txt.previous`). Twice a worker printing to a terminal tab froze for hours mid-task without ever
reporting; with no console there is nothing for it to block on. Start it from a normal (not administrator) shell, or
the monitor won't be able to restart it.

To run only the monitor:

```powershell
python monitor.py --host 0.0.0.0 --worker C:\fishtest\worker
```

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `FISHTEST_WORKER` | `C:\fishtest\worker` | The worker's folder |
| `FISHTEST_PYTHON` | `python` on PATH | The Python that runs the monitor |
| `MSYS2_ROOT` | `C:\msys64` | Where MSYS2 is installed |
| `BRIEF_MODEL` | `qwen3:8b` | Ollama model for the scouting reports |

## Network access and security

`start-fishtest.ps1` starts the monitor on all interfaces (`0.0.0.0`) so your phone can reach it.

- Every page needs a PIN login except from this PC (127.0.0.1). The PIN is created on first start in
  `tv-cache\remote-pin.txt`; delete it and restart to make a new one (which logs out every device).
- Five wrong PINs lock logins for 10 minutes.
- Action buttons need a custom header, so other websites can't trigger them. Only IP, `localhost` and `*.ts.net`
  Host headers are accepted.
- Traffic is plain http. **Don't open the port on your router.** For access away from home use Tailscale, and allow
  port 8787 in Windows Firewall on the Tailscale interface only.

The monitor contacts tests.stockfishchess.org, api.github.com (a few unauthenticated requests an hour) and
github.com (a daily `git fetch` of Stockfish's history).

## Phone home-screen app (PWA)

Browsers only install HTTPS pages as apps, so use Tailscale's HTTPS:

```powershell
tailscale serve --bg --https=8443 8787
```

Open `https://<pc-name>.<tailnet>.ts.net:8443/remote` on your phone and choose "Add to home screen". Connections
through `tailscale serve` still need the PIN. To stop: `tailscale serve --https=8443 off`.

Port 8443 instead of 443 because an app installed from the same name on port 443 would claim the whole site; a
different port is a different site. Avoid `tailscale serve reset`, which also removes other apps' settings.

Rebuild the icons with `python tools/make_icons.py` (needs Pillow).

## Data

Runtime data lives in `tv-cache\` (not in git).

- `ledger.json`: every test and task this PC worked on. The worker's own logs are overwritten after a few weeks, so
  **your contribution history exists only in this file**. Don't delete it.
- `runs\`, `elo\`, `follow-ups.json`, scouting reports: caches of Fishtest data (rebuilt if deleted).
- `stockfish.git`: Stockfish's history, for merge detection and the net explorer.
- `watchdog.log`, `remote-actions.log`: what the monitor did on its own or from the remote.

## Credits and license

MIT ([LICENSE](LICENSE)). `vendor/chess.js` is [chess.js](https://github.com/jhlywa/chess.js) (BSD 2-Clause, notice at
the top of the file). The TV's chess pieces are [Staunty](https://github.com/lichess-org/lila/tree/master/public/piece/staunty)
by sadsnake1, via [lichess-org/lila](https://github.com/lichess-org/lila), licensed
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). The pieces keep their own licence, separate from
the MIT licence of the code: it covers `shared/pieces/staunty/` (the piece library both engine-tv apps share) and the copy that `tools/build_pieces.py` embeds in `tv.html`.
