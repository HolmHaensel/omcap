// View state model (no DOM). Run: node --test tests/ds
import test from "node:test";
import assert from "node:assert/strict";
import { initialState, reduce, defaultView, layoutFor, previewGeometry, clampSplit, overlaysFor,
  SPLIT_MIN, SPLIT_MAX } from "../../omcap/web/ds/views.js";

test("default view per device (Figma: desktop panel, phone landscape full, portrait panel, watch full)", () => {
  assert.equal(defaultView("desktop", "landscape"), "panel");
  assert.equal(defaultView("mobile", "landscape"), "full");
  assert.equal(defaultView("mobile", "portrait"), "panel");
  assert.equal(defaultView("watch", "portrait"), "full");
  assert.equal(initialState().scaling, "fit");
  assert.equal(initialState().theme, "dark");
});

test("Clean View keeps an explicit way back", () => {
  let s = initialState("desktop");
  s = reduce(s, { type: "clean" });
  assert.equal(s.view, "clean");
  assert.equal(overlaysFor(s.view), "none");
  s = reduce(s, { type: "clean" });
  assert.equal(s.view, "panel");
  s = reduce(reduce(s, { type: "view", view: "full" }), { type: "view", view: "clean" });
  assert.equal(reduce(s, { type: "clean" }).view, "full");
});

test("axes are independent: turning the display or changing theme keeps view and scaling", () => {
  let s = reduce(initialState("mobile", "landscape"), { type: "scaling", scaling: "fill" });
  s = reduce(s, { type: "display", display: "portrait" });
  s = reduce(s, { type: "theme", theme: "astro" });
  s = reduce(s, { type: "cameraOrientation", deg: 90 });
  assert.equal(s.view, "full");
  assert.equal(s.scaling, "fill");
  assert.equal(s.cameraOrientation, 90);
  assert.equal(s.display, "portrait");
});

test("view actions carry no camera state and never return one", () => {
  const s = initialState();
  const keys = Object.keys(s).sort();
  for (const a of [{ type: "view", view: "full" }, { type: "clean" }, { type: "scaling", scaling: "fill" },
    { type: "split", split: 0.5 }, { type: "theme", theme: "daylight" }, { type: "display", display: "portrait" }]) {
    assert.deepEqual(Object.keys(reduce(s, a)).sort(), keys);
  }
  assert.throws(() => reduce(s, { type: "capture" }));
  assert.throws(() => reduce(s, { type: "view", view: "shutter" }));
});

test("split clamps to the proposal limits", () => {
  assert.equal(clampSplit(0.1), SPLIT_MIN);
  assert.equal(clampSplit(0.99), SPLIT_MAX);
  assert.equal(clampSplit("x"), 0.65);
  assert.deepEqual(layoutFor(initialState("desktop")), { kind: "split-horizontal", live: 0.65 });
  assert.deepEqual(layoutFor(initialState("watch")), { kind: "viewport" });
  assert.deepEqual(layoutFor(reduce(initialState("watch"), { type: "view", view: "panel" })), { kind: "instrument-screen" });
  assert.deepEqual(layoutFor(initialState("mobile", "portrait")), { kind: "split-vertical" });
});

test("Fit shows the whole frame, Fill crops the preview only", () => {
  const fit = previewGeometry(4, 3, 1600, 900, "fit");
  assert.equal(fit.h, 900);
  assert.equal(fit.w, 1200);
  assert.equal(fit.cropped, 0);
  const fill = previewGeometry(4, 3, 1600, 900, "fill");
  assert.equal(fill.w, 1600);
  assert.ok(fill.cropped > 0.24 && fill.cropped < 0.26);
  const turned = previewGeometry(4, 3, 900, 1600, "fit", 90);
  assert.equal(turned.w, 900);
  assert.equal(turned.h, 1200);
});
