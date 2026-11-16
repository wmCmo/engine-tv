# Chess pieces (shared by both apps)

37 piece sets from [lichess-org/lila](https://github.com/lichess-org/lila) (`public/piece/<set>/`), one folder per
set with 12 images (`wK.svg` … `bP.svg`; `monarchy` is webp). Each set's author and licence are in
[`sets.json`](sets.json). They are **not** under this repository's MIT licence: each keeps its own (GPL, MIT,
Apache, CC BY, CC BY-SA, CC BY-NC-SA, or freeware for personal use).

Who uses what:
- **leela/** serves every set at `/pieces/<set>/<piece>` for the boards and the Pieces gallery, and lets you pick one.
- **fishtest/** embeds **Staunty** (by sadsnake1, [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/))
  into its TV page with `fishtest/tools/build_pieces.py`. That licence also covers the embedded copy in
  `fishtest/tv.html`.

`python shared/fetch_pieces.py` re-downloads any missing set. Sets that lila lists without a licence aren't included.
