// Quiet Precision V4.0 view architecture (Adaptive View Architecture V1.0, Figma 34:967; REQ-D06).
// Pure state model plus a small DOM shell. View, image scaling (Fit/Fill), theme, device, display
// orientation and camera orientation are independent axes. No transition here ever produces a camera
// action: views only change layout. Camera state lives elsewhere and is passed through untouched.

export const VIEWS = ["full", "clean", "panel"];
export const SCALING = ["fit", "fill"];
export const THEMES = ["dark", "daylight", "astro"];
export const DEVICES = ["desktop", "mobile", "watch"];
export const DISPLAY = ["landscape", "portrait"];
export const CAMERA_ORIENTATION = [0, 90, 180, 270];

// Split between live view and instruments (desktop, Resizable Panel variant A).
// 65/35 is the approved starting proposal; the limits are a PROPOSAL (Figma: "exact constraints open").
export const SPLIT_DEFAULT = 0.65;
export const SPLIT_MIN = 0.4;
export const SPLIT_MAX = 0.8;

/** Default view per device and display orientation (Figma "Device / default state"). */
export function defaultView(device, display) {
  if (device === "desktop") return "panel";
  if (device === "watch") return "full";
  return display === "portrait" ? "panel" : "full";
}

export function initialState(device = "desktop", display = "landscape") {
  return {
    device, display,
    view: defaultView(device, display),
    returnView: null,          // where Clean View goes back to (explicit return path)
    scaling: "fit",            // Fit is the default
    theme: "dark",             // Dark is primary
    split: SPLIT_DEFAULT,
    cameraOrientation: 0,      // from the camera (level/orientation sensor), never from the display
  };
}

const oneOf = (list, v, what) => {
  if (!list.includes(v)) throw new Error(`${what}: ${v} is not one of ${list.join(", ")}`);
  return v;
};

/**
 * reduce(state, action) -> next state. Actions:
 *   {type:"view", view}  {type:"clean"} (toggle, remembers the way back)  {type:"scaling", scaling}
 *   {type:"theme", theme}  {type:"split", split}  {type:"display", display}
 *   {type:"device", device}  {type:"cameraOrientation", deg}
 * The returned object is new; unknown actions throw (no silent no-ops).
 */
export function reduce(s, a) {
  switch (a.type) {
    case "view": {
      const view = oneOf(VIEWS, a.view, "view");
      return { ...s, view, returnView: view === "clean" ? (s.view === "clean" ? s.returnView : s.view) : null };
    }
    case "clean":
      return s.view === "clean"
        ? { ...s, view: s.returnView || "full", returnView: null }
        : { ...s, view: "clean", returnView: s.view };
    case "scaling":
      return { ...s, scaling: oneOf(SCALING, a.scaling, "scaling") };
    case "theme":
      return { ...s, theme: oneOf(THEMES, a.theme, "theme") };
    case "split":
      return { ...s, split: clampSplit(a.split) };
    case "display":
      // Turning the phone changes only the display axis; view, theme and camera orientation stay.
      return { ...s, display: oneOf(DISPLAY, a.display, "display") };
    case "device":
      return { ...s, device: oneOf(DEVICES, a.device, "device") };
    case "cameraOrientation":
      return { ...s, cameraOrientation: oneOf(CAMERA_ORIENTATION, a.deg, "cameraOrientation") };
    default:
      throw new Error(`unknown view action ${a.type}`);
  }
}

export function clampSplit(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return SPLIT_DEFAULT;
  return Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, n));
}

/** Overlays shown in a view: Full shows essential controls over the image, Clean none, Panel uses the side panel. */
export function overlaysFor(view) {
  return { full: "essential", clean: "none", panel: "none" }[view];
}

/** Watch has no side panel: Panel View there is a separate instrument screen instead of a split. */
export function layoutFor(s) {
  if (s.view !== "panel") return { kind: "viewport" };
  if (s.device === "watch") return { kind: "instrument-screen" };
  if (s.device === "desktop") return { kind: "split-horizontal", live: s.split };
  return s.display === "portrait" ? { kind: "split-vertical" } : { kind: "split-horizontal", live: s.split };
}

/**
 * Preview geometry of the incoming camera frame inside the viewport.
 *   fit:  the whole frame, bars where the aspect ratios differ (default)
 *   fill: covers the viewport; only the preview is cropped (the captured image is unchanged)
 * Camera orientation 90/270 swaps the frame's sides before fitting. Returns pixels and the crop share.
 */
export function previewGeometry(frameW, frameH, vpW, vpH, scaling, cameraOrientation = 0) {
  const turned = cameraOrientation === 90 || cameraOrientation === 270;
  const fw = turned ? frameH : frameW;
  const fh = turned ? frameW : frameH;
  const k = scaling === "fill" ? Math.max(vpW / fw, vpH / fh) : Math.min(vpW / fw, vpH / fh);
  const w = fw * k;
  const h = fh * k;
  const visible = Math.min(1, vpW / w) * Math.min(1, vpH / h);
  return { w, h, x: (vpW - w) / 2, y: (vpH - h) / 2, cropped: +(1 - visible).toFixed(4) };
}

