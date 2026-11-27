// Pure logic of the precision instruments (no DOM). Run: node --test tests/ds
import test from "node:test";
import assert from "node:assert/strict";
import { ValueState, normStops, indexOfValue, snapPosition, centerLockOffset, dragToPosition, fixedRangeStep,
  isMajor, angleToSegment, segmentAngle, radiusToValue, valueToRadius } from "../../omcap/web/ds/precision.js";

const AP = ["2.8", "3.2", "3.5", "4.0", "4.5", "5.0", "5.6"];

test("stops: refuse empty and duplicate lists", () => {
  assert.throws(() => normStops([]));
  assert.throws(() => normStops(["1", "1"]));
  assert.deepEqual(normStops([{ value: 4, label: "ƒ4" }])[0], { value: "4", label: "ƒ4" });
});

test("snapping lands only on real stops", () => {
  const s = normStops(AP);
  assert.equal(snapPosition(s, 2.4), 2);
  assert.equal(snapPosition(s, 2.6), 3);
  assert.equal(snapPosition(s, -3), 0);
  assert.equal(snapPosition(s, 99), 6);
  assert.equal(indexOfValue(s, "3.3"), -1); // never snapped to a neighbour
});

test("requested -> pending -> confirmed", () => {
  const v = new ValueState(AP, "5.6");
  assert.equal(v.phase, "confirmed");
  assert.ok(v.request("4.0"));
  assert.equal(v.phase, "requested");
  assert.equal(v.shown, "4.0");
  assert.equal(v.confirmed, "5.6");     // nothing claimed before the camera answers
  assert.equal(v.send(), "4.0");
  assert.equal(v.phase, "pending");
  assert.ok(v.confirm("4.0"));
  assert.equal(v.phase, "confirmed");
  assert.equal(v.confirmed, "4.0");
});

test("camera readback wins over the wish", () => {
  const v = new ValueState(AP, "5.6");
  v.request("2.8"); v.send();
  assert.equal(v.confirm("3.5"), false);   // e.g. lens cannot open that far
  assert.equal(v.phase, "failed");
  assert.equal(v.shown, "3.5");
});

test("unsupported values are refused, failure keeps the camera value", () => {
  const v = new ValueState(AP, "5.6");
  assert.equal(v.request("1.8"), false);
  assert.equal(v.phase, "confirmed");
  v.request("4.0"); v.send(); v.fail("timeout");
  assert.equal(v.phase, "failed");
  assert.equal(v.confirmed, "5.6");
  assert.equal(v.send(), null);           // nothing left to send
});

test("requesting the confirmed value clears the wish", () => {
  const v = new ValueState(AP, "5.6");
  v.request("4.0"); v.request("5.6");
  assert.equal(v.phase, "confirmed");
});

test("new stop list drops wishes that are no longer valid", () => {
  const v = new ValueState(AP, "5.6");
  v.request("2.8");
  v.setStops(["4.0", "5.6"]);
  assert.equal(v.requested, null);
});

test("scale geometry", () => {
  assert.equal(centerLockOffset(3, 41, 544), 272 - 123);
  assert.equal(dragToPosition(3, -82, 41, "center"), 5); // drag left brings higher stops to the centre
  assert.equal(dragToPosition(3, 82, 41, "fixed"), 5);   // marker follows the finger
  assert.equal(fixedRangeStep(13, 544, 24), (544 - 48) / 12);
  assert.ok(isMajor(0, 3) && isMajor(3, 3) && !isMajor(2, 3));
});

test("colour ring geometry", () => {
  assert.equal(segmentAngle(3, 12), 90);
  assert.equal(angleToSegment(89, 12), 3);
  assert.equal(angleToSegment(-15.1, 12), 11);
  assert.equal(angleToSegment(359, 30), 0);
  assert.equal(radiusToValue(1, -5, 5), 5);
  assert.equal(radiusToValue(0.2, -5, 5), -5);
  assert.equal(radiusToValue(valueToRadius(3, -5, 5), -5, 5), 3);
});
