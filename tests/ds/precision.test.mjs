// Pure logic of the precision instruments (no DOM). Run: node --test tests/ds
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ValueState, normStops, indexOfValue, clampIndex, centerLockOffset, dragToX, fitLayout, scaleLayout, nearestStop,
  stopsFor, isMainValue, shutterSeconds, stopIsMajor, ringLabels, formatValue, valueText,
  angleToSegment, segmentAngle, radiusToValue, valueToRadius } from "../../omcap/web/ds/precision.js";

const FX = JSON.parse(readFileSync(new URL("../../omcap/web/ds/fixtures/em1-capabilities-sample.json", import.meta.url)));

const AP = ["2.8", "3.2", "3.5", "4.0", "4.5", "5.0", "5.6"];

test("stops: refuse empty and duplicate lists", () => {
  assert.throws(() => normStops([]));
  assert.throws(() => normStops(["1", "1"]));
  assert.deepEqual(normStops([{ value: 4, label: "ƒ4" }])[0], { value: "4", label: "ƒ4", major: null, special: false });
});

test("snapping lands only on real stops", () => {
  const s = normStops(AP);
  const xs = scaleLayout(s, 41);
  assert.equal(nearestStop(xs, 2.4 * 41), 2);
  assert.equal(nearestStop(xs, 2.6 * 41), 3);
  assert.equal(nearestStop(xs, -300), 0);
  assert.equal(nearestStop(xs, 9999), 6);
  assert.equal(clampIndex(s, 99), 6);
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
  assert.equal(centerLockOffset(123, 544), 272 - 123);
  assert.equal(dragToX(123, -82, "center"), 205); // drag left brings higher stops to the centre
  assert.equal(dragToX(123, 82, "fixed"), 205);   // marker follows the finger
  const fit = fitLayout([0, 41, 82], 544, 24);
  assert.deepEqual([fit[0], fit[2]], [24, 520]);
});

// ---- Adaptive Precision Scale V2.0: every tick has a purpose ----

const wifi = FX.props;

test("tick <-> camera value bijection: one stop per camera value, same order, nothing added", () => {
  for (const [kind, prop] of [["aperture", "focalvalue"], ["shutter", "shutspeedvalue"], ["iso", "isospeedvalue"], ["ev", "expcomp"]]) {
    const st = stopsFor(kind, wifi[prop].values);
    assert.deepEqual(st.map((s) => s.value), wifi[prop].values, kind);
    assert.equal(new Set(st.map((s) => s.value)).size, st.length, kind);
    const xs = scaleLayout(st, 41);
    assert.equal(xs.length, st.length, kind);
    st.forEach((_, i) => assert.equal(nearestStop(xs, xs[i]), i, `${kind} ${i}`)); // each tick snaps to itself
  }
});

test("main values per parameter (full stops, ISO doublings, whole EV, 1000 K)", () => {
  const major = (kind, list) => stopsFor(kind, list).filter((s) => s.major).map((s) => s.value);
  assert.deepEqual(major("aperture", wifi.focalvalue.values), ["1.0", "1.4", "2.0", "2.8", "4.0", "5.6", "8.0", "11", "16", "22", "32", "45", "64", "91"]);
  assert.deepEqual(major("iso", wifi.isospeedvalue.values), ["200", "400", "800", "1600", "3200", "6400", "12800", "25600"]);
  assert.deepEqual(major("ev", wifi.expcomp.values), ["-5.0", "-4.0", "-3.0", "-2.0", "-1.0", "0.0", "+1.0", "+2.0", "+3.0", "+4.0", "+5.0"]);
  const sh = major("shutter", wifi.shutspeedvalue.values);
  assert.ok(["60\"", "30\"", "15\"", "8\"", "4\"", "2\"", "1\"", "2", "4", "8", "15", "30", "60", "125", "250", "500", "1000", "2000", "4000", "8000"].every((v) => sh.includes(v)), sh.join(" "));
  assert.equal(sh.length, 20);
  const k = stopsFor("kelvin", FX.wb.custom_kelvin.values.map(String)).filter((s) => s.major).map((s) => s.value);
  assert.deepEqual(k, ["2000", "3000", "4000", "5000", "6000", "7000", "9000", "10000", "11000", "12000", "13000", "14000"]);
  assert.ok(!FX.wb.custom_kelvin.values.includes(8000)); // the body has 7800 and 8200: no 8000 tick is invented
});

test("step size: 1/3, 1/2 and 1 EV lists mark the same full stops", () => {
  const third = ["1.4", "1.6", "1.8", "2.0", "2.2", "2.5", "2.8"];            // camera list (1/3 EV)
  const half = ["1.4", "1.7", "2.0", "2.4", "2.8"];                         // synthetic 1/2 EV list (test only)
  const full = ["1.4", "2.0", "2.8"];                                       // 1 EV subset of the camera list
  for (const l of [third, half, full]) {
    assert.deepEqual(stopsFor("aperture", l).filter((s) => s.major).map((s) => s.value), ["1.4", "2.0", "2.8"]);
    assert.equal(stopsFor("aperture", l).length, l.length);
  }
  // ISO steps are separate from exposure steps: 1/3-step ISO 250/320 are minor, 1 EV ISO all major
  assert.equal(isMainValue("iso", "250"), false);
  assert.ok(["200", "400", "800"].every((v) => isMainValue("iso", v)));
  assert.equal(isMainValue("ev", "+0.3"), false);
});

