// Quiet Precision V4.0 precision instruments (E-M1 Capture 1.0 design system, REQ-D06).
// Isolated components: they never talk to the camera. They render supported values handed in by the
// caller (camera capability mapping) and report the user's wish through onRequest. The caller sends it to
// the camera and feeds the readback back in with confirm(). Figma reference: SCP & QCP (31:438),
// Control Panel Components (31:56), Precision Color Controls V9 (12:2).

// ---------------------------------------------------------------------------------------------
// Value model: requested -> pending -> confirmed (or failed). Pure, no DOM, testable in node.
// ---------------------------------------------------------------------------------------------

/** Normalise a list of camera stops: strings or {value,label}. Empty or duplicate lists are refused. */
export function normStops(stops) {
  if (!Array.isArray(stops) || stops.length === 0) throw new Error("stops: need at least one supported camera value");
  const out = stops.map((s) => (typeof s === "object" && s !== null
    ? { value: String(s.value), label: String(s.label ?? s.value) }
    : { value: String(s), label: String(s) }));
  const seen = new Set();
  for (const s of out) {
    if (seen.has(s.value)) throw new Error(`stops: duplicate value ${s.value}`);
    seen.add(s.value);
  }
  return out;
}

/** Index of a camera value in the stops, or -1 (an unknown readback is never snapped to a neighbour). */
export function indexOfValue(stops, value) {
  return stops.findIndex((s) => s.value === String(value));
}

/** Clamp an index into the stop range. */
export function clampIndex(stops, i) {
  return Math.max(0, Math.min(stops.length - 1, Math.round(i)));
}

/** Nearest stop for a fractional scale position (only real stops, never in-between values). */
export function snapPosition(stops, pos) {
  return clampIndex(stops, pos);
}

/**
 * State of one camera value.
 *   confirmed: last value the camera read back (null until the first readback)
 *   requested: the user's wish, not yet sent
 *   pending:   sent to the camera, no readback yet
 *   failed:    the camera refused or did not answer; confirmed stays what the camera said
 */
export class ValueState {
  constructor(stops, confirmedValue = null) {
    this.stops = normStops(stops);
    this.confirmed = confirmedValue === null ? null : String(confirmedValue);
    this.requested = null;
    this.pending = null;
    this.error = null;
  }

  get phase() {
    if (this.error) return "failed";
    if (this.pending !== null) return "pending";
    if (this.requested !== null) return "requested";
    return "confirmed";
  }

  /** The value to show: the wish while one is open, otherwise the camera's value. */
  get shown() {
    return this.pending ?? this.requested ?? this.confirmed;
  }

  get shownIndex() {
    const v = this.shown;
    return v === null ? -1 : indexOfValue(this.stops, v);
  }

  /** User wish. Returns false (and changes nothing) for a value that is not a supported stop. */
  request(value) {
    const v = String(value);
    if (indexOfValue(this.stops, v) < 0) return false;
    if (this.pending === null && v === this.confirmed) { this.requested = null; this.error = null; return true; }
    this.requested = v;
    this.error = null;
    return true;
  }

  /** The caller hands the wish to the camera adapter. Returns the value sent, or null if nothing to send. */
  send() {
    if (this.requested === null) return null;
    this.pending = this.requested;
    this.requested = null;
    return this.pending;
  }

  /** Camera readback. The camera's value always wins; a different readback means the wish was not taken. */
  confirm(value) {
    const v = value === null || value === undefined ? null : String(value);
    const asked = this.pending;
    this.confirmed = v;
    this.pending = null;
    this.error = asked !== null && v !== asked ? `camera kept ${v}` : null;
    return this.error === null;
  }

  /** Sending failed (refused, timeout, disconnected). The confirmed value stays the camera's. */
  fail(message) {
    this.pending = null;
    this.error = String(message || "not confirmed");
  }

  /** Swap in a new list of supported stops (lens change, mode change). Drops wishes that are no longer valid. */
  setStops(stops) {
    this.stops = normStops(stops);
    for (const k of ["requested", "pending"]) {
      if (this[k] !== null && indexOfValue(this.stops, this[k]) < 0) this[k] = null;
    }
  }
}