// ---------------------------------------------------------------------------------------------
// Store with per-viewer persistence of view preferences only (never camera state)
// ---------------------------------------------------------------------------------------------

const PERSIST = ["view", "scaling", "theme", "split"];

export function createViewStore(init, key = "qp.view") {
  let s = init;
  try {
    const saved = JSON.parse(localStorage.getItem(key) || "null");
    if (saved) for (const k of PERSIST) if (k in saved) s = reduce(s, k === "view" ? { type: "view", view: saved.view } : { type: k, [k]: saved[k] });
  } catch { /* storage blocked or bad data: start from defaults */ }
  const subs = new Set();
  return {
    get: () => s,
    dispatch(a) {
      s = reduce(s, a);
      try { localStorage.setItem(key, JSON.stringify(Object.fromEntries(PERSIST.map((k) => [k, s[k]])))); } catch { /* ignore */ }
      subs.forEach((f) => f(s, a));
      return s;
    },
    subscribe(f) { subs.add(f); return () => subs.delete(f); },
  };
}

// ---------------------------------------------------------------------------------------------
// DOM shell: live view area + instrument panel with a draggable divider (desktop variant A).
// ---------------------------------------------------------------------------------------------

/**
 * mountViewShell(host, {store, live, panel, frame:{w,h}})
 *   live:  element that shows the camera frame (img/canvas/video), sized by previewGeometry
 *   panel: element with SCP/QCP
 * The shell writes data attributes and sizes only. It never calls the camera.
 */
export function mountViewShell(host, { store, live, panel, frame }) {
  const root = document.createElement("div");
  root.className = "qp-shell";
  const stage = document.createElement("div");
  stage.className = "qp-stage";
  const divider = document.createElement("div");
  divider.className = "qp-divider";
  divider.tabIndex = 0;
  divider.setAttribute("role", "separator");
  divider.setAttribute("aria-orientation", "vertical");
  divider.setAttribute("aria-label", "Resize live view and instruments");
  const side = document.createElement("aside");
  side.className = "qp-side";
  stage.appendChild(live);
  side.appendChild(panel);
  root.append(stage, divider, side);
  host.appendChild(root);

  function apply() {
    const s = store.get();
    const lay = layoutFor(s);
    root.dataset.view = s.view;
    root.dataset.layout = lay.kind;
    root.dataset.scaling = s.scaling;
    root.dataset.device = s.device;
    root.dataset.display = s.display;
    root.dataset.qpTheme = s.theme;
    root.dataset.overlays = overlaysFor(s.view);
    root.style.setProperty("--qp-split", `${(lay.live ?? s.split) * 100}%`);
    divider.setAttribute("aria-valuenow", Math.round(s.split * 100));
    divider.setAttribute("aria-valuemin", Math.round(SPLIT_MIN * 100));
    divider.setAttribute("aria-valuemax", Math.round(SPLIT_MAX * 100));
    const r = stage.getBoundingClientRect();
    if (r.width && frame?.w) {
      const g = previewGeometry(frame.w, frame.h, r.width, r.height, s.scaling, s.cameraOrientation);
      // A turned camera frame keeps its own sides and is rotated around the centre of its box.
      const turned = s.cameraOrientation === 90 || s.cameraOrientation === 270;
      const [ew, eh] = turned ? [g.h, g.w] : [g.w, g.h];
      Object.assign(live.style, { position: "absolute", left: `${g.x + (g.w - ew) / 2}px`, top: `${g.y + (g.h - eh) / 2}px`,
        width: `${ew}px`, height: `${eh}px` });
      live.style.transform = s.cameraOrientation ? `rotate(${s.cameraOrientation}deg)` : "";
      live.dataset.cropped = g.cropped;
    }
  }

  let drag = null;
  divider.addEventListener("pointerdown", (e) => { drag = root.getBoundingClientRect(); divider.setPointerCapture(e.pointerId); });
  divider.addEventListener("pointermove", (e) => { if (drag) store.dispatch({ type: "split", split: (e.clientX - drag.left) / drag.width }); });
  divider.addEventListener("pointerup", () => { drag = null; });
  divider.addEventListener("keydown", (e) => {
    const d = { ArrowLeft: -0.05, ArrowRight: 0.05 }[e.key];
    if (d) { e.preventDefault(); store.dispatch({ type: "split", split: store.get().split + d }); }
  });
  const unsub = store.subscribe(apply);
  const ro = new ResizeObserver(apply);
  ro.observe(stage);
  apply();
  return { el: root, apply, destroy() { unsub(); ro.disconnect(); root.remove(); } };
}
