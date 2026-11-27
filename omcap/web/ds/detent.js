// Precision Detent Engine (Precision Instrument Library V2.1, REQ-D06).
// One interaction core for every discrete instrument and every input: mouse drag, wheel/trackpad, keyboard,
// touch/swipe and the Digital Crown. It moves an index over a list of valid camera values, one detent at a
// time: no in-between values, no kinetic scrolling, no overshoot. Every detent actually passed gives exactly
// one feedback pulse; at the limits nothing moves and nothing pulses. The engine knows no camera and no theme.

/** Tunable values (Motion & Feedback design decides the final numbers). */
export const DETENT_DEFAULTS = {
  wheelPxPerDetent: 40,     // accumulated wheel/trackpad delta (px) for one detent
  dragPxPerDetent: 41,      // pointer travel for one detent (the tick spacing of the scale)
  crownPerDetent: 1,        // Digital Crown rotation units for one detent (watchOS: crown delta)
  maxDetentsPerEvent: 12,   // a single input event never jumps further (fast flick of a wheel)
};

/**
 * createDetent({count, index, onDetent, onEdge, config})
 *   count:     number of valid values (the capability list length)
 *   index:     current index
 *   onDetent(index, direction, source): called once per detent passed (selection changed)
 *   onEdge(direction, source): called once when an input pushes against a limit (no pulse, optional cue)
 *   wrap:      true for rings (colour sectors): no limits, the index runs round
 * Inputs: step(n, source), wheel(delta, source), crown(delta, source), dragStart/dragMove(px)/dragEnd, set(index).
 */
export function createDetent(opts) {
  const cfg = { ...DETENT_DEFAULTS, ...(opts.config || {}) };
  let count = opts.count;
  let index = Math.max(0, Math.min(count - 1, opts.index ?? 0));
  let wheelAcc = 0;
  let crownAcc = 0;
  let drag = null;
  let edgeHeld = false; // pushing against a limit reports the edge once, not per event

  const wrap = !!opts.wrap;
  const mod = (i) => ((i % count) + count) % count;

  function stepTo(target, source) {
    if (!wrap) target = Math.max(0, Math.min(count - 1, target));
    const dir = Math.sign(target - index);
    if (dir === 0) return 0;
    let passed = 0;
    let pos = index;
    while (pos !== target) {
      pos += dir;
      passed += 1;
      index = wrap ? mod(pos) : pos;
      opts.onDetent?.(index, dir, source);
    }
    edgeHeld = false;
    return passed;
  }

  /** Shortest signed distance between two ring positions. */
  const ringDelta = (from, to) => { const d = mod(to - from); return d > count / 2 ? d - count : d; };

  function step(n, source = "key") {
    if (!n) return 0;
    n = Math.max(-cfg.maxDetentsPerEvent, Math.min(cfg.maxDetentsPerEvent, Math.trunc(n)));
    const atEdge = !wrap && ((n > 0 && index >= count - 1) || (n < 0 && index <= 0));
    if (atEdge) {
      if (!edgeHeld) opts.onEdge?.(Math.sign(n), source);
      edgeHeld = true;
      return 0;
    }
    return stepTo(index + n, source);
  }

  function accumulate(acc, delta, per) {
    acc += delta;
    const n = acc > 0 ? Math.floor(acc / per) : Math.ceil(acc / per);
    return [acc - n * per, n];
  }

  return {
    get index() { return index; },
    get count() { return count; },
    config: cfg,
    /** Programmatic set (camera readback, list change): no feedback, no edge. */
    set(i) { index = Math.max(0, Math.min(count - 1, i)); wheelAcc = 0; crownAcc = 0; },
    setCount(n, i = index) { count = n; index = Math.max(0, Math.min(n - 1, i)); },
    step,
    /** Wheel or trackpad: small deltas accumulate until one detent; leftover stays for the next event. */
    wheel(delta, source = "wheel") {
      // Reversing direction drops the leftover so a tiny reverse movement cannot cross a detent at once.
      if (Math.sign(delta) !== Math.sign(wheelAcc)) wheelAcc = 0;
      let n;
      [wheelAcc, n] = accumulate(wheelAcc, delta, cfg.wheelPxPerDetent);
      return step(n, source);
    },
    /** Digital Crown (or any rotary input) with its own sensitivity. */
    crown(delta, source = "crown") {
      if (Math.sign(delta) !== Math.sign(crownAcc)) crownAcc = 0;
      let n;
      [crownAcc, n] = accumulate(crownAcc, delta, cfg.crownPerDetent);
      return step(n, source);
    },
    /** Pointer drag: the index follows the finger detent by detent; releasing does not coast. */
    dragStart(px, source = "drag") { drag = { px, start: index, source }; },
    dragMove(px, sign = 1) {
      if (!drag) return 0;
      const n = Math.round(((px - drag.px) * sign) / cfg.dragPxPerDetent);
      const target = drag.start + n;
      if (target === index) return 0;
      const clamped = Math.max(0, Math.min(count - 1, target));
      if (clamped === index) {
        if (!edgeHeld) opts.onEdge?.(Math.sign(target - index), drag.source);
        edgeHeld = true;
        return 0;
      }
      return stepTo(clamped, drag.source);
    },
    /** Pointer that maps straight to a detent (drag over ticks, angle on a ring): passes every detent between. */
    dragToIndex(i, source = "drag") { return stepTo(wrap ? index + ringDelta(index, i) : i, source); },
    /** Tap on a value: one jump, one pulse (nothing is traversed). */
    jump(i, source = "tap") {
      i = wrap ? mod(i) : Math.max(0, Math.min(count - 1, i));
      if (i === index) return 0;
      const dir = Math.sign(i - index);
      index = i;
      opts.onDetent?.(index, dir, source);
      return 1;
    },
    dragEnd() { const moved = drag && index !== drag.start; drag = null; edgeHeld = false; return !!moved; },
  };
}

