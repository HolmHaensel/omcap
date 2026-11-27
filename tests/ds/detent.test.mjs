// Precision Detent Engine, feedback and command gate (no DOM). Run: node --test tests/ds
import test from "node:test";
import assert from "node:assert/strict";
import { createDetent, createFeedback, createCommandGate, feedbackDefaults } from "../../omcap/web/ds/detent.js";
import { ValueState } from "../../omcap/web/ds/precision.js";
import { crownTarget, initialState, reduce } from "../../omcap/web/ds/views.js";

function rig(count, index, extra = {}) {
  const pulses = [];
  const edges = [];
  const d = createDetent({ count, index, onDetent: (i, dir, src) => pulses.push([i, dir, src]), onEdge: (dir) => edges.push(dir), ...extra });
  return { d, pulses, edges };
}

test("discrete steps in both directions, one pulse per detent", () => {
  const { d, pulses } = rig(10, 5);
  assert.equal(d.step(1), 1);
  assert.equal(d.step(-3), 3);
  assert.equal(d.index, 3);
  assert.deepEqual(pulses.map((p) => p[0]), [6, 5, 4, 3]);
  assert.deepEqual(pulses.map((p) => p[1]), [1, -1, -1, -1]);
});

test("no pulses and no movement at the limits; the edge is reported once while held", () => {
  const { d, pulses, edges } = rig(5, 4);
  assert.equal(d.step(1), 0);
  assert.equal(d.step(1), 0);
  assert.equal(d.wheel(400), 0);
  assert.equal(pulses.length, 0);
  assert.deepEqual(edges, [1]);
  d.step(-1);
  assert.equal(d.step(5 * -1), 4 - 1 > 0 ? 3 : 0); // runs to 0, stops there
  assert.equal(d.index, 0);
  assert.equal(d.step(-1), 0);
});

test("slow and fast wheel input: deltas accumulate to whole detents, nothing in between", () => {
  const { d, pulses } = rig(50, 10, { config: { wheelPxPerDetent: 40 } });
  for (let i = 0; i < 8; i++) d.wheel(10);  // slow trackpad: 80 px -> 2 detents
  assert.equal(d.index, 12);
  d.wheel(400);                             // fast flick: 10 detents in one event
  assert.equal(d.index, 22);
  d.wheel(2000);                            // capped per event, no runaway
  assert.equal(d.index, 34);
  assert.equal(pulses.length, 24);
  d.wheel(30); d.wheel(-5);                 // reversing drops the leftover: no detent from a small reverse
  assert.equal(d.index, 34);
});

test("dragToIndex passes every value between; a tap jumps with one pulse", () => {
  const { d, pulses } = rig(30, 0);
  d.dragToIndex(4);
  assert.deepEqual(pulses.map((p) => p[0]), [1, 2, 3, 4]);
  d.jump(20, "tap");
  assert.equal(pulses.length, 5);
  assert.equal(d.jump(20, "tap"), 0);  // same value: no pulse
});

test("ring (colour sectors) wraps round and takes the short way", () => {
  const { d, pulses } = rig(12, 11, { wrap: true });
  d.step(1);
  assert.equal(d.index, 0);
  d.dragToIndex(10);           // 0 -> 10 the short way: -2 detents
  assert.deepEqual(pulses.map((p) => p[0]), [0, 11, 10]);
});

test("programmatic set (camera readback) never pulses", () => {
  const { d, pulses } = rig(10, 2);
  d.set(7);
  assert.equal(d.index, 7);
  assert.equal(pulses.length, 0);
});

test("crown: sensitivity, native haptic is not doubled, sound still once", () => {
  const { d, pulses } = rig(10, 0, { config: { crownPerDetent: 0.5 } });
  d.crown(0.25); assert.equal(d.index, 0);
  d.crown(0.25); assert.equal(d.index, 1);
  const buzz = [];
  const clicks = [];
  const fb = createFeedback({ env: {}, settings: { sound: true, haptic: true, motion: true, volume: 0.1 },
    audio: () => clicks.push(1), vibrate: (ms) => buzz.push(ms), now: (() => { let t = 0; return () => (t += 20); })() });
  fb.pulse("crown-native");
  fb.pulse("crown");
  assert.equal(buzz.length, 1);    // native crown haptic: no second haptic from the app
  assert.equal(clicks.length, 2);
  assert.equal(fb.log.length, 2);
  assert.equal(pulses.length, 1);
});

