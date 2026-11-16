// Figma-style pan/zoom canvas, shared by both net explorers (leela/net.html, fishtest/net.html).
//   wheel pans · Ctrl/⌘+wheel and trackpad pinch zoom at the pointer · Shift+wheel pans sideways
//   drag pans (mouse, pen or one finger) · two fingers pinch-zoom around their midpoint and pan with it
//   a tap/click without moving calls onTap(e, target, isDoubleTap)
// The page owns everything else: what a tap selects, what a drag may move (onDrag), and what to do on each
// camera change (onChange).
(function () {
  const TAP_SLOP = 8;   // px a finger may wiggle and still count as a tap
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

  class PanZoom {
    // stage: the element that receives input; world: the element that gets the transform (inside stage)
    // opts: {cam, minZ, maxZ, ignore, onChange(cam), onTap(e, target, dbl), onDrag(e) -> {move(dx, dy), end(moved)} | null}
    constructor(stage, world, opts = {}) {
      this.stage = stage; this.world = world;
      this.o = { minZ: 0.08, maxZ: 4, ignore: "input,select,textarea,button,a", ...opts };
      this.cam = { x: 0, y: 0, z: 1, ...(opts.cam || {}) };
      this.ptrs = new Map(); this.g = null; this.lastTap = { t: 0, x: 0, y: 0 }; this.pending = null;
      stage.style.touchAction = "none";   // the canvas handles drags and pinches; the page must not scroll or zoom
      stage.addEventListener("wheel", e => this._wheel(e), { passive: false });
      stage.addEventListener("pointerdown", e => this._down(e));
      stage.addEventListener("pointermove", e => this._move(e));
      stage.addEventListener("pointerup", e => this._end(e));
      stage.addEventListener("pointercancel", e => this._end(e));
      stage.addEventListener("dragstart", e => e.preventDefault());
      // a fit asked for while the stage had no size (hidden, not laid out yet) runs once it gets one
      new ResizeObserver(() => { if (this.pending) this.fit(...this.pending); }).observe(stage);
    }
    get width() { return this.stage.clientWidth; }
    get height() { return this.stage.clientHeight; }
    apply() {
      const c = this.cam;
      this.world.style.transform = `translate(${c.x}px, ${c.y}px) scale(${c.z})`;
      this.o.onChange?.(c);
    }
    set(c) { Object.assign(this.cam, c); this.apply(); }
    // zoom by factor f, keeping the stage point (cx, cy) still; defaults to the stage centre
    zoomAt(f, cx = this.width / 2, cy = this.height / 2) {
      const c = this.cam, z = clamp(c.z * f, this.o.minZ, this.o.maxZ);
      c.x = cx - (cx - c.x) * z / c.z; c.y = cy - (cy - c.y) * z / c.z; c.z = z; this.apply();
    }
    // show the world box {x, y, w, h}; bottom = px kept free at the bottom (a toolbar)
    fit(box, { pad = 60, minZ = this.o.minZ, maxZ = 1.4, bottom = 0 } = {}) {
      const W = this.width - pad * 2, H = this.height - bottom - pad * 2;
      if (W <= 0 || H <= 0) { this.pending = [box, { pad, minZ, maxZ, bottom }]; return; }
      this.pending = null;
      const z = clamp(Math.min(W / box.w, H / box.h), minZ, maxZ);
      this.cam.z = z;
      this.cam.x = (this.width - box.w * z) / 2 - box.x * z;
      this.cam.y = (this.height - bottom - box.h * z) / 2 - box.y * z;
      this.apply();
    }
    _local(x, y) { const r = this.stage.getBoundingClientRect(); return [x - r.left, y - r.top]; }
    _pinch() {
      const [a, b] = [...this.ptrs.values()];
      return { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2 };
    }
    _wheel(e) {
      e.preventDefault();
      const c = this.cam;
      if (e.ctrlKey || e.metaKey) this.zoomAt(Math.exp(-e.deltaY * 0.0025), ...this._local(e.clientX, e.clientY));
      else if (e.shiftKey) { c.x -= e.deltaY; this.apply(); }
      else { c.x -= e.deltaX; c.y -= e.deltaY; this.apply(); }
    }
    _down(e) {
      if (this.o.ignore && e.target.closest(this.o.ignore)) return;   // controls inside the canvas work normally
      if (e.pointerType === "mouse" && e.button !== 0 && e.button !== 1) return;
      e.preventDefault();   // no text selection or native drag starting under the pointer
      this.ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
      try { this.stage.setPointerCapture(e.pointerId); } catch {}   // keep moves coming if the finger leaves
      const c = this.cam;
      if (this.ptrs.size === 2) {   // second finger: switch to pinch, cancel any pan or drag
        const p = this._pinch();
        this.g = { type: "pinch", d0: p.d, mx: p.mx, my: p.my, z0: c.z, cx: c.x, cy: c.y };
        return;
      }
      if (this.ptrs.size > 2) return;
      const h = e.button === 0 ? this.o.onDrag?.(e) : null;
      this.g = { type: h ? "drag" : "pan", h, target: e.target, x: e.clientX, y: e.clientY, cx: c.x, cy: c.y, moved: false };
    }
    _move(e) {
      const g = this.g, c = this.cam;
      if (!this.ptrs.has(e.pointerId) || !g) return;
      this.ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (g.type === "pinch") {
        if (this.ptrs.size < 2) return;
        const p = this._pinch(), z = clamp(g.z0 * p.d / g.d0, this.o.minZ, this.o.maxZ);
        const [m0x, m0y] = this._local(g.mx, g.my), [m1x, m1y] = this._local(p.mx, p.my);
        // keep the world point under the starting midpoint under the fingers' current midpoint
        c.z = z; c.x = m1x - (m0x - g.cx) * z / g.z0; c.y = m1y - (m0y - g.cy) * z / g.z0;
        this.apply(); return;
      }
      const dx = e.clientX - g.x, dy = e.clientY - g.y;
      if (!g.moved && Math.hypot(dx, dy) < TAP_SLOP) return;
      g.moved = true;
      if (g.type === "pan") { c.x = g.cx + dx; c.y = g.cy + dy; this.stage.classList.add("panning"); this.apply(); }
      else g.h.move(dx / c.z, dy / c.z);   // world units
    }
    _end(e) {
      if (!this.ptrs.has(e.pointerId)) return;
      this.ptrs.delete(e.pointerId);
      this.stage.classList.remove("panning");
      const g = this.g;
      if (!g) return;
      if (g.type === "pinch") {   // one finger left: carry on as a pan from where it is, never as a tap
        if (this.ptrs.size === 1) { const [p] = [...this.ptrs.values()]; this.g = { type: "pan", x: p.x, y: p.y, cx: this.cam.x, cy: this.cam.y, moved: true }; }
        else if (!this.ptrs.size) this.g = null;
        return;
      }
      if (this.ptrs.size) return;
      if (e.type === "pointerup" && !g.moved) {
        const now = performance.now(), lt = this.lastTap;
        const dbl = now - lt.t < 320 && Math.hypot(e.clientX - lt.x, e.clientY - lt.y) < 30;
        this.lastTap = dbl ? { t: 0, x: 0, y: 0 } : { t: now, x: e.clientX, y: e.clientY };
        this.o.onTap?.(e, g.target, dbl);
      }
      g.h?.end?.(g.moved);
      this.g = null;
    }
  }
  window.PanZoom = PanZoom;
})();
