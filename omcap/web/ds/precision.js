// Quiet Precision precision instruments (E-M1 Capture 1.0 design system, REQ-D06).
// Precision Instrument Library V2.0 (Figma 45:1180): Scale, Selector, Wheel, Axis, Relative control.
// Isolated components: they never talk to the camera. They render supported values handed in by the
// caller (camera capability mapping) and report the user's wish through onRequest. The caller sends it to
// the camera and feeds the readback back in with confirm(). Every tick is one real camera value.

// All input runs through the Precision Detent Engine: one detent per valid value, no gliding values,
// no kinetic scrolling, one feedback pulse per detent passed.
import { createDetent } from "./detent.js";

// ---------------------------------------------------------------------------------------------
// Value model: requested -> pending -> confirmed (or failed). Pure, no DOM, testable in node.
// ---------------------------------------------------------------------------------------------

/** Normalise a list of camera stops: strings or {value,label,major,special}. Empty or duplicate lists are refused. */
export function normStops(stops) {
  if (!Array.isArray(stops) || stops.length === 0) throw new Error("stops: need at least one supported camera value");
  const out = stops.map((s) => (typeof s === "object" && s !== null
    ? { value: String(s.value), label: String(s.label ?? s.value), major: s.major ?? null, special: !!s.special }
    : { value: String(s), label: String(s), major: null, special: false }));
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

/**
 * State of one camera value.
 *   confirmed: last value the camera read back (null until the first readback)
 *   requested: the user's wish, not yet sent
 *   pending:   sent to the camera, no readback yet
 *   failed:    the camera refused or did not answer; confirmed stays what the camera said
 * One ValueState per camera value; QCP, SCP and any other view share the same object (one value source).
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
    if (this.requested !== null) return "requested"; // newest local selection, not sent yet (an older one may be in flight)
    if (this.error) return "failed";
    if (this.pending !== null) return "pending";
    return "confirmed";
  }

  /** The value to show: the newest local selection, else the one in flight, else the camera's value. */
  get shown() {
    return this.requested ?? this.pending ?? this.confirmed;
  }

  get shownIndex() {
    const v = this.shown;
    return v === null ? -1 : indexOfValue(this.stops, v);
  }

  /** User wish. Returns false (and changes nothing) for a value that is not a supported stop. */
  request(value) {
    const v = String(value);
    if (indexOfValue(this.stops, v) < 0) return false;
    // Back to what the camera has (or to what is already on its way): nothing new to send.
    if ((this.pending === null && v === this.confirmed) || v === this.pending) { this.requested = null; this.error = null; return true; }
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

  /** Swap in a new list of supported stops (lens, mode or step-size change). Drops wishes that are no longer valid. */
  setStops(stops) {
    this.stops = normStops(stops);
    for (const k of ["requested", "pending"]) {
      if (this[k] !== null && indexOfValue(this.stops, this[k]) < 0) this[k] = null;
    }
  }
}

// ---------------------------------------------------------------------------------------------
// Adaptive Precision Scale V2.0: every tick has a purpose. Ticks, labels and snap positions come
// from the same capability list. Major = a relevant main value of that parameter, minor = a real
// intermediate stop; special values (AUTO, LOW, BULB, LIVE ...) are semantic, not numbers.
// ---------------------------------------------------------------------------------------------

const near = (x, tol) => Math.abs(x - Math.round(x)) < tol;

/** Special (non-numeric) camera values and their display label. Values are the camera's own strings. */
export const SPECIAL_LABELS = {
  auto: "AUTO", low: "LOW", livebulb: "BULB", bulb: "BULB", livetime: "LIVE TIME", livecomp: "LIVE COMP",
};

/** Shutter value string (Wi-Fi style: '250' = 1/250 s, '2"' = 2 s) in seconds, or null if special. */
export function shutterSeconds(v) {
  const s = String(v);
  if (s.endsWith('"')) return parseFloat(s);
  const n = parseFloat(s);
  return Number.isFinite(n) && n > 0 ? 1 / n : null;
}

/**
 * Is this camera value a main value of the parameter? Separate rules per kind, independent of the step
 * size the camera uses (1/3, 1/2 or 1 EV lists all mark the same full stops; ISO has its own steps).
 */
export function isMainValue(kind, value) {
  const s = String(value);
  if (SPECIAL_LABELS[s.toLowerCase()]) return false;
  const n = parseFloat(s);
  switch (kind) {
    case "aperture": return n > 0 && near(2 * Math.log2(n), 0.1);           // f/1, 1.4, 2, 2.8 ... 22
    case "shutter": { const t = shutterSeconds(s); return t !== null && near(Math.log2(t), 0.1); } // 1/250, 1/125 ... 1", 2" ...
    case "iso": return n > 0 && near(Math.log2(n / 100), 0.05);            // 200, 400, 800 ...
    case "ev": return Number.isFinite(n) && near(n, 0.01);                  // whole EV
    case "kelvin": return n % 1000 === 0;                                   // 2000, 3000 ... K
    case "axis": return n === 0;                                             // the neutral centre
    default: return true;
  }
}

/**
 * Build labelled stops for a parameter from the camera's own list. Nothing is added or interpolated:
 * the result has exactly one entry per camera value, in camera order.
 */
export function stopsFor(kind, values, labelFn) {
  return values.map((v) => {
    const s = String(v);
    const sp = SPECIAL_LABELS[s.toLowerCase()];
    return {
      value: s,
      label: sp || (labelFn ? labelFn(s) : s),
      special: !!sp,
      major: !sp && isMainValue(kind, s),
    };
  });
}

/** Major flag of stop i: from the stop itself, else every stop (short lists) is major. */
export function stopIsMajor(stops, i) {
  const s = stops[i];
  return s.major === null || s.major === undefined ? true : !!s.major;
}

/**
 * x position of every stop on the strip (one stop = one tick). A change between a special value and a
 * numeric value gets a gap of 3/4 step, so AUTO/LOW/BULB stand apart. No extra stops are created.
 */
export function scaleLayout(stops, step) {
  const xs = [];
  let x = 0;
  for (let i = 0; i < stops.length; i++) {
    if (i > 0) x += step + (stops[i].special !== stops[i - 1].special ? step * 0.75 : 0);
    xs.push(x);
  }
  return xs;
}

/** Index of the stop nearest to strip position x. */
export function nearestStop(xs, x) {
  let best = 0;
  for (let i = 1; i < xs.length; i++) if (Math.abs(xs[i] - x) < Math.abs(xs[best] - x)) best = i;
  return best;
}

/** Strip offset so that strip position x sits under the centre marker (Center Lock). */
export function centerLockOffset(x, width) {
  return width / 2 - x;
}

/** Strip position after a drag of dx pixels from startX. Center Lock moves the scale, Fixed Range the marker. */
export function dragToX(startX, dx, variant) {
  return variant === "fixed" ? startX + dx : startX - dx;
}

/** Fixed Range: map layout positions onto the available width with a side padding. */
export function fitLayout(xs, width, pad) {
  const span = xs[xs.length - 1] || 1;
  const k = xs.length > 1 ? (width - 2 * pad) / span : 0;
  return xs.map((x) => pad + x * k);
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

const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---------------------------------------------------------------------------------------------
// Precision Scale (Center Lock default, Fixed Range alternative)
// ---------------------------------------------------------------------------------------------

/**
 * mountScale(host, {state, label, variant, format, ends, onRequest})
 *   state:      ValueState; its stops carry major/special flags (see stopsFor)
 *   variant:    "center" (Center Lock, standard) or "fixed" (Fixed Range, alternative)
 *   ends:       optional [left, right] end labels (Precision Axis)
 *   onRequest:  called with the requested camera value after a tap, drag/swipe end or key press.
 * Direct operation only: drag, swipe, tap, wheel/trackpad, arrow keys and crown on the scale; no extra slider.
 * Detents only: the scale never rests between two values and does not coast after release.
 */
export function mountScale(host, opts) {
  const o = { variant: "center", format: (s) => s.label, label: "Value", ...opts };
  const root = el("div", "qp-scale");
  root.dataset.variant = o.variant;
  root.tabIndex = 0;
  root.setAttribute("role", "slider");
  root.setAttribute("aria-label", o.label);
  const strip = el("div", "qp-scale-strip");
  const marker = el("div", "qp-scale-marker");
  root.append(strip, marker);
  if (o.ends) {
    root.classList.add("qp-axis-scale");
    root.append(el("span", "qp-axis-end left", o.ends[0]), el("span", "qp-axis-end right", o.ends[1]));
  }
  host.appendChild(root);

  let xs = [];          // strip position of every stop (px)
  let pointer = null;   // {x, startX, moved, target}

  const step = () => parseFloat(getComputedStyle(root).getPropertyValue("--qp-tick-step")) || 41;

  // One detent per camera value. A detent changes value display, scale position and marker together.
  const engine = createDetent({
    count: o.state.stops.length,
    index: Math.max(0, o.state.shownIndex),
    config: o.detent,
    onDetent: (i, dir, source) => {
      o.feedback?.pulse(source);
      const s = o.state.stops[i];
      o.state.request(s.value);
      render();
      o.onRequest?.(s.value, source);
    },
  });

  function computeXs() {
    const base = scaleLayout(o.state.stops, step());
    xs = o.variant === "fixed" ? fitLayout(base, root.clientWidth, o.ends ? 36 : 24) : base;
  }

  function build() {
    strip.textContent = "";
    o.state.stops.forEach((s, i) => {
      const t = el("button", "qp-tick");
      t.type = "button";
      t.tabIndex = -1;
      t.dataset.i = i;
      t.dataset.value = s.value;
      t.setAttribute("aria-label", o.format(s));
      if (s.special) t.classList.add("special");
      else if (stopIsMajor(o.state.stops, i)) t.classList.add("major");
      t.appendChild(el("span", "qp-tick-label qp-num", s.special ? s.label : o.format(s)));
      strip.appendChild(t);
    });
    computeXs();
  }

  function layout(i) {
    const w = root.clientWidth;
    const ticks = strip.children;
    for (let k = 0; k < ticks.length; k++) {
      ticks[k].style.transform = `translateX(${xs[k]}px)`;
      ticks[k].classList.toggle("active", k === i);
    }
    const x = xs[i] ?? 0;
    if (o.variant === "fixed") {
      strip.style.transform = "";
      marker.style.transform = `translateX(${x}px)`;
    } else {
      strip.style.transform = `translateX(${centerLockOffset(x, w)}px)`;
      marker.style.transform = `translateX(${w / 2}px)`;
    }
  }

  function render() {
    const i = o.state.shownIndex;
    if (i >= 0 && i !== engine.index) engine.set(i); // readback or list change: no pulse
    root.className = `qp-scale ${o.ends ? "qp-axis-scale " : ""}${stateClass(o.state.phase)}${pointer?.moved ? " dragging" : ""}`;
    root.dataset.phase = o.state.phase;
    root.setAttribute("aria-valuemin", 0);
    root.setAttribute("aria-valuemax", o.state.stops.length - 1);
    root.setAttribute("aria-valuenow", Math.max(0, i));
    const s = o.state.stops[i];
    root.setAttribute("aria-valuetext", s ? `${o.format(s)}, ${o.state.phase}` : "unknown");
    root.setAttribute("aria-busy", o.state.phase === "pending" ? "true" : "false");
    layout(engine.index);
  }

  root.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    root.setPointerCapture(e.pointerId);
    pointer = { x: e.clientX, startX: xs[engine.index], moved: false, target: e.target };
  });
  root.addEventListener("pointermove", (e) => {
    if (!pointer) return;
    const dx = e.clientX - pointer.x;
    if (!pointer.moved && Math.abs(dx) <= 4) return;
    pointer.moved = true;
    // The finger position picks the nearest real stop; every stop in between is passed as a detent.
    engine.dragToIndex(nearestStop(xs, dragToX(pointer.startX, dx, o.variant)), e.pointerType === "touch" ? "touch" : "drag");
  });
  const end = () => {
    if (!pointer) return;
    const p = pointer;
    pointer = null;
    if (!p.moved) {
      const t = p.target.closest?.(".qp-tick"); // tap on a tick: one jump; elsewhere: nothing
      if (t) engine.jump(+t.dataset.i, "tap");
    }
    render();
  };
  root.addEventListener("pointerup", end);
  root.addEventListener("pointercancel", end);
  root.addEventListener("wheel", (e) => {
    e.preventDefault();
    const d = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
    engine.wheel(e.deltaMode === 1 ? d * 16 : d, "wheel");
  }, { passive: false });
  root.addEventListener("keydown", (e) => {
    const k = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
    if (k) { e.preventDefault(); engine.step(k, "key"); }
    else if (e.key === "Home") { e.preventDefault(); engine.jump(0, "key"); }
    else if (e.key === "End") { e.preventDefault(); engine.jump(o.state.stops.length - 1, "key"); }
  });
  const ro = new ResizeObserver(() => { computeXs(); render(); });
  ro.observe(root);

  build();
  render();
  return {
    el: root,
    render,
    engine,
    /** Digital Crown or another rotary input; native=true when the platform already gives crown haptics. */
    crown(delta, native = false) { return engine.crown(delta, native ? "crown-native" : "crown"); },
    setStops(stops) { o.state.setStops(stops); engine.setCount(o.state.stops.length, Math.max(0, o.state.shownIndex)); build(); render(); },
    setVariant(v) { o.variant = v; root.dataset.variant = v; build(); render(); },
    destroy() { ro.disconnect(); root.remove(); },
  };
}