// ---------------------------------------------------------------------------------------------
// Scale geometry (pure): Center Lock moves the scale under a fixed centre marker; Fixed Range moves
// the marker across a fixed scale. Both snap only to real stops.
// ---------------------------------------------------------------------------------------------

/** Pixel offset of the scale strip so that stop `pos` sits under the centre (Center Lock). */
export function centerLockOffset(pos, step, width) {
  return width / 2 - pos * step;
}

/** Scale position (fractional stop index) for a drag of dx pixels starting at stop `startPos`. */
export function dragToPosition(startPos, dx, step, variant) {
  // Center Lock: dragging the scale left brings higher stops to the centre. Fixed Range: the marker follows.
  return variant === "fixed" ? startPos + dx / step : startPos - dx / step;
}

/** Fixed Range: step size so that all stops fit the width; fractional stop index at pixel x. */
export function fixedRangeStep(count, width, pad) {
  return count > 1 ? (width - 2 * pad) / (count - 1) : 0;
}

/** Stops shown with a long tick and a label (every `every`-th stop, counted from the first). */
export function isMajor(i, every) {
  return every <= 1 || i % every === 0;
}

// ---------------------------------------------------------------------------------------------
// DOM helpers
// ---------------------------------------------------------------------------------------------

const SVGNS = "http://www.w3.org/2000/svg";
let iconBase = "/ds/icons.svg";
/** Where the sprite lives (the gallery and the app both serve it from /ds/). */
export function setIconBase(url) { iconBase = url; }

