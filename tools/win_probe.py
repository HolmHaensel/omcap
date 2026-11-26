"""Windows bring-up probe for E-M1 Capture: what does this PC see, and what does the camera offer?

Read only: the camera is only asked the CGIs that omcap.camera allows without --allow-write, so nothing
on the body changes. Writes nothing but the report on stdout.

  .venv\\Scripts\\python tools\\win_probe.py                     # this PC: route to the camera, USB devices
  .venv\\Scripts\\python tools\\win_probe.py --host 192.168.0.10  # camera Wi-Fi: model, commands, properties
  .venv\\Scripts\\python tools\\win_probe.py --json              # one JSON object, for a report

Why: the app was written on macOS for the E-M1 Mark I. This prints what a Windows PC and another body can
differ in - camera address, command list (which features the app may use), property names and enums, and
which USB driver Windows bound to the camera - before the app connects.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error

try:
    from omcap.camera import Camera, CameraError
except ImportError:
    sys.exit("Run this from the omcap folder with its environment: .venv\\Scripts\\python tools\\win_probe.py")

DEFAULT_HOST = "192.168.0.10"  # same default as the app (--host)
LIVE_VIEW_CGIS = ("startliveview", "getliveviewimage", "switch_cammode", "exec_takemisc")
PS_USB = (
    "$ds = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | "
    "Where-Object { $_.InstanceId -like 'USB\\VID_07B4*' }; "
    "@($ds | ForEach-Object { [pscustomobject]@{ name = $_.FriendlyName; status = $_.Status; "
    "class = $_.Class; instance = $_.InstanceId; "
    "service = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName 'DEVPKEY_Device_Service' "
    "-ErrorAction SilentlyContinue).Data } }) | ConvertTo-Json -Compress"
)


def route_to(host):
    """Local IPv4 address the system would use to reach host, or None (no route / camera Wi-Fi not joined)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(0.5)
        s.connect((host, 80))  # UDP connect sends nothing, it only asks the routing table
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def tcp_check(host, port=80, timeout=3.0):
    """(milliseconds, error text) for a TCP connection to host:port; milliseconds None on failure."""
    t0 = time.monotonic()
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return round((time.monotonic() - t0) * 1000, 1), None
    except OSError as e:
        return None, str(e)