// ---------------------------------------------------------------------------------------------
// Precision Axis: one independent correction axis (e.g. WB A-B, G-M) on the same scale engine.
// Without a mapped value list it shows that the axis is not available instead of inventing a range.
// ---------------------------------------------------------------------------------------------

/** mountAxis(host, {state|null, label, ends:[left,right], reason, onRequest}) */
export function mountAxis(host, opts) {
  const root = el("div", "qp-axis");
  root.append(el("span", "qp-param-label", opts.label));
  host.appendChild(root);
  if (!opts.state) {
    const empty = el("div", "qp-axis-empty");
    empty.append(el("span", "qp-axis-end", opts.ends[0]), el("span", "qp-axis-note", opts.reason || "Not available"), el("span", "qp-axis-end", opts.ends[1]));
    root.appendChild(empty);
    return { el: root, render() {}, destroy() { root.remove(); } };
  }
  const scale = mountScale(root, { state: opts.state, label: opts.label, variant: "fixed", ends: opts.ends,
    feedback: opts.feedback, detent: opts.detent, onRequest: opts.onRequest });
  return { el: root, render: scale.render, crown: scale.crown, destroy() { scale.destroy(); root.remove(); } };
}

// ---------------------------------------------------------------------------------------------
// Precision Selector: categorical choices (WB presets, AF modes, metering, picture modes).
// One stop per available mode, no interpolation; tap, swipe across the row, or arrow keys.
// ---------------------------------------------------------------------------------------------

