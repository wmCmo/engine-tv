// The chosen piece set, shared by every page through localStorage. Changing it in one tab
// updates the others live (storage event).
(function () {
  const KEY = "lc0.pieceSet", DEFAULT = { name: "cburnett", ext: "svg" };
  let cur = DEFAULT;
  try { const v = JSON.parse(localStorage.getItem(KEY)); if (v && /^[a-z0-9-]+$/.test(v.name)) cur = v; } catch {}
  const subs = [];
  // code: FEN letter (K = white king, k = black king)
  const url = (code, set = cur) => `/pieces/${set.name}/${code === code.toUpperCase() ? "w" : "b"}${code.toUpperCase()}.${set.ext}`;
  function set(name, ext) {
    cur = { name, ext };
    try { localStorage.setItem(KEY, JSON.stringify(cur)); } catch {}
    subs.forEach(f => f(cur));
  }
  window.addEventListener("storage", e => {
    if (e.key !== KEY) return;
    try { const v = JSON.parse(e.newValue); if (v) { cur = v; subs.forEach(f => f(cur)); } } catch {}
  });
  window.PieceSet = { url, set, get: () => cur, onChange: f => subs.push(f), DEFAULT };
})();
