// Shared chess.com-style board with animated moves. Used by live.html.
(function () {
  const FILES = "abcdefgh";

  function parseFen(fen) {
    const b = Array(64).fill(".");
    fen.split("/").forEach((row, i) => {
      let f = 0; const r = 7 - i;
      for (const ch of row) { if (/\d/.test(ch)) f += +ch; else { b[r * 8 + f] = ch; f++; } }
    });
    return b;
  }
  const sqIdx = s => FILES.indexOf(s[0]) + 8 * (+s[1] - 1);
  const qToPawns = q => { const c = Math.max(-0.999, Math.min(0.999, q)); return 1.11714640912 * Math.tan(1.5620688421 * c); };
  const fmtEval = q => { const p = qToPawns(q), a = Math.abs(p); const s = a >= 99 ? "99" : a.toFixed(a >= 10 ? 0 : 1); return (p >= 0 ? "+" : "−") + s; };

  class Board {
    constructor(el, opts = {}) {
      this.el = el; this.flipped = !!opts.flipped; this.coords = opts.coords !== false;
      this.anim = opts.animMs ?? 220;
      this.pieceSet = opts.pieceSet || null; // {name, ext}; null = the shared choice
      el.classList.add("cb");
      el.innerHTML = `<div class="cb-sq"></div><div class="cb-pc"></div><svg class="cb-ar" viewBox="0 0 8 8"></svg>`;
      this.sqLayer = el.querySelector(".cb-sq"); this.pcLayer = el.querySelector(".cb-pc"); this.arLayer = el.querySelector(".cb-ar");
      this.imgs = new Map(); // square -> img
      this.board = null;
      this._squares();
    }
    _squares() {
      let h = "";
      for (let row = 0; row < 8; row++) for (let col = 0; col < 8; col++) {
        const file = this.flipped ? 7 - col : col, rank = this.flipped ? row : 7 - row;
        h += `<div class="${(file + rank) % 2 ? "l" : "d"}" data-sq="${rank * 8 + file}">`
          + (this.coords && col === 0 ? `<span class="cr">${rank + 1}</span>` : "")
          + (this.coords && row === 7 ? `<span class="cf">${FILES[file]}</span>` : "") + `</div>`;
      }
      this.sqLayer.innerHTML = h;
    }
    _pos(s) { const f = s % 8, r = Math.floor(s / 8); return this.flipped ? [7 - f, r] : [f, 7 - r]; }
    _place(img, s) { const [x, y] = this._pos(s); img.style.transform = `translate(${x * 100}%, ${y * 100}%)`; }
    _add(s, pc) {
      const img = document.createElement("img");
      img.src = this._url(pc); img.alt = pc; img.draggable = false;
      this._place(img, s); this.pcLayer.appendChild(img); this.imgs.set(s, img);
    }
    _remove(s) { const img = this.imgs.get(s); if (img) { img.remove(); this.imgs.delete(s); } }
    _move(from, to) {
      const img = this.imgs.get(from); if (!img) return;
      this._remove(to); this.imgs.delete(from); this.imgs.set(to, img);
      img.style.transition = this.anim ? `transform ${this.anim}ms ease` : "none";
      img.style.zIndex = 2; this._place(img, to);
      // snap to the final square even if the browser paused the transition (hidden tab)
      setTimeout(() => { img.style.zIndex = ""; img.style.transition = "none"; }, this.anim + 20);
    }
    // fen: placement; last: uci of the move that led here (animated if it follows the shown position)
    set(fen, { last = null, arrows = [], animate = true } = {}) {
      const nb = parseFen(fen);
      if (animate && last && this.board) {
        const f = sqIdx(last.slice(0, 2)), t = sqIdx(last.slice(2, 4)), pc = this.board[f];
        if (pc && pc !== ".") {
          if ("Pp".includes(pc) && f % 8 !== t % 8 && this.board[t] === ".") this._remove(t + (pc === "P" ? -8 : 8));
          if ("Kk".includes(pc) && Math.abs(t % 8 - f % 8) === 2) {
            const r = f - f % 8;
            if (t % 8 === 6) this._move(r + 7, r + 5); else this._move(r, r + 3);
          }
          this._move(f, t);
        }
      }
      // reconcile anything the move didn't explain (promotions, jumps, first draw)
      for (let s = 0; s < 64; s++) {
        const want = nb[s], img = this.imgs.get(s);
        if (want === ".") { if (img) this._remove(s); }
        else if (!img) { this._add(s, want); }
        else if (img.alt !== want) { img.src = this._url(want); img.alt = want; }
      }
      this.board = nb;
      const hl = last ? [sqIdx(last.slice(0, 2)), sqIdx(last.slice(2, 4))] : [];
      this.sqLayer.querySelectorAll("[data-sq]").forEach(d => d.classList.toggle("hl", hl.includes(+d.dataset.sq)));
      this.arLayer.innerHTML = arrows.map(a => this._arrow(sqIdx(a.uci.slice(0, 2)), sqIdx(a.uci.slice(2, 4)), a.w ?? .16, a.op ?? .8)).join("");
    }
    _url(pc) { return window.PieceSet.url(pc, this.pieceSet || window.PieceSet.get()); }
    refreshPieces() { this.imgs.forEach(img => { img.src = this._url(img.alt); }); }
    flip() { this.flipped = !this.flipped; this._squares(); this.imgs.forEach((img, s) => { img.style.transition = "none"; this._place(img, s); }); }
    _xy(s) { const [x, y] = this._pos(s); return [x + .5, y + .5]; }
    _arrow(from, to, width, opacity, color = "var(--arrow, #ffaa00)") {
      const [x1, y1] = this._xy(from), [x2, y2] = this._xy(to);
      const dx = x2 - x1, dy = y2 - y1, head = Math.max(.32, width * 2.2), hw = Math.max(.26, width * 1.8);
      if (Math.abs(dx) * Math.abs(dy) === 2) {
        const horiz = Math.abs(dx) > Math.abs(dy), cx = horiz ? x2 : x1, cy = horiz ? y1 : y2;
        const l2 = Math.hypot(x2 - cx, y2 - cy), vx = (x2 - cx) / l2, vy = (y2 - cy) / l2;
        const l1 = Math.hypot(cx - x1, cy - y1), wx = (cx - x1) / l1, wy = (cy - y1) / l1;
        const hx = x2 - vx * head, hy = y2 - vy * head;
        return `<g opacity="${opacity}"><polyline points="${x1 + wx * .28},${y1 + wy * .28} ${cx},${cy} ${hx},${hy}" fill="none" stroke="${color}" stroke-width="${width}"/>
          <polygon points="${x2},${y2} ${hx - vy * hw / 2},${hy + vx * hw / 2} ${hx + vy * hw / 2},${hy - vx * hw / 2}" fill="${color}"/></g>`;
      }
      const len = Math.hypot(dx, dy), ux = dx / len, uy = dy / len;
      const sx = x1 + ux * .28, sy = y1 + uy * .28, ex = x2 - ux * head, ey = y2 - uy * head;
      return `<g opacity="${opacity}"><line x1="${sx}" y1="${sy}" x2="${ex}" y2="${ey}" stroke="${color}" stroke-width="${width}"/>
        <polygon points="${x2 - ux * .04},${y2 - uy * .04} ${ex - uy * hw / 2},${ey + ux * hw / 2} ${ex + uy * hw / 2},${ey - ux * hw / 2}" fill="${color}"/></g>`;
    }
  }

  const CSS = `
  .cb { position: relative; aspect-ratio: 1; border-radius: 3px; overflow: hidden; user-select: none; container-type: inline-size; }
  .cb-sq { position: absolute; inset: 0; display: grid; grid-template-columns: repeat(8, 1fr); grid-template-rows: repeat(8, 1fr); }
  .cb-sq > div { position: relative; }
  .cb-sq .l { background: var(--sq-light, #ebecd0); } .cb-sq .d { background: var(--sq-dark, #739552); }
  .cb-sq .l.hl { background: var(--hl-light, #f5f682); } .cb-sq .d.hl { background: var(--hl-dark, #b9ca43); }
  .cb-sq .cr, .cb-sq .cf { position: absolute; font-size: max(8px, 2.6cqi); font-weight: 700; line-height: 1; }
  .cb-sq .cr { top: 3%; left: 4%; } .cb-sq .cf { bottom: 3%; right: 5%; }
  .cb-sq .l span { color: var(--sq-dark, #739552); } .cb-sq .d span { color: var(--sq-light, #ebecd0); }
  .cb-pc { position: absolute; inset: 0; pointer-events: none; }
  .cb-pc img { position: absolute; left: 0; top: 0; width: 12.5%; height: 12.5%; will-change: transform; }
  .cb-ar { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; z-index: 3; }`;
  const st = document.createElement("style"); st.textContent = CSS; document.head.appendChild(st);

  window.ChessUI = { Board, parseFen, sqIdx, fmtEval, qToPawns };
})();