/**
 * mountSelector(host, {state, options, label, display, onRequest})
 *   options: [{value, label, short?, icon?}] in camera order; state.stops must hold the same values
 *   display(option) -> {big, sub}: the large value and the name under it
 */
export function mountSelector(host, opts) {
  const o = { display: (op) => ({ big: op.short || op.label, sub: op.label }), ...opts };
  const byValue = new Map(o.options.map((op) => [String(op.value), op]));
  for (const s of o.state.stops) if (!byValue.has(s.value)) throw new Error(`selector: no option for camera value ${s.value}`);
  const root = el("div", "qp-selector");
  const head = el("div", "qp-selector-head");
  const lab = el("div", "qp-active-label", o.label);
  const ic = el("div", "qp-selector-icon");
  const big = el("output", "qp-selector-big qp-num");
  big.setAttribute("aria-live", "polite");
  const sub = el("div", "qp-selector-sub");
  head.append(lab, ic, big, sub);
  const row = el("div", "qp-selector-row");
  row.setAttribute("role", "radiogroup");
  row.setAttribute("aria-label", o.label);
  root.append(head, row);
  host.appendChild(root);

  const btns = o.state.stops.map((s, i) => {
    const op = byValue.get(s.value);
    const b = el("button", "qp-option");
    b.type = "button";
    b.setAttribute("role", "radio");
    b.dataset.i = i;
    b.dataset.value = s.value;
    b.setAttribute("aria-label", op.label);
    b.title = op.label;
    if (op.icon) b.appendChild(icon(op.icon, "qp-icon qp-option-icon"));
    else b.appendChild(el("span", "qp-option-text", op.short || op.label));
    b.appendChild(el("span", "qp-option-tick"));
    row.appendChild(b);
    return b;
  });

  function render() {
    const i = o.state.shownIndex;
    if (engine && i >= 0 && i !== engine.index) engine.set(i); // readback: no pulse
    const op = i >= 0 ? byValue.get(o.state.stops[i].value) : null;
    const d = op ? o.display(op) : { big: "–", sub: "" };
    big.textContent = d.big;
    sub.textContent = d.sub;
    ic.textContent = "";
    if (op?.icon) ic.appendChild(icon(op.icon, "qp-icon qp-icon-primary"));
    root.className = `qp-selector ${stateClass(o.state.phase)}`;
    btns.forEach((b, k) => {
      b.setAttribute("aria-checked", k === i ? "true" : "false");
      b.tabIndex = k === Math.max(0, i) ? 0 : -1;
      b.classList.toggle("active", k === i);
    });
  }

  const engine = createDetent({
    count: o.state.stops.length,
    index: Math.max(0, o.state.shownIndex),
    config: o.detent,
    onDetent: (i, dir, source) => {
      o.feedback?.pulse(source);
      const s = o.state.stops[i];
      o.state.request(s.value);
      render();
      o.onRequest?.(s.value, source);
    },
  });

  // A row wider than its box scrolls natively (tap to pick); a row that fits picks by dragging across it.
  const overflows = () => row.scrollWidth > row.clientWidth + 1;
  const fitMode = () => { row.style.touchAction = overflows() ? "pan-x pan-y" : "pan-y"; row.classList.toggle("scrolls", overflows()); };
  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(fitMode) : null;
  ro?.observe(row);
  const hitIndex = (x) => btns.findIndex((b) => { const r = b.getBoundingClientRect(); return x >= r.left && x < r.right; });

  let drag = null;
  row.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const scroll = overflows();
    if (!scroll) row.setPointerCapture(e.pointerId);
    drag = { x: e.clientX, moved: false, scroll, target: e.target };
  });
  row.addEventListener("pointermove", (e) => {
    if (!drag) return;
    if (Math.abs(e.clientX - drag.x) > 6) drag.moved = true;
    if (!drag.moved || drag.scroll) return;
    const hit = hitIndex(e.clientX);
    if (hit >= 0) engine.dragToIndex(hit, e.pointerType === "touch" ? "touch" : "drag"); // one detent per option passed
  });
  row.addEventListener("pointerup", () => {
    if (!drag) return;
    const d = drag;
    drag = null;
    if (d.moved) return;
    const b = d.target.closest?.(".qp-option");
    if (b) engine.jump(+b.dataset.i, "tap");
  });
  row.addEventListener("pointercancel", () => { drag = null; });
  row.addEventListener("wheel", (e) => {
    if (overflows() && Math.abs(e.deltaX) > Math.abs(e.deltaY)) return; // horizontal trackpad scrolls the row
    e.preventDefault();
    engine.wheel(e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY, "wheel");
  }, { passive: false });
  row.addEventListener("keydown", (e) => {
    const k = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (!k) return;
    e.preventDefault();
    engine.step(k, "key");
    btns[engine.index].focus();
  });

  render();
  fitMode();
  return {
    el: root, render, engine,
    crown(delta, native = false) { return engine.crown(delta, native ? "crown-native" : "crown"); },
    destroy() { ro?.disconnect(); root.remove(); },
  };
}