export function icon(name, cls = "qp-icon") {
  const s = document.createElementNS(SVGNS, "svg");
  s.setAttribute("class", cls);
  s.setAttribute("aria-hidden", "true");
  const u = document.createElementNS(SVGNS, "use");
  u.setAttribute("href", `${iconBase}#i-${name}`);
  s.appendChild(u);
  return s;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function stateClass(phase) {
  return `qp-state-${phase}`;
}

// ---------------------------------------------------------------------------------------------
// Precision Scale (Center Lock default, Fixed Range alternative)
// ---------------------------------------------------------------------------------------------

/**
 * mountScale(host, {state, label, variant, majorEvery, format, onRequest})
 *   state:      ValueState (the scale shows state.shown and its phase)
 *   variant:    "center" (Center Lock, approved preference) or "fixed" (Fixed Range, alternative)
 *   onRequest:  called with the requested camera value after a tap, drag/swipe end or key press.
 * Direct operation only: drag, swipe (flick) and tap on the scale, arrow keys; no extra slider.
 */
export function mountScale(host, opts) {
  const o = { variant: "center", majorEvery: 3, format: (s) => s.label, label: "Value", ...opts };
  const root = el("div", "qp-scale");
  root.dataset.variant = o.variant;
  root.tabIndex = 0;
  root.setAttribute("role", "slider");
  root.setAttribute("aria-label", o.label);
  const strip = el("div", "qp-scale-strip");
  const marker = el("div", "qp-scale-marker");
  root.append(strip, marker);
  host.appendChild(root);

  let pos = 0;          // fractional stop index currently under the marker
  let drag = null;      // {x, startPos, t, moved, samples}
  let raf = 0;

  const step = () => (o.variant === "fixed"
    ? fixedRangeStep(o.state.stops.length, root.clientWidth, 24)
    : parseFloat(getComputedStyle(root).getPropertyValue("--qp-tick-step")) || 41);

  function build() {
    strip.textContent = "";
    o.state.stops.forEach((s, i) => {
      const t = el("button", "qp-tick");
      t.type = "button";
      t.tabIndex = -1;
      t.dataset.i = i;
      t.setAttribute("aria-label", o.format(s));
      if (isMajor(i, o.majorEvery)) {
        t.classList.add("major");
        t.appendChild(el("span", "qp-tick-label qp-num", o.format(s)));
      }
      strip.appendChild(t);
    });
  }

  function layout(p) {
    const st = step();
    const w = root.clientWidth;
    const ticks = strip.children;
    if (o.variant === "fixed") {
      for (let i = 0; i < ticks.length; i++) ticks[i].style.transform = `translateX(${24 + i * st}px)`;
      strip.style.transform = "";
      marker.style.transform = `translateX(${24 + p * st}px)`;
    } else {
      for (let i = 0; i < ticks.length; i++) ticks[i].style.transform = `translateX(${i * st}px)`;
      strip.style.transform = `translateX(${centerLockOffset(p, st, w)}px)`;
      marker.style.transform = `translateX(${w / 2}px)`;
    }
    const near = clampIndex(o.state.stops, p);
    for (let i = 0; i < ticks.length; i++) ticks[i].classList.toggle("active", i === near);
  }

  function render() {
    const i = o.state.shownIndex;
    if (!drag) pos = i < 0 ? pos : i;
    root.dataset.phase = o.state.phase;
    root.className = `qp-scale ${stateClass(o.state.phase)}`;
    root.setAttribute("aria-valuemin", 0);
    root.setAttribute("aria-valuemax", o.state.stops.length - 1);
    root.setAttribute("aria-valuenow", Math.max(0, i));
    const s = o.state.stops[i];
    root.setAttribute("aria-valuetext", s ? `${o.format(s)}, ${o.state.phase}` : "unknown");
    root.setAttribute("aria-busy", o.state.phase === "pending" ? "true" : "false");
    layout(pos);
  }

  function requestIndex(i) {
    const s = o.state.stops[clampIndex(o.state.stops, i)];
    if (o.state.request(s.value)) {
      render();
      if (o.state.phase === "requested") o.onRequest?.(s.value);
    }
  }

  function animateTo(target) {
    cancelAnimationFrame(raf);
    const from = pos;
    const t0 = performance.now();
    const dur = matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 160;
    const tick = (now) => {
      const k = dur ? Math.min(1, (now - t0) / dur) : 1;
      pos = from + (target - from) * (1 - (1 - k) ** 3);
      layout(pos);
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
  }

  root.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    root.setPointerCapture(e.pointerId);
    drag = { x: e.clientX, startPos: pos, moved: false, samples: [[e.timeStamp, e.clientX]], target: e.target };
  });
  root.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x;
    if (Math.abs(dx) > 4) drag.moved = true;
    if (!drag.moved) return;
    drag.samples.push([e.timeStamp, e.clientX]);
    if (drag.samples.length > 5) drag.samples.shift();
    pos = Math.max(-0.4, Math.min(o.state.stops.length - 0.6, dragToPosition(drag.startPos, dx, step(), o.variant)));
    layout(pos);
  });
  const end = (e) => {
    if (!drag) return;
    const d = drag;
    drag = null;
    if (!d.moved) {
      // Tap: a tick (stop) jumps there; a tap elsewhere on the scale does nothing.
      const t = d.target.closest?.(".qp-tick");
      if (t) { const i = +t.dataset.i; animateTo(i); requestIndex(i); }
      return;
    }
    // Swipe: carry on with the release velocity, then snap to the nearest real stop.
    const [a, b] = [d.samples[0], d.samples[d.samples.length - 1]];
    const v = b[0] > a[0] ? (b[1] - a[1]) / (b[0] - a[0]) : 0; // px per ms
    const flick = Math.abs(v) > 0.3 ? (v * 120) / step() : 0;
    const target = snapPosition(o.state.stops, pos + (o.variant === "fixed" ? flick : -flick));
    animateTo(target);
    requestIndex(target);
  };
  root.addEventListener("pointerup", end);
  root.addEventListener("pointercancel", () => { drag = null; render(); });
  root.addEventListener("keydown", (e) => {
    const i = Math.max(0, o.state.shownIndex);
    const k = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
    let to = null;
    if (k) to = i + k;
    else if (e.key === "Home") to = 0;
    else if (e.key === "End") to = o.state.stops.length - 1;
    if (to === null) return;
    e.preventDefault();
    to = clampIndex(o.state.stops, to);
    animateTo(to);
    requestIndex(to);
  });
  const ro = new ResizeObserver(() => layout(pos));
  ro.observe(root);

  build();
  render();
  return {
    el: root,
    render,
    setStops(stops) { o.state.setStops(stops); build(); render(); },
    setVariant(v) { o.variant = v; root.dataset.variant = v; build(); render(); },
    destroy() { ro.disconnect(); cancelAnimationFrame(raf); root.remove(); },
  };
}

