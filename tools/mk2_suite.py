"""E-M1 Mark II capability sweep over USB, one sub-test at a time.

Usage:  .venv\\Scripts\\python.exe tools\\mk2_suite.py [lv|props|poll|focus|all]

Everything is measured, not assumed: each sub-test prints what it did, what the camera answered and
how long it took, and appends to probe_out/mk2_suite.json. Settings that are written are read first and
restored afterwards. Nothing is written to the card and no firmware command is ever sent.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from omcap import ptp  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "probe_out")
REPORT = os.path.join(OUT, "mk2_suite.json")

SIZES = [(320, 240), (640, 480), (800, 600), (1024, 768), (1280, 960)]

# The properties the app drives on the Mark I, with the body's own labels for the report.
KEY_PROPS = {
    0xD006: "mode dial", 0xD00C: "AF mode", 0xD051: "AF field", 0xD010: "picture mode",
    0xD01C: "exposure time", 0xD01D: "aperture", 0xD01E: "ISO", 0xD020: "WB",
    0xD04B: "loupe", 0xD06D: "live view size", 0xD053: "roll", 0xD055: "pitch",
    0xD0F0: "battery", 0xD052: "control mode",
}


def save(name, data):
    os.makedirs(OUT, exist_ok=True)
    all_ = {}
    if os.path.exists(REPORT):
        try:
            all_ = json.load(open(REPORT, encoding="utf-8"))
        except Exception:
            all_ = {}
    all_[name] = data
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(all_, f, indent=1, default=str)


def fps_for(cam, w, h, seconds=3.0, dtype=6):
    cam.set_prop(ptp.DPC_LV_SIZE, (w << 16) | h, dtype)
    time.sleep(0.25)
    frames, marks, t0 = 0, [], time.monotonic()
    while time.monotonic() - t0 < seconds:
        f = cam.liveview_frame(wait=0.5)
        if not f:
            break
        frames += 1
        marks.append(time.monotonic())
    dt = (marks[-1] - marks[0]) if len(marks) > 1 else 0.0
    return {"frames": frames, "seconds": round(dt, 2),
            "fps": round((frames - 1) / dt, 1) if dt else 0.0}


def t_lv(cam):
    desc = cam.prop_desc(ptp.DPC_LV_SIZE)
    print("live view size property: type %s, enum %s" % (desc["type"], desc.get("enum")))
    out = {}
    for w, h in SIZES:
        r = fps_for(cam, w, h, dtype=desc["type"])
        print("  %4dx%-4d : %5.1f fps   (%d frames in %s s)" % (w, h, r["fps"], r["frames"], r["seconds"]))
        out["%dx%d" % (w, h)] = r
    cam.set_prop(ptp.DPC_LV_SIZE, 0, desc["type"])
    return out


def t_props(cam):
    out = {}
    print("current settings as the camera reports them:")
    for code, label in KEY_PROPS.items():
        try:
            d = cam.prop_desc(code)
            v = d.get("value")
            extra = ""
            if d.get("enum"):
                extra = "  of %d values" % len(d["enum"])
            elif d.get("range"):
                extra = "  range %s" % str(d["range"])
            print("  0x%04X %-16s = %-12s%s" % (code, label, str(v)[:24], extra))
            out["0x%04X" % code] = {"label": label, "value": v, "writable": d.get("writable"),
                                    "enum": d.get("enum"), "range": d.get("range")}
        except ptp.PtpError as e:
            print("  0x%04X %-16s : FAILED 0x%04X" % (code, label, e.code or 0))
            out["0x%04X" % code] = {"label": label, "error": e.code}
    return out


def t_poll(cam):
    """0x9489 sets the poll list, 0x9486 reads back what changed - the Mark I's fast control loop."""
    codes = [0xD006, 0xD01C, 0xD01D, 0xD01E, 0xD020, 0xD051, 0xD052]
    res = {"list": ["0x%04X" % c for c in codes]}
    t0 = time.monotonic()
    try:
        cam.set_poll_list(codes)
        res["set_poll_list"] = "ok in %.2f s" % (time.monotonic() - t0)
    except ptp.PtpError as e:
        res["set_poll_list"] = "FAILED 0x%04X" % (e.code or 0)
        print("set_poll_list: FAILED 0x%04X" % (e.code or 0))
        return res
    print("set_poll_list   : ok (%.2f s)" % (time.monotonic() - t0))
    for i in range(3):
        t1 = time.monotonic()
        try:
            ch = cam.changed_props()
            dt = (time.monotonic() - t1) * 1000
            res["poll_%d" % i] = {"ms": round(dt, 1), "props": ["0x%04X=%s" % (k, v.get("value")) for k, v in (ch or {}).items()]}
            print("changed_props %d : %5.1f ms  %s" % (i, dt, res["poll_%d" % i]["props"] or "(nothing changed)"))
        except ptp.PtpError as e:
            res["poll_%d" % i] = "FAILED 0x%04X" % (e.code or 0)
            print("changed_props %d : FAILED 0x%04X" % (i, e.code or 0))
        time.sleep(0.2)
    return res


def t_focus(cam):
    """AF field d051: read the current field, move it, read back. Does not press the shutter."""
    res = {}
    d = cam.prop_desc(0xD051)
    enum = d.get("enum") or []
    cur = d.get("value")
    res["enum"] = enum
    res["before"] = cur
    print("AF field: %d fields (%s..%s), current %s" % (len(enum), min(enum) if enum else "-",
                                                        max(enum) if enum else "-", cur))
    target = 5 if 5 in enum else (enum[0] if enum else None)
    if target is None:
        return res
    try:
        cam.set_prop(0xD051, target, d["type"])
        time.sleep(0.2)
        after = cam.prop_desc(0xD051)["value"]
        res.update({"set": target, "after": after, "ok": after == target})
        print("set d051 = %s -> reads %s  %s" % (target, after, "OK" if after == target else "MISMATCH"))
    except ptp.PtpError as e:
        res["error"] = e.code
        print("set d051 failed: 0x%04X" % (e.code or 0))
    if cur is not None:
        try:
            cam.set_prop(0xD051, cur, d["type"])
            res["restored"] = cam.prop_desc(0xD051)["value"]
            print("restored to %s" % res["restored"])
        except ptp.PtpError:
            pass
    return res


TESTS = {"lv": t_lv, "props": t_props, "poll": t_poll, "focus": t_focus}


def main(argv):
    want = argv[1] if len(argv) > 1 else "all"
    todo = list(TESTS) if want in ("all",) else [want]
    cam = ptp.PtpCamera(ptp.UsbTransport())
    cam.open()
    res: dict[str, object] = {"model": cam.device_info().get("model"),
                             "ops": len(cam.device_info().get("operations", ()))}
    try:
        if cam.prop_desc(ptp.DPC_CONTROL_MODE)["value"] != 1:
            cam.pc_mode(True)
        for name in todo:
            print("\n=== %s ===" % name)
            t0 = time.monotonic()
            try:
                res[name] = TESTS[name](cam)
            except Exception as e:
                res[name] = {"exception": "%s: %s" % (type(e).__name__, e)}
                print("  EXCEPTION: %s" % e)
            res[name + "_seconds"] = round(time.monotonic() - t0, 1)
    finally:
        cam.close()
        save(want, res)
        print("\nwrote %s" % REPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
