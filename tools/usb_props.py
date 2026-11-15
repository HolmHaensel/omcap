"""USB value listener for the E-M1 Mark I: which PTP property belongs to which menu item?

Read only: reads the camera summary (like `gphoto2 --summary`), never set_config,
never shooting, never live view. The camera only updates its values when a
USB session is established, so `watch` rebuilds the session before every measurement.

  python tools/usb_props.py snapshot NAME        # save values
  python tools/usb_props.py diff A B             # compare two snapshots
  python tools/usb_props.py watch [--kill-ptpcamerad] [--replug]
      # --replug: the camera closes its menu under PC control, so each round is: name the change,
      #   unplug the cable, change the setting in peace, plug in and choose PC + camera – the tool
      #   notices the cable and reads by itself
      # --omcapture: change ONE value in OM Capture and quit OM Capture – the tool waits for OM Capture to
      #   close, then reads by itself (we never write; OM Capture does). Never run both on the camera at once.
      # baseline, then per round: change ONE setting on the camera, enter a name,
      # Enter -> reconnect, compare, append the result to mapping.md

Storage: out/research/usb_props/ (without serial number). The app must not be connected via USB meanwhile.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time

OUT = os.path.join(os.getcwd(), "out", "research", "usb_props")
LINE = re.compile(r"^(?P<label>.*?)\s*\((?P<code>[0-9a-fA-F]{4}) (?P<access>ro|rw) (?P<type>[^)]*?)\s*\):\s*(?P<rest>.*)$")
SECRET = re.compile(r"(?i)serien|serial")


def parse_summary(text):
    """Properties from the summary: {code: {label, access, type, form, value}}."""
    props = {}
    for line in text.splitlines():
        if SECRET.search(line):
            continue
        m = LINE.match(line.strip())
        if not m:
            continue
        rest = m["rest"]
        form, value = "", rest
        if rest.startswith(("Enumeration", "Range")):
            form, _, value = rest.partition(" value: ")
        elif rest.startswith("a["):
            form, value = rest.split(" ", 1)[0], "(array)"  # do not compare long byte fields
        props[m["code"].lower()] = {"label": m["label"].strip(), "access": m["access"],
                                    "type": m["type"].strip(), "form": form.strip(), "value": value.strip()}
    return props


def read_summary(kill=False):
    """Build a USB session, read the summary, close the session."""
    import gphoto2 as gp
    if kill:
        subprocess.run(["killall", "-9", "ptpcamerad"], capture_output=True)
    cam = gp.Camera()
    for attempt in range(4):
        try:
            cam.init()
            break
        except gp.GPhoto2Error:
            if kill:
                subprocess.run(["killall", "-9", "ptpcamerad"], capture_output=True)
            time.sleep(1.0)
            cam = gp.Camera()
    else:
        raise SystemExit("Kamera nicht erreichbar (USB-Menü: 3. Eintrag, App getrennt, Fotos beendet?)")
    try:
        return str(cam.get_summary())
    finally:
        cam.exit()


def save(name, props):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name + ".json")
    with open(p, "w") as f:
        json.dump(props, f, indent=1, sort_keys=True)
    return p


def load(name):
    with open(os.path.join(OUT, name + ".json")) as f:
        return json.load(f)


def diff(a, b):
    """Changed values and value ranges: [(code, label, old, new, access, form)]."""
    out = []
    for code in sorted(set(a) | set(b)):
        x, y = a.get(code), b.get(code)
        if not x or not y:
            out.append((code, (x or y)["label"], x and x["value"], y and y["value"], (x or y)["access"], "added/removed"))
        elif x["value"] != y["value"] or x["form"] != y["form"]:
            note = "range changed" if x["form"] != y["form"] else ""
            out.append((code, y["label"], x["value"], y["value"], y["access"], (y["form"][:80] + " " + note).strip()))
    return out


def print_diff(rows):
    if not rows:
        print("  keine Änderung erkannt (Einstellung wirkt evtl. erst beim nächsten Sitzungsaufbau oder ist nicht per USB sichtbar)")
    for code, label, old, new, access, form in rows:
        print("  %s %-3s %-22s %s -> %s   %s" % (code, access, label[:22], old, new, form))


def camera_present():
    """True while a camera is on USB (autodetect, no session)."""
    import gphoto2 as gp
    try:
        return gp.Camera.autodetect().count() > 0
    except gp.GPhoto2Error:
        return False


def wait_replug(kill):
    """Wait until the cable is pulled, then until the camera is back on USB."""
    print("  1) USB-Kabel abziehen …", flush=True)
    while camera_present():
        time.sleep(0.5)
    print("  2) Jetzt an der Kamera in Ruhe ändern, dann Kabel einstecken und PC + Kamera wählen …", flush=True)
    while not camera_present():
        if kill:
            subprocess.run(["killall", "-9", "ptpcamerad"], capture_output=True)
        time.sleep(0.5)
    time.sleep(2.0)  # let the camera finish its USB mode switch


def omcapture_running():
    """True while the OM Capture app runs (it holds the camera then)."""
    return subprocess.run(["pgrep", "-f", "OM Capture.app/Contents/MacOS/OM Capture"],
                          capture_output=True).returncode == 0


def wait_omcapture():
    """Wait until OM Capture was opened and quit again."""
    if not omcapture_running():
        print("  1) OM Capture öffnen und verbinden …", flush=True)
        while not omcapture_running():
            time.sleep(1.0)
    print("  2) In OM Capture EINEN Wert ändern, dann OM Capture beenden (⌘Q) …", flush=True)
    while omcapture_running():
        time.sleep(1.0)
    time.sleep(3.0)  # OM Capture closes its session; give the camera a moment


def watch(kill, replug=False, omcapture=False):
    base = parse_summary(read_summary(kill))
    print("Grundstand: %d Eigenschaften gelesen." % len(base))
    save("base", base)
    mapping = os.path.join(OUT, "mapping.md")
    if not os.path.exists(mapping):
        with open(mapping, "w") as f:
            f.write("# USB-Eigenschaften je Menüpunkt (E-M1 Mark I, Firmware 4.6)\n\n"
                    "| Menüpunkt geändert | Eigenschaft | rw | alt -> neu | Wertebereich |\n|---|---|---|---|---|\n")
    while True:
        try:
            prompt = ("\nWelche Einstellung änderst du als Nächstes? Name eingeben (leer = Ende): " if replug or omcapture else
                      "\nAn der Kamera EINE Einstellung ändern, dann hier benennen (leer = Ende): ")
            label = input(prompt).strip()
        except EOFError:
            break
        if not label:
            break
        if replug:
            wait_replug(kill)
        if omcapture:
            wait_omcapture()
        now = parse_summary(read_summary(kill))
        rows = diff(base, now)
        print_diff(rows)
        stamp = datetime.datetime.now().strftime("%H:%M")
        with open(mapping, "a") as f:
            if not rows:
                f.write("| %s (%s) | – | | keine Änderung | |\n" % (label, stamp))
            for code, lab, old, new, access, form in rows:
                f.write("| %s (%s) | `%s` %s | %s | %s -> %s | %s |\n" % (label, stamp, code, lab, access, old, new, form))
        save(re.sub(r"\W+", "_", label)[:40] or "step", now)
        base = now
    print("Ergebnis: " + mapping)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot"); s.add_argument("name"); s.add_argument("--kill-ptpcamerad", action="store_true")
    d = sub.add_parser("diff"); d.add_argument("a"); d.add_argument("b")
    w = sub.add_parser("watch"); w.add_argument("--kill-ptpcamerad", action="store_true")
    w.add_argument("--replug", action="store_true", help="unplug, change, plug in for every round")
    w.add_argument("--omcapture", action="store_true", help="change one value in OM Capture and quit it; the tool then reads")
    a = p.parse_args()
    if a.cmd == "snapshot":
        props = parse_summary(read_summary(a.kill_ptpcamerad))
        print("%d Eigenschaften -> %s" % (len(props), save(a.name, props)))
    elif a.cmd == "diff":
        print_diff(diff(load(a.a), load(a.b)))
    else:
        watch(a.kill_ptpcamerad, a.replug, a.omcapture)


if __name__ == "__main__":
    main()