// ---------------------------------------------------------------------------------------------
// QCP - Quick Control Panel: four fixed positions (aperture, shutter, ISO, EV), Center Lock scale,
// AF / Capture / Review in the lower bar.
// ---------------------------------------------------------------------------------------------

export const QCP_PARAMS = [
  { key: "aperture", label: "APERTURE", fmt: (s) => `ƒ${s.label}`, scaleFmt: (s) => s.label },
  { key: "shutter", label: "SHUTTER", fmt: (s) => (/^\d/.test(s.label) && !s.label.includes('"') ? `1/${s.label}` : s.label), scaleFmt: (s) => s.label },
  { key: "iso", label: "ISO", fmt: (s) => s.label, scaleFmt: (s) => s.label },
  { key: "ev", label: "EV", fmt: (s) => s.label, scaleFmt: (s) => s.label },
];

/**
 * mountQCP(host, {title, connection, values, active, onRequest, onAction})
 *   values:     {aperture: ValueState|null, shutter, iso, ev}; null = not available in this mode/connection
 *   connection: {kind: "usb"|"wifi", label}
 *   onRequest(key, value): user wish for a camera value
 *   onAction(name): "af" | "capture" | "review" - the panel never triggers the camera itself
 */
export function mountQCP(host, opts) {
  const o = { title: "OMCAP", active: "aperture", ...opts };
  const root = el("section", "qp-panel qp-qcp");
  root.setAttribute("aria-label", "Quick Control Panel");
  const head = el("header", "qp-panel-head");
  head.append(el("span", "qp-brand", o.title), connectionBadge(o.connection));
  const kicker = el("div", "qp-kicker", "QUICK CONTROL PANEL");
  const activeLabel = el("div", "qp-active-label");
  const big = el("output", "qp-big qp-num");
  big.setAttribute("aria-live", "polite");
  const scaleHost = el("div", "qp-scale-host");
  const params = el("div", "qp-params");
  params.setAttribute("role", "tablist");
  const bar = el("div", "qp-capture-bar");
  const af = actionButton("af", "s-af", "AF");
  const cap = el("button", "qp-capture");
  cap.type = "button";
  cap.setAttribute("aria-label", "Capture");
  cap.dataset.action = "capture";
  const rev = actionButton("review", "review", "Review");
  bar.append(af, cap, rev);
  root.append(head, kicker, activeLabel, big, scaleHost, params, bar);
  host.appendChild(root);

  let scale = null;
  const paramBtns = {};
  for (const p of QCP_PARAMS) {
    const b = el("button", "qp-param");
    b.type = "button";
    b.setAttribute("role", "tab");
    b.dataset.key = p.key;
    b.append(el("span", "qp-param-label", p.label), el("span", "qp-param-value qp-num"), el("span", "qp-param-bar"));
    b.addEventListener("click", () => { if (o.values[p.key]) { o.active = p.key; render(true); } });
    params.appendChild(b);
    paramBtns[p.key] = b;
  }
  bar.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-action]");
    if (b && !b.disabled) o.onAction?.(b.dataset.action);
  });

  function render(rebuildScale) {
    if (!o.values[o.active]) o.active = QCP_PARAMS.find((p) => o.values[p.key])?.key ?? o.active;
    const p = QCP_PARAMS.find((x) => x.key === o.active);
    const st = o.values[o.active];
    activeLabel.textContent = p.label;
    if (st) {
      const s = st.stops[st.shownIndex];
      big.textContent = s ? p.fmt(s) : "–";
      big.className = `qp-big qp-num ${stateClass(st.phase)}`;
      if (rebuildScale || !scale) {
        scale?.destroy();
        scale = mountScale(scaleHost, {
          state: st, label: p.label, variant: o.variant || "center", format: p.scaleFmt,
          onRequest: (v) => { o.onRequest?.(p.key, v); render(false); },
        });
      } else scale.render();
    } else {
      big.textContent = "–";
      scale?.destroy();
      scale = null;
    }
    for (const q of QCP_PARAMS) {
      const b = paramBtns[q.key];
      const s = o.values[q.key];
      b.disabled = !s;
      b.title = s ? "" : "Not available in this mode or on this connection";
      b.setAttribute("aria-selected", q.key === o.active ? "true" : "false");
      b.classList.toggle("selected", q.key === o.active);
      const v = b.querySelector(".qp-param-value");
      const stop = s?.stops[s.shownIndex];
      v.textContent = stop ? q.fmt(stop) : "–";
      v.className = `qp-param-value qp-num ${s ? stateClass(s.phase) : ""}`;
    }
  }

  render(true);
  return {
    el: root,
    render: () => render(false),
    setActive(k) { o.active = k; render(true); },
    setVariant(v) { o.variant = v; render(true); },
    setConnection(c) { head.lastChild.replaceWith(connectionBadge(c)); },
    destroy() { scale?.destroy(); root.remove(); },
  };
}