test("feedback switches are independent; silent shooting mutes sound only; defaults per platform", () => {
  const clicks = [];
  const buzz = [];
  const fb = createFeedback({ env: {}, settings: { sound: true, haptic: false, motion: true }, audio: () => clicks.push(1), vibrate: () => buzz.push(1), now: () => 1000 + clicks.length * 50 });
  fb.pulse("key");
  fb.set({ sound: false, haptic: true });
  fb.pulse("key");
  fb.set({ sound: true });
  fb.setSilent(true);
  fb.pulse("key");
  assert.equal(clicks.length, 1);
  assert.equal(buzz.length, 2);
  assert.deepEqual(feedbackDefaults({ coarsePointer: false }), { sound: true, haptic: false, motion: true, volume: 0.18 });
  assert.deepEqual(feedbackDefaults({ coarsePointer: true, canVibrate: true, reducedMotion: true }), { sound: false, haptic: true, motion: false, volume: 0.18 });
});

// ---- command gate: latest wins, no stale queue, readback and refusal ----

function deferredCamera() {
  const calls = [];
  const send = (v) => new Promise((resolve, reject) => calls.push({ v, resolve, reject }));
  return { calls, send };
}
const tick = () => new Promise((r) => setImmediate(r));

test("fast detents send at most one command at a time; only the newest waiting wish follows", async () => {
  const st = new ValueState(["1", "2", "3", "4", "5", "6"], "1");
  const cam = deferredCamera();
  const gate = createCommandGate(st, cam.send);
  for (const v of ["2", "3", "4", "5", "6"]) { st.request(v); gate.wish(); }
  assert.equal(cam.calls.length, 1);          // "2" in flight
  assert.equal(st.phase, "requested");         // "6" waits (the wish shows), "3"-"5" were replaced
  assert.equal(gate.stats.superseded, 3);
  cam.calls[0].resolve("2");
  await tick(); await tick();
  assert.deepEqual(cam.calls.map((c) => c.v), ["2", "6"]);
  assert.equal(st.phase, "pending");
  cam.calls[1].resolve("6");
  await tick(); await tick();
  assert.equal(st.phase, "confirmed");
  assert.equal(st.confirmed, "6");
});

test("delayed readback: the state stays pending until the camera answers; refusal keeps the camera value", async () => {
  const st = new ValueState(["1", "2", "3"], "1");
  const cam = deferredCamera();
  const gate = createCommandGate(st, cam.send);
  st.request("3"); gate.wish();
  assert.equal(st.phase, "pending");
  await tick();
  assert.equal(st.phase, "pending");
  cam.calls[0].reject(new Error("refused"));
  await tick(); await tick();
  assert.equal(st.phase, "failed");
  assert.equal(st.confirmed, "1");
  assert.equal(st.shown, "1");
});

test("turning back to the value already on its way sends nothing new", async () => {
  const st = new ValueState(["1", "2", "3"], "1");
  const cam = deferredCamera();
  const gate = createCommandGate(st, cam.send);
  st.request("2"); gate.wish();
  st.request("3"); gate.wish();
  st.request("2"); gate.wish();   // back to the in-flight value
  cam.calls[0].resolve("2");
  await tick(); await tick();
  assert.equal(cam.calls.length, 1);
  assert.equal(st.phase, "confirmed");
});

// ---- Digital Crown routing ----

test("crown target by context: live zoom, instrument value, colour axes, timer, review", () => {
  const s = initialState("watch");
  assert.deepEqual(crownTarget(s), { target: "zoom" });
  const panel = reduce(s, { type: "view", view: "panel" });
  assert.deepEqual(crownTarget(panel), { target: "value" });
  assert.deepEqual(crownTarget(panel, { screen: "instrument", instrument: { kind: "profile", axis: "angle" } }), { target: "saturation", axis: "radial" });
  assert.deepEqual(crownTarget(panel, { screen: "instrument", instrument: { kind: "creator", axis: "angle" } }), { target: "hue", axis: "angle" });
  assert.deepEqual(crownTarget(panel, { screen: "instrument", instrument: { kind: "creator", axis: "radial" } }), { target: "saturation", axis: "radial" });
  assert.deepEqual(crownTarget(panel, { screen: "instrument", instrument: { kind: "mono" } }), { target: "filter", axis: "angle" });
  assert.deepEqual(crownTarget(panel, { screen: "instrument", instrument: { kind: "mono", hasStrength: true } }), { target: "strength", axis: "radial" });
  assert.deepEqual(crownTarget(panel, { screen: "timer" }), { target: "timer" });
  assert.deepEqual(crownTarget(panel, { screen: "review" }), { target: "image" });
  assert.deepEqual(crownTarget(panel, { screen: "review", reviewZoomed: true }), { target: "zoom" });
  // theme does not change the target
  assert.deepEqual(crownTarget(reduce(panel, { type: "theme", theme: "astro" })), { target: "value" });
});
