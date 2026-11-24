"""Read-only reconnaissance of an Olympus body over the OI.Share Wi-Fi protocol.

Dumps what the camera says about itself so a body other than the E-M1 Mark I
(e.g. the E-M1 Mark II) can be compared against the app's assumptions.
Nothing here changes the camera: only GET endpoints are used, plus one
get_connectmode switch to 'play' is avoided entirely.

Run:  .venv\\Scripts\\python.exe tools\\mk2_probe.py [host]
"""
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.10"
HDR = {"User-Agent": "OlympusCameraKit", "Host": HOST}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "probe_out")
os.makedirs(OUT, exist_ok=True)


def fetch(cgi, **query):
    url = "http://%s/%s" % (HOST, cgi)
    if query:
        url += "?" + "&".join("%s=%s" % kv for kv in query.items())
    req = urllib.request.Request(url, headers=HDR)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, r.read(), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read(), time.time() - t0
    except (urllib.error.URLError, OSError) as e:
        return None, repr(e).encode(), time.time() - t0


def save(name, raw):
    with open(os.path.join(OUT, name), "wb") as f:
        f.write(raw)


def main():
    print("host:", HOST)
    # 1. TCP reachable?
    try:
        s = socket.create_connection((HOST, 80), timeout=4)
        s.close()
        print("tcp:80 ok")
    except OSError as e:
        print("tcp:80 FAILED:", e)
        return 1

    # 2. Who are you?
    code, raw, dt = fetch("get_caminfo")
    print("get_caminfo -> %s (%.2fs)" % (code, dt))
    save("caminfo.xml", raw)
    print(raw[:600].decode("utf-8", "replace"))

    # 3. Command list (what this body really supports)
    code, raw, dt = fetch("get_commandlist")
    print("\nget_commandlist -> %s (%.2fs, %d bytes)" % (code, dt, len(raw)))
    save("commandlist.xml", raw)
    cam_cmds = set()
    try:
        root = ET.fromstring(raw.split(b"?>", 1)[-1])
        cam_cmds = {c.get("name") for c in root.iter("cgi") if c.get("name")}
        print("  cgi count:", len(cam_cmds))
    except ET.ParseError as e:
        print("  parse error:", e)

    # 4. Diff against the bundled E-M1 Mark I list
    bundled = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                           "omcap", "data", "commandlist.xml")
    if cam_cmds and os.path.exists(bundled):
        try:
            braw = open(bundled, "rb").read()
            broot = ET.fromstring(braw.split(b"?>", 1)[-1])
            mk1 = {c.get("name") for c in broot.iter("cgi") if c.get("name")}
            print("\n  missing vs bundled E-M1 list:", sorted(mk1 - cam_cmds) or "none")
            print("  extra on this body:", sorted(cam_cmds - mk1) or "none")
        except ET.ParseError as e:
            print("  bundled parse error:", e)

    # 5. Current property state
    code, raw, dt = fetch("get_camprop", com="desc", propname="")
    print("\nget_camprop desc -> %s (%.2fs, %d bytes)" % (code, dt, len(raw)))
    save("camprop_desc.xml", raw)

    code, raw, dt = fetch("get_camprop", com="get", propname="")
    print("get_camprop get  -> %s (%.2fs, %d bytes)" % (code, dt, len(raw)))
    save("camprop_get.xml", raw)

    # 6. Card + battery
    for cgi in ("get_unusedcapacity", "get_dcffilenum", "get_connectmode", "get_activate"):
        code, raw, dt = fetch(cgi)
        print("%-22s -> %s (%.2fs) %s" % (cgi, code, dt, raw[:160].decode("utf-8", "replace").replace("\n", " ")))

    # 7. Image list on the card (playback side)
    code, raw, dt = fetch("get_imglist", dir="/DCIM", file="")
    print("get_imglist           -> %s (%.2fs, %d bytes)" % (code, dt, len(raw)))
    save("imglist.xml", raw)

    print("\nwrote dumps to", os.path.abspath(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