// ---------------------------------------------------------------------------------------------
// Relative control: focus (and lens zoom, if a body/lens ever offers it) by steps in a direction.
// No absolute position is shown or invented. Unavailable on a connection = disabled with the reason.
// ---------------------------------------------------------------------------------------------

/**
 * mountRelative(host, {label, steps:[1,2,3], directions:["near","far"], available, reason, onStep})
 *   onStep(direction, size) may return a promise; the buttons wait for it (pending) before the next step.
 */
export function mountRelative(host, opts) {
  const root = el("div", "qp-relative");
  root.append(el("span", "qp-param-label", opts.label));
  const row = el("div", "qp-relative-row");
  root.appendChild(row);
  host.appendChild(root);
  const [left, right] = opts.directions || ["near", "far"];
  const steps = opts.steps || [];
  const mk = (dir, size) => {
    const b = el("button", "qp-rel-btn");
    b.type = "button";
    b.dataset.dir = dir;
    b.dataset.size = size;
    b.textContent = (dir === left ? "‹" : "›").repeat(size);
    b.setAttribute("aria-label", `${dir} ${size}`);
    return b;
  };
  [...steps].reverse().forEach((s) => row.appendChild(mk(left, s)));
  row.appendChild(el("span", "qp-rel-name", `${left.toUpperCase()} · ${right.toUpperCase()}`));
  steps.forEach((s) => row.appendChild(mk(right, s)));
  const btns = [...row.querySelectorAll("button")];
  if (!opts.available) {
    btns.forEach((b) => { b.disabled = true; });
    root.classList.add("unavailable");
    root.appendChild(el("span", "qp-axis-note", opts.reason || "Not available on this connection"));
  }
  row.addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (!b || b.disabled) return;
    btns.forEach((x) => { x.disabled = true; });
    root.setAttribute("aria-busy", "true");
    try { await opts.onStep?.(b.dataset.dir, +b.dataset.size); }
    finally { btns.forEach((x) => { x.disabled = false; }); root.setAttribute("aria-busy", "false"); }
  });
  return { el: root, destroy() { root.remove(); } };
}