function actionButton(action, iconName, label) {
  const b = el("button", "qp-icon-btn");
  b.type = "button";
  b.dataset.action = action;
  b.setAttribute("aria-label", label);
  b.appendChild(icon(iconName));
  return b;
}

function connectionBadge(c) {
  const b = el("span", "qp-conn");
  if (!c) { b.textContent = "Not connected"; return b; }
  b.append(icon(c.kind === "usb" ? "usb" : "wifi", "qp-icon qp-icon-sm"), el("span", "", c.label || (c.kind === "usb" ? "USB" : "Wi-Fi")));
  b.classList.add("ok");
  return b;
}

// ---------------------------------------------------------------------------------------------
// SCP - Super Control Panel: fixed exposure positions, tiles with icon, value and label.
// Tapping a tile asks to open its precision control (onOpen); unavailable functions stay visible but marked.
// ---------------------------------------------------------------------------------------------

/**
 * mountSCP(host, {title, connection, exposure, tiles, footer, onOpen})
 *   exposure: [{key, label, value, phase?, available}] (mode, shutter, aperture, ISO, EV)
 *   tiles:    [{key, icon, value, label, available, reason?, phase?}]
 *   footer:   {left, right}
 */
export function mountSCP(host, opts) {
  const o = { title: "OMCAP", ...opts };
  const root = el("section", "qp-panel qp-scp");
  root.setAttribute("aria-label", "Super Control Panel");
  host.appendChild(root);

  function render() {
    root.textContent = "";
    const head = el("header", "qp-panel-head");
    head.append(el("span", "qp-brand", o.title), connectionBadge(o.connection));
    const expo = el("div", "qp-scp-expo");
    for (const x of o.exposure || []) {
      const b = el("button", "qp-scp-expo-item");
      b.type = "button";
      b.dataset.key = x.key;
      b.disabled = !x.available;
      b.append(el("span", "qp-param-label", x.label), el("span", `qp-scp-expo-value qp-num ${stateClass(x.phase || "confirmed")}`, x.value ?? "–"));
      expo.appendChild(b);
    }
    const grid = el("div", "qp-scp-grid");
    for (const t of o.tiles || []) {
      const b = el("button", "qp-scp-tile");
      b.type = "button";
      b.dataset.key = t.key;
      if (!t.available) {
        b.classList.add("unavailable");
        b.setAttribute("aria-disabled", "true");
        b.title = t.reason || "Not available";
      }
      b.append(icon(t.icon), el("span", `qp-scp-tile-value ${stateClass(t.phase || "confirmed")}`, t.value ?? "–"), el("span", "qp-scp-tile-label", t.label));
      grid.appendChild(b);
    }
    const foot = el("footer", "qp-scp-foot");
    foot.append(el("span", "", o.footer?.left ?? ""), el("span", "qp-num", o.footer?.right ?? ""));
    root.append(head, el("div", "qp-kicker", "SUPER CONTROL PANEL"), expo, grid, foot);
  }
  root.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-key]");
    if (!b || b.disabled || b.getAttribute("aria-disabled") === "true") return;
    o.onOpen?.(b.dataset.key);
  });
  render();
  return { el: root, update(next) { Object.assign(o, next); render(); }, destroy() { root.remove(); } };
}