// ---------------------------------------------------------------------------------------------
// Multisensory feedback: one pulse per detent; sound and haptic independently switchable.
// ---------------------------------------------------------------------------------------------

const STORE_KEY = "qp.feedback";

/** Platform defaults (V2.1 table): desktop = click sound, phone/tablet = haptic, watch = native crown haptic. */
export function feedbackDefaults(env) {
  const touch = !!env.coarsePointer;
  return {
    sound: !touch,                       // desktop primary; optional on touch devices
    haptic: touch && !!env.canVibrate,   // phone primary where the platform supports it
    motion: !env.reducedMotion,          // short detent motion; off with Reduced Motion
    volume: 0.18,
  };
}

/**
 * createFeedback({env, settings, audio, vibrate, now})
 *   env: {coarsePointer, canVibrate, reducedMotion}; audio()/vibrate(ms) are injectable for tests.
 *   pulse(source): one detent pulse. Native crown haptics ("crown-native") never get a second haptic.
 *   setSilent(true): silent shooting situation (e.g. Silent drive): no sound, haptic stays.
 * Camera confirmations do not pulse: the detent already gave the local feedback.
 */
export function createFeedback(opts = {}) {
  const env = opts.env || {};
  let settings = { ...feedbackDefaults(env), ...(opts.settings || {}) };
  if (!opts.settings) {
    try { Object.assign(settings, JSON.parse(localStorage.getItem(STORE_KEY) || "{}")); } catch { /* storage blocked */ }
  }
  let silent = false;
  const now = opts.now || (() => (typeof performance !== "undefined" ? performance.now() : Date.now()));
  const log = [];
  let lastSound = -1e9;

  const playClick = opts.audio || makeClick();
  const buzz = opts.vibrate || ((ms) => (typeof navigator !== "undefined" && navigator.vibrate ? navigator.vibrate(ms) : false));

  return {
    get settings() { return { ...settings }; },
    get silent() { return silent; },
    log,
    set(next) {
      settings = { ...settings, ...next };
      try { localStorage.setItem(STORE_KEY, JSON.stringify(settings)); } catch { /* ignore */ }
    },
    setSilent(v) { silent = !!v; },
    pulse(source = "input") {
      const t = now();
      const ev = { t, source, sound: false, haptic: false };
      if (settings.sound && !silent) {
        // Very fast input: clicks closer than 12 ms would merge into noise; the pulse still counts.
        if (t - lastSound >= 12) { playClick(settings.volume); lastSound = t; }
        ev.sound = true;
      }
      if (settings.haptic && source !== "crown-native") { buzz(8); ev.haptic = true; }
      log.push(ev);
      if (log.length > 200) log.shift();
      return ev;
    },
  };
}

/** A short, dry mechanical click synthesised with WebAudio (no audio file); silent where WebAudio is missing. */
function makeClick() {
  let ctx = null;
  return (volume) => {
    try {
      const AC = globalThis.AudioContext || globalThis.webkitAudioContext;
      if (!AC) return;
      ctx = ctx || new AC();
      const t = ctx.currentTime;
      const len = Math.floor(ctx.sampleRate * 0.012);
      const buf = ctx.createBuffer(1, len, ctx.sampleRate);
      const d = buf.getChannelData(0);
      for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / len) ** 4;
      const src = ctx.createBufferSource();
      src.buffer = buf;
      const bp = ctx.createBiquadFilter();
      bp.type = "bandpass";
      bp.frequency.value = 3200;
      bp.Q.value = 1.2;
      const g = ctx.createGain();
      g.gain.setValueAtTime(volume, t);
      src.connect(bp).connect(g).connect(ctx.destination);
      src.start(t);
    } catch { /* audio unavailable: visual detent stays */ }
  };
}

// ---------------------------------------------------------------------------------------------
// Command gate: at most one camera command in flight per value; newer wishes replace the waiting one.
// Fast detents never build a queue of stale commands.
// ---------------------------------------------------------------------------------------------

/**
 * createCommandGate(state, send)
 *   state: ValueState (requested -> pending -> confirmed/failed)
 *   send(value) -> Promise<readback value>: the camera adapter; rejects on refusal or timeout
 * wish() after each detent: sends now if nothing is in flight, otherwise only the newest wish waits.
 */
export function createCommandGate(state, send, hooks = {}) {
  let inFlight = false;
  let waiting = null;
  const stats = { sent: 0, superseded: 0 };
  async function pump() {
    if (inFlight) return;
    waiting = null;
    const v = state.send();
    if (v === null) return;
    inFlight = true;
    stats.sent += 1;
    hooks.onSend?.(v);
    try {
      const back = await send(v);
      // A newer wish that arrived meanwhile stays requested; the readback only updates the camera value.
      const newer = state.requested;
      state.confirm(back);
      if (newer !== null) state.request(newer); // clears itself if it equals the camera value now
      hooks.onReadback?.(back, v);
    } catch (e) {
      const newer = state.requested;
      state.fail(e?.message || "not confirmed");
      if (newer !== null) state.request(newer);
      hooks.onError?.(e, v);
    } finally {
      inFlight = false;
    }
    if (state.requested !== null) pump();
  }
  return {
    stats,
    get busy() { return inFlight; },
    /** Call after every local detent (state.request already done). */
    wish() {
      if (inFlight) {
        if (waiting !== null && waiting !== state.requested) stats.superseded += 1;
        waiting = state.requested;
        return Promise.resolve();
      }
      return pump();
    },
  };
}
