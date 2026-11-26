"""Read-only PTP probe for an Olympus body (MTP mode + WinUSB bound).

What it does: opens a session, asks the camera who it is (GetDeviceInfo), lists the
property descriptors it advertises and reads their current values. It never writes a
property, never releases the shutter, never reads, writes or deletes a file on the card.

Typical use on a body the app was not written for (E-M1 Mark II on the Mark I codebase):

    .venv\\Scripts\\python.exe tools\\ptp_probe.py

Writes a JSON dump next to the script in probe_out/.
"""
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from omcap import ptp  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "probe_out")
# Properties the app actually uses, so their values can be compared with the Mark I's
APP_PROPS = {
    0xD052: "control mode (PC/camera)",
    0xD006: "shooting mode (mode dial)",
    0xD00C: "AF mode",
    0xD051: "AF field",
    0xD010: "picture mode",
    0xD01C: "exposure time",
    0xD01D: "aperture",
    0xD01E: "ISO",
    0xD020: "white balance",
    0xD04B: "loupe on/off",
    0xD0CF: "loupe ratio",
    0xD06D: "live view size",
    0xD053: "roll (level)",
    0xD055: "pitch (level)",
    0xD0F0: "battery",
}


def main():
    os.makedirs(OUT, exist_ok=True)
    dump = {}
    t = ptp.UsbTransport()
    print("USB transport open, endpoints in/out/int = %s/%s/%s" % (t.ep_in, t.ep_out, t.ep_int))
    cam = ptp.PtpCamera(t)
    cam.open()
    print("session open")

    info = cam.device_info()
    dump["device_info"] = {k: (list(v) if isinstance(v, tuple) else v) for k, v in info.items()}
    print("\nmodel       : %s" % info.get("model"))
    print("manufacturer: %s" % info.get("manufacturer"))
    print("version     : %s" % info.get("version"))
    print("operations  : %d   events: %d   properties: %d"
          % (len(info.get("operations", ())), len(info.get("events", ())), len(info.get("properties", ()))))
    print("ops        :", " ".join("0x%04X" % o for o in info.get("operations", ())))
    print("prop codes :", " ".join("0x%04X" % p for p in info.get("properties", ())))

    storages = cam.storage_ids()
    dump["storages"] = []
    for s in storages:
        try:
            si = cam.storage_info(s)
        except ptp.PtpError as e:
            si = {"error": str(e)}
        n = None
        try:
            n = len(cam.handles(s))  # count only, nothing is fetched
        except ptp.PtpError as e:
            n = "error: %s" % e
        print("\nstorage 0x%08X: %s, %s objects" % (s, si, n))
        dump["storages"].append({"id": s, "info": si, "objects": n})

    print("\n-- property descriptors --")
    dump["properties"] = {}
    for code in sorted(set(list(info.get("properties", ())) + list(APP_PROPS))):
        entry: dict[str, object] = {"label": APP_PROPS.get(code)}
        try:
            d = cam.prop_desc(code)
            entry["desc"] = {k: (v if not isinstance(v, tuple) else list(v)) for k, v in d.items()} \
                if isinstance(d, dict) else str(d)
            dtype = d.get("type") if isinstance(d, dict) else None
            if dtype is not None:
                try:
                    entry["value"] = cam.prop_value(code, dtype)
                except ptp.PtpError as e:
                    entry["value"] = "error 0x%s" % (e.code,)
        except Exception as e:  # PtpError, or a dataset this parser does not know yet
            entry["desc"] = str(e) if not isinstance(e, ptp.PtpError) else "not supported (0x%04X)" % (e.code or 0)
        dump["properties"]["0x%04X" % code] = entry
        if entry.get("label") or entry.get("desc") not in (None, "not supported (0x0000)"):
            print("0x%04X %-28s %s" % (code, entry.get("label") or "", json.dumps(entry.get("desc"))[:150]),
                  "=", entry.get("value"))

    path = os.path.join(OUT, "ptp_probe.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dump, f, indent=1, default=str)
    print("\nwrote", os.path.abspath(path))

    cam.close()
    print("session closed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