// ---------------------------------------------------------------------------------------------
// Precision Color Controls V9: Color Profile, Color Creator, Monochrome Profile.
// One instrument family: ring of segments, value and name in the centre, direct radial grip.
// Static reference in Figma; drag/snap and Color All still need interaction validation (DESIGN.md).
// ---------------------------------------------------------------------------------------------

/** Angle (deg, 0 = top, clockwise) of segment i of n. */
export function segmentAngle(i, n) {
  return (360 / n) * i;
}

/** Segment nearest to a pointer angle (deg, 0 = top, clockwise). */
export function angleToSegment(deg, n) {
  const a = ((deg % 360) + 360) % 360;
  return Math.round(a / (360 / n)) % n;
}

/** Map a radial distance (0 = centre, 1 = ring) to a value in [min, max], snapped to integers. */
export function radiusToValue(r, min, max, inner = 0.45, outer = 1) {
  const k = Math.max(0, Math.min(1, (r - inner) / (outer - inner)));
  return Math.round(min + k * (max - min));
}

export function valueToRadius(v, min, max, inner = 0.45, outer = 1) {
  return inner + ((v - min) / (max - min || 1)) * (outer - inner);
}

/**
 * mountColorRing(host, {kind, segments, values, active, min, max, centerLabel, onRequest})
 *   kind:     "profile" (polygon of per-segment values), "creator" (hue position + one value),
 *             "mono" (filter segments with their own value)
 *   segments: [{name, hue}] from the capability mapping (hue in degrees for the swatch only)
 *   values:   per-segment integers (profile, mono) or {hue: index, value: int} (creator)
 *   onRequest({segment, value}): user wish; the caller validates against the camera or the processor
 */
