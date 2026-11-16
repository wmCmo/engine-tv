"""Files both engine-tv servers serve from engine-tv/shared: the board, canvas, theme, piece library and the
phone-app helpers (pwa.js, sw.js). Each server asks shared_file(route) first and falls through to its own
routes when it returns None. These are plain static assets, so the fishtest monitor serves them without the
PIN (its phone login page needs theme.css before anyone has logged in)."""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".svg": "image/svg+xml", ".webp": "image/webp"}
ASSET = re.compile(r"/shared/([a-z]+\.(?:js|css))")          # no slashes or dots in the name: nothing outside shared/
PIECE = re.compile(r"/pieces/([a-z0-9-]+)/([wb][KQRBNP])\.(svg|webp)")


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def shared_file(route, app=None):
    """(body bytes, content type) for a shared route, or None.
    app = {"name": ..., "start": ...} serves the shared service worker at /sw.js with that app's offline page
    (served from the root so its scope covers every page)."""
    if route == "/sw.js" and app:
        body = _read(os.path.join(HERE, "sw.js"))
        if body is None:
            return None
        body = body.decode("utf-8").replace("__APP_NAME__", app["name"]).replace("__START__", app["start"])
        return body.encode("utf-8"), TYPES[".js"]
    m = ASSET.fullmatch(route)
    if m:
        path = os.path.join(HERE, m.group(1))
    else:
        m = PIECE.fullmatch(route)
        if not m:
            return None
        path = os.path.join(HERE, "pieces", m.group(1), f"{m.group(2)}.{m.group(3)}")
    body = _read(path)
    return (body, TYPES[os.path.splitext(path)[1]]) if body is not None else None
