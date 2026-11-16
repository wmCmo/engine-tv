# engine-tv

Local dashboards for the chess engines your PC helps improve: a [Fishtest](https://tests.stockfishchess.org/) worker
for **Stockfish**, and the [Lc0 training client](https://training.lczero.org/) for **Leela Chess Zero**. Each one
reads its engine's files and public APIs, never changes the worker or client, and works from your phone over
Tailscale as an installable app.

| | [`fishtest/`](fishtest/) | [`leela/`](leela/) |
|---|---|---|
| Watches | a Fishtest worker (MSYS2) | the Lc0 training client |
| Pages | Monitor, TV, Net explorer, phone remote | Dashboard, Live boards, Analysis, Net explorer, Pieces |
| Start / stop | `fishtest` / `fishtest stop` | `leela` / `leela stop` |
| Local address | `http://127.0.0.1:8787/` | `http://127.0.0.1:8765/stats` |
| Phone (Tailscale serve) | `:8443` | `:8445` |

The two apps run separately (own process, own port), so you can use either one on its own. Each folder's README has
the details, requirements and settings.

## Setup

Add both commands to your PowerShell profile (Windows PowerShell 5.1 and PowerShell 7 read different profile files):

```powershell
function fishtest { & "C:\path\to\engine-tv\fishtest\start-fishtest.ps1" @args }
function leela { & "C:\path\to\engine-tv\leela\leela.ps1" @args }
```

Python 3.10+ (standard library) runs both servers. Leela's Net explorer also needs a small venv:
`leela\requirements-net.txt`.

## License

The code is MIT ([LICENSE](LICENSE)). Bundled assets keep their own licenses: chess pieces from
[lichess-org/lila](https://github.com/lichess-org/lila) (each set's license is listed in `leela/pieces/sets.json`;
the Stockfish TV uses Staunty, CC BY-NC-SA 4.0) and [chess.js](https://github.com/jhlywa/chess.js) (BSD 2-Clause).