export function mountColorRing(host, opts) {
  const o = { size: 260, ...opts };
  const n = o.segments.length;
  const root = el("div", `qp-color qp-color-${o.kind}`);
  root.tabIndex = 0;
  root.setAttribute("role", "group");
  root.setAttribute("aria-label", { profile: "Color Profile", creator: "Color Creator", mono: "Monochrome Profile" }[o.kind]);
  const svg = document.createElementNS(SVGNS, "svg");
  svg.setAttribute("viewBox", "-130 -130 260 260");
  svg.setAttribute("class", "qp-color-svg");
  const centre = el("div", "qp-color-centre");
  const val = el("output", "qp-color-value qp-num");
  const name = el("div", "qp-color-name");
  centre.append(val, name);
  root.append(svg, centre);
  host.appendChild(root);
  const R = 118;
  const polar = (deg, r) => [Math.sin((deg * Math.PI) / 180) * r, -Math.cos((deg * Math.PI) / 180) * r];

  const getVal = (i) => (o.kind === "creator" ? o.values.value : o.values[i]);
  const fmtSigned = (v) => (v > 0 ? `+${v}` : `${v}`);

  function draw() {
    svg.textContent = "";
    const seg = 360 / n;
    o.segments.forEach((s, i) => {
      const gap = o.kind === "creator" ? seg * 0.38 : seg * 0.22;
      const a0 = segmentAngle(i, n) - seg / 2 + gap / 2;
      const a1 = segmentAngle(i, n) + seg / 2 - gap / 2;
      const [x0, y0] = polar(a0, R);
      const [x1, y1] = polar(a1, R);
      const p = document.createElementNS(SVGNS, "path");
      p.setAttribute("d", o.kind === "creator" ? `M${x0} ${y0}A${R} ${R} 0 0 1 ${x1} ${y1}` : `M${x0} ${y0}L${x1} ${y1}`);
      p.setAttribute("class", "qp-color-seg");
      p.style.setProperty("--seg", s.hue === null || s.hue === undefined ? "var(--qp-muted)" : `hsl(${s.hue} 55% 58%)`);
      p.dataset.i = i;
      svg.appendChild(p);
    });
    const inner = document.createElementNS(SVGNS, "circle");
    inner.setAttribute("r", o.kind === "profile" ? 0 : 66);
    inner.setAttribute("class", "qp-color-inner");
    svg.appendChild(inner);
    if (o.kind === "profile") {
      const pts = o.segments.map((_, i) => polar(segmentAngle(i, n), valueToRadius(getVal(i), o.min, o.max) * (R - 14)));
      const poly = document.createElementNS(SVGNS, "polygon");
      poly.setAttribute("points", pts.map((p) => p.join(",")).join(" "));
      poly.setAttribute("class", "qp-color-poly");
      svg.appendChild(poly);
    }
    // Grip at the active segment
    const i = o.kind === "creator" ? o.values.hue : o.active;
    const r = o.kind === "profile" ? valueToRadius(getVal(i), o.min, o.max) * (R - 14) : o.kind === "creator" ? R - 28 : R - 28;
    const [gx, gy] = polar(segmentAngle(i, n), r);
    const g = document.createElementNS(SVGNS, "circle");
    g.setAttribute("cx", gx);
    g.setAttribute("cy", gy);
    g.setAttribute("r", 10);
    g.setAttribute("class", "qp-color-grip");
    g.style.setProperty("--seg", o.segments[i].hue === null || o.segments[i].hue === undefined ? "var(--qp-muted)" : `hsl(${o.segments[i].hue} 55% 58%)`);
    svg.appendChild(g);
    const v = getVal(i);
    // noValue: the camera has only the choice, no level (E-M1 B&W Filter); show the short name instead.
    val.textContent = o.noValue ? (o.segments[i].short ?? "") : o.kind === "creator" ? String(v).padStart(2, "0") : fmtSigned(v);
    name.textContent = o.kind === "creator" ? `HUE ${String(i).padStart(2, "0")}` : o.segments[i].name.toUpperCase();
    root.setAttribute("aria-valuetext", `${name.textContent} ${val.textContent}`);
    root.className = `qp-color qp-color-${o.kind} ${stateClass(o.phase || "confirmed")}`;
  }

  function emit(segment, value) {
    const v = Math.max(o.min, Math.min(o.max, value));
    if (o.kind === "creator") { o.values = { hue: segment, value: v }; }
    else { o.values = o.values.slice(); o.values[segment] = v; o.active = segment; }
    o.phase = "requested";
    draw();
    o.onRequest?.({ segment, value: v });
  }

  let drag = null;
  root.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    root.setPointerCapture(e.pointerId);
    drag = true;
    move(e);
  });
  root.addEventListener("pointermove", (e) => { if (drag) move(e); });
  root.addEventListener("pointerup", () => { drag = null; });
  root.addEventListener("pointercancel", () => { drag = null; });
  function move(e) {
    const b = svg.getBoundingClientRect();
    const x = ((e.clientX - b.left) / b.width) * 260 - 130;
    const y = ((e.clientY - b.top) / b.height) * 260 - 130;
    const deg = (Math.atan2(x, -y) * 180) / Math.PI;
    const r = Math.hypot(x, y) / (R - 14);
    const seg = angleToSegment(deg, n);
    if (o.kind === "creator") {
      if (seg !== o.values.hue) emit(seg, o.values.value);
    } else if (o.kind === "profile" && !o.noValue) {
      emit(seg, radiusToValue(r, o.min, o.max));
    } else if (seg !== o.active) {
      if (o.noValue) emit(seg, 0);
      else { o.active = seg; draw(); }
    }
  }
  root.addEventListener("keydown", (e) => {
    const i = o.kind === "creator" ? o.values.hue : o.active;
    const v = getVal(i);
    if (e.key === "ArrowRight") emit((i + 1) % n, o.kind === "creator" ? v : getVal((i + 1) % n));
    else if (e.key === "ArrowLeft") emit((i - 1 + n) % n, o.kind === "creator" ? v : getVal((i - 1 + n) % n));
    else if (e.key === "ArrowUp" && !o.noValue) emit(i, v + 1);
    else if (e.key === "ArrowDown" && !o.noValue) emit(i, v - 1);
    else return;
    e.preventDefault();
  });
  root.addEventListener("wheel", (e) => {
    if (o.noValue) return;
    e.preventDefault();
    const i = o.kind === "creator" ? o.values.hue : o.active;
    emit(i, getVal(i) + (e.deltaY < 0 ? 1 : -1));
  }, { passive: false });

  draw();
  return {
    el: root,
    confirm(values) { o.values = values; o.phase = "confirmed"; draw(); },
    setPhase(p) { o.phase = p; draw(); },
    destroy() { root.remove(); },
  };
}