test("AUTO, LOW, BULB and LIVE modes are semantic values, set apart, never major or numeric", () => {
  const iso = stopsFor("iso", wifi.isospeedvalue.values);
  assert.deepEqual(iso.filter((s) => s.special).map((s) => s.label), ["AUTO", "LOW"]);
  const sh = stopsFor("shutter", wifi.shutspeedvalue.values);
  assert.deepEqual(sh.filter((s) => s.special).map((s) => s.label), ["LIVE COMP", "LIVE TIME", "BULB"]);
  assert.ok(sh.filter((s) => s.special).every((s) => !s.major));
  const xs = scaleLayout(iso, 40);
  assert.equal(xs[1] - xs[0], 40);        // AUTO -> LOW: both special, normal step
  assert.equal(xs[2] - xs[1], 70);        // LOW -> 200: gap between semantic and numeric values
  assert.equal(xs[3] - xs[2], 40);
  assert.equal(shutterSeconds("livebulb"), null);
  assert.equal(shutterSeconds('2"'), 2);
  assert.equal(shutterSeconds("250"), 1 / 250);
});

test("limits: no artificial values beyond the camera's range", () => {
  const ev = stopsFor("ev", wifi.expcomp.values);
  assert.equal(ev[0].value, "-5.0");
  assert.equal(ev[ev.length - 1].value, "+5.0");
  const st = new ValueState(ev, "+5.0");
  assert.equal(st.request("+5.3"), false);
  assert.equal(clampIndex(st.stops, 99), ev.length - 1);
});

test("short lists without major flags: every stop is labelled", () => {
  const s = normStops(["A", "B", "C"]);
  assert.ok([0, 1, 2].every((i) => stopIsMajor(s, i)));
});

test("USB and Wi-Fi give the same exposure values (shared value source)", () => {
  const u = FX.usb;
  const iso = u.d007_iso.map((v) => (v === 65535 ? "Auto" : v === 65533 ? "Low" : String(v)));
  assert.deepEqual(iso, wifi.isospeedvalue.values);
  const ev = u.d008_expcomp.map((v) => { const n = (v > 32767 ? v - 65536 : v) / 1000; return n === 0 ? "0.0" : (n > 0 ? "+" : "") + n.toFixed(1); });
  assert.deepEqual(ev, wifi.expcomp.values);
  const ap = u.d002_aperture_x10.map((v) => (v < 100 ? (v / 10).toFixed(1) : String(Math.round(v / 10))));
  assert.deepEqual(ap, wifi.focalvalue.values);
});

test("Astro Red ring identifiers: indices, hue numbers, filter initials", () => {
  const twelve = Array.from({ length: 12 }, (_, i) => ({ name: String(i) }));
  assert.deepEqual(ringLabels("profile", twelve, 0).slice(0, 3), ["01", "02", "03"]);
  const thirty = Array.from({ length: 30 }, (_, i) => ({ name: String(i) }));
  const cr = ringLabels("creator", thirty, 5);
  assert.deepEqual(cr.filter(Boolean), ["01", "06", "11", "16", "21", "26"]);
  assert.equal(ringLabels("creator", thirty, 7)[7], "08");      // the active hue is always numbered
  const mono = FX.color.mono.filters.map((n, i) => ({ name: n, short: FX.color.mono.filters_short[i] }));
  assert.deepEqual(ringLabels("mono", mono, 0), ["N", "Y", "O", "R", "G"]);
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

// ---- Typography Refinement V1.1: value formatting ----


test("value typography: aperture sign as prefix, one EV sign rule with a real minus, Kelvin unit, camera words", () => {
  const t = (kind, value, special = false) => valueText(formatValue(kind, { value, label: special ? value.toUpperCase() : value, special }));
  assert.deepEqual(formatValue("aperture", { value: "2.8", label: "2.8" }), { prefix: "ƒ", text: "2.8", unit: "" });
  assert.equal(t("aperture", "22"), "ƒ22");
  assert.equal(t("shutter", "8000"), "1/8000");
  assert.equal(t("shutter", '60"'), '60"');
  assert.equal(t("ev", "-0.3"), "−0.3");   // real minus sign
  assert.equal(t("ev", "0.0"), "±0.0");
  assert.equal(t("ev", "+1.7"), "+1.7");
  assert.equal(t("kelvin", "5600"), "5600 K");
  assert.equal(formatValue("iso", { value: "Auto", label: "AUTO", special: true }).word, true);
  // the camera value is untouched: only the display changes
  const ev = stopsFor("ev", ["-0.3", "0.0"]);
  assert.deepEqual(ev.map((s) => s.value), ["-0.3", "0.0"]);
});