// ---------------------------------------------------------------------------------------------
// QCP - Quick Control Panel: four fixed positions (aperture, shutter, ISO, EV), Center Lock scale,
// AF / Capture / Review in the lower bar. Optional WB preset selector entry (placement provisional).
// ---------------------------------------------------------------------------------------------

export const QCP_PARAMS = [
  { key: "aperture", label: "APERTURE", fmt: (s) => (s.special ? s.label : `ƒ${s.label}`), scaleFmt: (s) => s.label },
  { key: "shutter", label: "SHUTTER", fmt: (s) => (s.special ? s.label : /"$/.test(s.label) ? s.label : `1/${s.label}`), scaleFmt: (s) => s.label },
  { key: "iso", label: "ISO", fmt: (s) => s.label, scaleFmt: (s) => s.label },
  { key: "ev", label: "EV", fmt: (s) => s.label, scaleFmt: (s) => s.label },
];

/**
 * mountQCP(host, {title, connection, values, active, wb, feedback, detent, onRequest, onAction})
 *   values:     {aperture: ValueState|null, shutter, iso, ev}; null = not available in this mode/connection
 *   wb:         optional {state, options, display} for the WB preset selector
 *   onRequest(key, value): user wish for a camera value (key "wb" for the selector)
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
  const wbRow = el("div", "qp-wb-entry");
  const bar = el("div", "qp-capture-bar");
  const af = actionButton("af", "s-af", "AF");
  const cap = el("button", "qp-capture");
  cap.type = "button";
  cap.setAttribute("aria-label", "Capture");
  cap.dataset.action = "capture";
  const rev = actionButton("review", "review", "Review");
  bar.append(af, cap, rev);
  root.append(head, kicker, activeLabel, big, scaleHost, params, wbRow, bar);
  host.appendChild(root);

  let inst = null;
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
  let wbBtn = null;
  if (o.wb) {
    wbBtn = el("button", "qp-wb-btn");
    wbBtn.type = "button";
    wbBtn.dataset.key = "wb";
    wbBtn.addEventListener("click", () => { o.active = o.active === "wb" ? "aperture" : "wb"; render(true); });
    wbRow.appendChild(wbBtn);
  } else wbRow.hidden = true;
  bar.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-action]");
    if (b && !b.disabled) o.onAction?.(b.dataset.action);
  });

  function render(rebuild) {
    const isWb = o.active === "wb" && o.wb;
    if (!isWb && !o.values[o.active]) o.active = QCP_PARAMS.find((p) => o.values[p.key])?.key ?? o.active;
    activeLabel.hidden = !!isWb;
    big.hidden = !!isWb;
    if (rebuild || !inst) {
      inst?.destroy();
      inst = null;
      if (isWb) {
        inst = mountSelector(scaleHost, { ...o.wb, label: "WHITE BALANCE", feedback: o.feedback, detent: o.detent,
          onRequest: (v, src) => { o.onRequest?.("wb", v, src); render(false); } });
      } else if (o.values[o.active]) {
        const p = QCP_PARAMS.find((x) => x.key === o.active);
        inst = mountScale(scaleHost, {
          state: o.values[o.active], label: p.label, variant: o.variant || "center", format: p.scaleFmt,
          feedback: o.feedback, detent: o.detent,
          onRequest: (v, src) => { o.onRequest?.(p.key, v, src); render(false); },
        });
      }
    } else inst.render();
    if (!isWb) {
      const p = QCP_PARAMS.find((x) => x.key === o.active);
      const st = o.values[o.active];
      activeLabel.textContent = p.label;
      const s = st?.stops[st.shownIndex];
      big.textContent = s ? p.fmt(s) : "–";
      big.className = `qp-big qp-num ${st ? stateClass(st.phase) : ""}`;
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
    if (wbBtn) {
      const st = o.wb.state;
      const op = o.wb.options.find((x) => String(x.value) === st.shown);
      wbBtn.textContent = "";
      wbBtn.append(el("span", "qp-param-label", "WB"), op?.icon ? icon(op.icon, "qp-icon") : el("span", "", ""),
        el("span", `qp-wb-value ${stateClass(st.phase)}`, op ? (op.short || op.label) : "–"));
      wbBtn.classList.toggle("selected", !!isWb);
      wbBtn.setAttribute("aria-pressed", isWb ? "true" : "false");
    }
  }

  render(true);
  return {
    el: root,
    render: () => render(false),
    setActive(k) { o.active = k; render(true); },
    setVariant(v) { o.variant = v; render(true); },
    /** Digital Crown in the instrument view: changes the active parameter only. */
    crown(delta, native = false) { return inst?.crown?.(delta, native) ?? 0; },
    get active() { return o.active; },
    setConnection(c) { head.lastChild.replaceWith(connectionBadge(c)); },
    destroy() { inst?.destroy(); root.remove(); },
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
// Exposure positions read the same ValueState objects as the QCP (same values, same precision).
// Tapping an item asks to open its precision control (onOpen); unavailable functions stay visible but marked.
// ---------------------------------------------------------------------------------------------

/**
 * mountSCP(host, {title, connection, exposure, tiles, footer, onOpen})
 *   exposure: [{key, label, state?: ValueState, fmt?, value?, available}] - state wins over a fixed value
 *   tiles:    [{key, icon, value | state+fmt, label, available, reason?}]
 *   footer:   {left, right}
 */
export function mountSCP(host, opts) {
  const o = { title: "OMCAP", ...opts };
  const root = el("section", "qp-panel qp-scp");
  root.setAttribute("aria-label", "Super Control Panel");
  host.appendChild(root);

  const shown = (x) => {
    if (!x.state) return { text: x.value ?? "–", phase: x.phase || "confirmed" };
    const s = x.state.stops[x.state.shownIndex];
    return { text: s ? (x.fmt ? x.fmt(s) : s.label) : "–", phase: x.state.phase };
  };

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
      const v = shown(x);
      b.append(el("span", "qp-param-label", x.label), el("span", `qp-scp-expo-value qp-num ${stateClass(v.phase)}`, v.text));
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
      const v = shown(t);
      b.append(icon(t.icon), el("span", `qp-scp-tile-value ${stateClass(v.phase)}`, v.text), el("span", "qp-scp-tile-label", t.label));
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
  return { el: root, render, update(next) { Object.assign(o, next); render(); }, destroy() { root.remove(); } };
}

// ---------------------------------------------------------------------------------------------
// Precision Wheel - Precision Color Controls V9.1: Color Profile, Color Creator, Monochrome Profile.
// One instrument family in all three themes: ring of segments, value and name in the centre, direct
// radial grip. Themes change only paint: Daylight darker segments and a dark grip contour; Astro Red
// red segments, identified by index / hue number / filter initial. Photographic values never change.
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
 * Identifier labels around the ring (shown in Astro Red, where colour cannot identify a sector).
 *   profile: 01..12 for every sector; creator: every 5th hue number (01, 06, 11 ...) plus the active one;
 *   mono: filter initials.
 */
export function ringLabels(kind, segments, active) {
  return segments.map((s, i) => {
    if (kind === "mono") return s.short ?? s.name[0];
    const num = String(i + 1).padStart(2, "0");
    if (kind === "creator") return i % 5 === 0 || i === active ? num : "";
    return num;
  });
}

/**
 * mountColorRing(host, {kind, segments, values, active, min, max, noValue, axis, feedback, detent, onRequest})
 *   kind:     "profile" (polygon of per-segment values), "creator" (hue position + one value),
 *             "mono" (filter segments)
 *   segments: [{name, hue, short?}] from the capability mapping (hue in degrees for the swatch only)
 *   values:   per-segment integers (profile, mono) or {hue: index, value: int} (creator)
 *   onRequest({segment, value}): user wish; the caller validates against the camera or the processor
 */
export function mountColorRing(host, opts) {
  const o = { ...opts };
  const n = o.segments.length;
  const root = el("div", `qp-color qp-color-${o.kind}`);
  root.tabIndex = 0;
  root.setAttribute("role", "group");
  root.setAttribute("aria-label", { profile: "Color Profile", creator: "Color Creator", mono: "Monochrome Profile" }[o.kind]);
  const svg = document.createElementNS(SVGNS, "svg");
  svg.setAttribute("viewBox", "-150 -150 300 300");
  svg.setAttribute("class", "qp-color-svg");
  const centre = el("div", "qp-color-centre");
  const val = el("output", "qp-color-value qp-num");
  const name = el("div", "qp-color-name");
  const axisCue = el("div", "qp-color-axis");
  centre.append(val, name, axisCue);
  root.append(svg, centre);
  host.appendChild(root);
  const R = 118;
  const polar = (deg, r) => [Math.sin((deg * Math.PI) / 180) * r, -Math.cos((deg * Math.PI) / 180) * r];
  const swatch = (s) => (s.hue === null || s.hue === undefined ? "var(--qp-muted)" : `hsl(${s.hue} var(--qp-seg-s) var(--qp-seg-l))`);

  const activeIndex = () => (o.kind === "creator" ? o.values.hue : o.active);
  const getVal = (i) => (o.kind === "creator" ? o.values.value : o.values[i]);
  const fmtSigned = (v) => (v > 0 ? `+${v}` : `${v}`);

  function draw() {
    svg.textContent = "";
    const seg = 360 / n;
    const act = activeIndex();
    const labels = ringLabels(o.kind, o.segments, act);
    o.segments.forEach((s, i) => {
      const gap = o.kind === "creator" ? seg * 0.38 : seg * 0.22;
      const a0 = segmentAngle(i, n) - seg / 2 + gap / 2;
      const a1 = segmentAngle(i, n) + seg / 2 - gap / 2;
      const [x0, y0] = polar(a0, R);
      const [x1, y1] = polar(a1, R);
      const p = document.createElementNS(SVGNS, "path");
      p.setAttribute("d", o.kind === "creator" ? `M${x0} ${y0}A${R} ${R} 0 0 1 ${x1} ${y1}` : `M${x0} ${y0}L${x1} ${y1}`);
      p.setAttribute("class", `qp-color-seg${i === act ? " active" : ""}`);
      p.style.setProperty("--seg", swatch(s));
      p.dataset.i = i;
      svg.appendChild(p);
      if (labels[i]) {
        const [lx, ly] = polar(segmentAngle(i, n), R + 20);
        const t = document.createElementNS(SVGNS, "text");
        t.setAttribute("x", lx);
        t.setAttribute("y", ly);
        t.setAttribute("class", `qp-color-id${i === act ? " active" : ""}`);
        t.textContent = labels[i];
        svg.appendChild(t);
      }
    });
    if (o.kind !== "profile") {
      const inner = document.createElementNS(SVGNS, "circle");
      inner.setAttribute("r", 66);
      inner.setAttribute("class", "qp-color-inner");
      svg.appendChild(inner);
    }
    if (o.kind === "profile") {
      const pts = o.segments.map((_, i) => polar(segmentAngle(i, n), valueToRadius(getVal(i), o.min, o.max) * (R - 14)));
      const poly = document.createElementNS(SVGNS, "polygon");
      poly.setAttribute("points", pts.map((p) => p.join(",")).join(" "));
      poly.setAttribute("class", "qp-color-poly");
      svg.appendChild(poly);
    }
    // Grip at the active segment
    // Grip radius shows the level on the radial axis (Creator: saturation between 40 and R-10), never in between.
    const r = o.kind === "profile" ? valueToRadius(getVal(act), o.min, o.max) * (R - 14)
      : o.kind === "creator" ? 40 + ((getVal(act) - o.min) / (o.max - o.min || 1)) * (R - 50) : R - 28;
    const [gx, gy] = polar(segmentAngle(act, n), r);
    const g = document.createElementNS(SVGNS, "circle");
    g.setAttribute("cx", gx);
    g.setAttribute("cy", gy);
    g.setAttribute("r", 10);
    g.setAttribute("class", "qp-color-grip");
    g.style.setProperty("--seg", swatch(o.segments[act]));
    svg.appendChild(g);
    const v = getVal(act);
    // noValue: the camera has only the choice, no level (E-M1 B&W Filter); show the initial instead.
    val.textContent = o.noValue ? (o.segments[act].short ?? "") : o.kind === "creator" ? String(v).padStart(2, "0") : fmtSigned(v);
    name.textContent = o.kind === "creator" ? `HUE ${String(act + 1).padStart(2, "0")}` : o.segments[act].name.toUpperCase();
    axisCue.textContent = o.axis === "radial" ? (o.kind === "mono" ? "STRENGTH" : "SATURATION") : o.kind === "creator" ? "HUE" : o.kind === "mono" ? "FILTER" : "COLOUR";
    root.setAttribute("aria-valuetext", `${name.textContent} ${val.textContent}, ${axisCue.textContent.toLowerCase()} active`);
    root.className = `qp-color qp-color-${o.kind} ${stateClass(o.phase || "confirmed")} axis-${o.axis}`;
  }

  // Two detent axes per instrument (V2.1): the angle picks a sector / hue (runs round), the radius a level.
  //   profile: angle = colour sector, radius = saturation level of that sector
  //   creator: angle = hue, radius = saturation
  //   mono:    angle = filter; radius = filter strength only where the body has it (E-M1: none -> noValue)
  // Touch near the ring selects the angle axis, inside the ring the radial axis; wheel, keys and crown change
  // only the active axis. Each detent pulses once; values never fall between two valid steps.
  const hasRadial = !o.noValue;
  o.axis = o.axis || (o.kind === "creator" || !hasRadial ? "angle" : "radial");
  const levels = hasRadial ? o.max - o.min + 1 : 1;
  const angle = createDetent({
    count: n, index: activeIndex(), wrap: true, config: o.detent,
    onDetent: (i, dir, source) => {
      o.feedback?.pulse(source);
      if (o.kind === "creator") o.values = { hue: i, value: o.values.value };
      else o.active = i;
      radial.set(getVal(i) - o.min);
      changed(i, source);
    },
  });
  const radial = createDetent({
    count: levels, index: hasRadial ? getVal(activeIndex()) - o.min : 0, config: o.detent,
    onDetent: (k, dir, source) => {
      o.feedback?.pulse(source);
      const i = activeIndex();
      const v = o.min + k;
      if (o.kind === "creator") o.values = { hue: o.values.hue, value: v };
      else { o.values = o.values.slice(); o.values[i] = v; }
      changed(i, source);
    },
  });

  function changed(i, source) {
    o.phase = "requested";
    draw();
    o.onRequest?.({ segment: i, value: o.noValue ? 0 : getVal(i), axis: o.axis, source });
  }

  function setAxis(a) {
    if (a === "radial" && !hasRadial) a = "angle";
    if (o.axis !== a) { o.axis = a; draw(); }
  }

  let drag = null;
  const geom = (e) => {
    const b = svg.getBoundingClientRect();
    const x = ((e.clientX - b.left) / b.width) * 300 - 150;
    const y = ((e.clientY - b.top) / b.height) * 300 - 150;
    return { deg: (Math.atan2(x, -y) * 180) / Math.PI, r: Math.hypot(x, y) };
  };
  const radialIndex = (r) => {
    // profile: the polygon radius; creator: inner circle (66) to ring (R); both snap to whole levels
    const lo = o.kind === "profile" ? 0.45 * (R - 14) : 40;
    const hi = o.kind === "profile" ? R - 14 : R - 10;
    return Math.round(Math.max(0, Math.min(1, (r - lo) / (hi - lo))) * (levels - 1));
  };
  root.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    root.setPointerCapture(e.pointerId);
    const g = geom(e);
    // Near the ring: angle axis. Inside: radial axis (Profile: the polygon; Creator: inside the inner circle area).
    const onRing = g.r > R - 22;
    setAxis(onRing || !hasRadial ? "angle" : "radial");
    drag = { src: e.pointerType === "touch" ? "touch" : "drag" };
    move(e);
  });
  root.addEventListener("pointermove", (e) => { if (drag) move(e); });
  root.addEventListener("pointerup", () => { drag = null; });
  root.addEventListener("pointercancel", () => { drag = null; });
  function move(e) {
    const g = geom(e);
    if (o.axis === "angle") angle.dragToIndex(angleToSegment(g.deg, n), drag.src);
    else radial.dragToIndex(radialIndex(g.r), drag.src);
  }
  root.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") { setAxis("angle"); angle.step(e.key === "ArrowRight" ? 1 : -1, "key"); }
    else if ((e.key === "ArrowUp" || e.key === "ArrowDown") && hasRadial) { setAxis("radial"); radial.step(e.key === "ArrowUp" ? 1 : -1, "key"); }
    else return;
    e.preventDefault();
  });
  const activeEngine = () => (o.axis === "angle" ? angle : radial);
  root.addEventListener("wheel", (e) => {
    e.preventDefault();
    activeEngine().wheel(-(e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY), "wheel");
  }, { passive: false });

  draw();
  return {
    el: root,
    get axis() { return o.axis; },
    setAxis,
    /** Digital Crown: changes only the active axis (Profile: saturation, Creator: active axis, Mono: filter). */
    crown(delta, native = false) {
      // Profile: touch picks the colour, the crown sets its level. Creator: active axis. Mono: strength if any, else filter.
      const eng = o.kind === "creator" ? activeEngine() : hasRadial ? radial : angle;
      return eng.crown(delta, native ? "crown-native" : "crown");
    },
    confirm(values) { o.values = values; o.phase = "confirmed"; angle.set(activeIndex()); radial.set(hasRadial ? getVal(activeIndex()) - o.min : 0); draw(); },
    setPhase(p) { o.phase = p; draw(); },
    destroy() { root.remove(); },
  };
}