def usb_devices():
    """Olympus USB devices Windows sees now, with the driver service bound to each (empty list: none)."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_USB],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return {"error": str(e)}
    out = (r.stdout or "").strip()
    if not out:
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return {"error": (r.stderr or out).strip()[:500]}
    return data if isinstance(data, list) else [data]


def probe_camera(host):
    """Read-only view of the camera: model, connect mode, commands, properties. Per item errors are kept."""
    cam = Camera(host=host, timeout=5, allow_write=False)
    info = {"host": host}

    def call(name, fn):
        try:
            return fn()
        except (CameraError, OSError, urllib.error.URLError, ValueError) as e:
            info[name + "_error"] = str(e)
            return None

    model = call("model", cam.caminfo)
    if model:
        info["model"] = model
    raw_mode = call("connect_mode", lambda: cam.get("get_connectmode").decode("ascii", "replace"))
    if raw_mode is not None:
        info["connect_mode"] = raw_mode.strip()
    commands = call("commands", lambda: sorted(cam.commandlist()))
    if commands:
        info["commands"] = commands
        info["live_view_cgis"] = [c for c in LIVE_VIEW_CGIS if c in commands]
    props = call("props", cam.props)
    if props is not None:
        info["props"] = props
    return info


def print_pc(pc):
    print("== this PC ==")
    host = pc["host"]
    if pc["route"]:
        print("route to %s: %s" % (host, pc["route"]))
    else:
        print("route to %s: none - the camera's Wi-Fi is not joined (or another address)" % host)
    if pc["camera_tcp_ms"] is not None:
        print("camera answers on %s:80 in %s ms" % (host, pc["camera_tcp_ms"]))
    else:
        print("camera does not answer on %s:80 (%s)" % (host, pc["camera_tcp_error"]))
    usb = pc["usb"]
    print("\n== Olympus USB devices (vendor 07b4) ==")
    if isinstance(usb, dict) and usb.get("error"):
        print("could not ask Windows: " + usb["error"])
    elif not usb:
        print("none present (camera on Wi-Fi, or the cable is not plugged in)")
    else:
        for d in usb:
            print("- %s  [%s, class %s]" % (d.get("name"), d.get("status"), d.get("class")))
            print("  service: %s" % (d.get("service") or "?"))
            print("  instance: %s" % d.get("instance"))
        services = {(d.get("service") or "").lower() for d in usb}
        if services & {"winusb", "libusb0", "libusbk"}:
            print("  -> libusb can reach the camera with this driver")
        else:
            print("  -> Windows' own camera driver owns it; libusb needs a WinUSB rebind (Zadig, admin)")


def print_camera(cam):
    print("\n== camera over Wi-Fi ==")
    if cam.get("model"):
        print("model: %s" % cam["model"])
    for key, label in (("model_error", "model"), ("connect_mode_error", "connect mode")):
        if cam.get(key):
            print("%s: not readable - %s" % (label, cam[key]))
    if cam.get("connect_mode"):
        print("connect mode: %s" % cam["connect_mode"])
    if cam.get("commands_error"):
        print("command list: not readable - %s" % cam["commands_error"])
    elif cam.get("commands"):
        print("commands: %d" % len(cam["commands"]))
        found = cam.get("live_view_cgis") or []
        print("live view commands: %s" % (", ".join(found) or "none of " + ", ".join(LIVE_VIEW_CGIS)))
        if "startliveview" in found:
            print("  -> RTP/UDP 5555, what the app expects")
        elif "getliveviewimage" in found:
            print("  -> HTTP frames, the app's Wi-Fi live view would need a change for this body")
    if cam.get("props_error"):
        print("properties: not readable - %s" % cam["props_error"])
    elif cam.get("props"):
        print("properties: %d" % len(cam["props"]))
        for name in sorted(cam["props"]):
            p = cam["props"][name]
            enum = p.get("enum") or []
            extra = ""
            if p.get("writable"):
                extra += " (writable)"
            if enum:
                extra += " [%s]" % " ".join(enum[:12]) + (" ..." if len(enum) > 12 else "")
            print("  %-24s = %-24s%s" % (name, (p.get("value") or "").strip(), extra))


def next_steps(pc, cam):
    print("\n== next ==")
    if not cam or "model" not in cam:
        print("1. Camera: Setup -> Wi-Fi Settings -> Wi-Fi Connect Settings -> Private")
        print("2. Camera: Playback -> Connection to Smartphone (shows SSID and password; card must be in)")
        print("3. This PC: join that network, then run this probe again")
        print("4. If the camera answers but live view later stays black: Windows Firewall must allow")
        print("   inbound UDP 5555 (Python) on the camera network, and that network must be 'Private'")
    else:
        print("Camera read: %s. Start the app with:" % cam.get("model"))
        print('  .venv\\Scripts\\python -m omcap.server --allow-write --host %s' % pc["host"])
        print("Then click Connect, choose Wi-Fi, and check live view and tap to focus.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="win_probe", description="Read-only Windows bring-up probe for E-M1 Capture.")
    p.add_argument("--host", default=DEFAULT_HOST, help="camera IP in its Wi-Fi (default %s)" % DEFAULT_HOST)
    p.add_argument("--json", action="store_true", help="print one JSON object instead of the report")
    a = p.parse_args(argv)
    host = a.host

    ms, err = tcp_check(host)
    pc = {"host": host, "route": route_to(host), "camera_tcp_ms": ms, "camera_tcp_error": err,
          "usb": usb_devices(), "platform": sys.platform}
    cam = probe_camera(host) if ms is not None else None

    if a.json:
        print(json.dumps({"pc": pc, "camera": cam}, indent=1, sort_keys=True))
        return 0
    print_pc(pc)
    if cam:
        print_camera(cam)
    next_steps(pc, cam)
    return 0


if __name__ == "__main__":
    sys.exit(main())
