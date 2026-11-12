"""Local web UI for the E-M1 (on 127.0.0.1 only).

  .venv/bin/python -m omcap.server                 # read only
  .venv/bin/python -m omcap.server --allow-write   # shooting/settings possible

The connection (USB or Wi-Fi) is chosen on the start screen.
"""
import argparse
import contextlib
import errno
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, exif, usb_camera
from .camera import Camera, CameraError, WriteBlocked
from .liveview import LiveView

ROOT = os.path.dirname(os.path.abspath(__file__))
# working folder (--data-dir, default: current folder): shots and preview cache live below it
CAPTURES = os.path.join(os.getcwd(), "captures")
PREVIEW_CACHE = os.path.join(os.getcwd(), "out", "cache", "previews")  # previews from the card
SETTINGS_FILE = os.path.join(os.getcwd(), "omcap-settings.json")
SAVE_SCHEMES = ("original", "datetime", "prefix")
save_cfg = {"dir": "", "scheme": "original", "prefix": ""}  # dir "" = default captures/
# Folders that must never receive pictures: firmware material and camera dumps of the project
PROTECTED_DIRS = [os.path.join(os.path.dirname(ROOT), d) for d in ("download", "out", "camera")]
# ... except the HSL results folder inside out/
PROTECTED_EXCEPT = [os.path.join(os.path.dirname(ROOT), "out", "hsl")]
PREVIEW_CACHE_MAX = 500 << 20  # bytes; above that the oldest previews are dropped
IMAGE_MAX_AGE = 7 * 24 * 3600  # image URLs contain the file size, so they change with the file
LV_PORT = 5555
MIN_INTERVAL = 5  # one shot takes about 4 s (focus, release, save)

WIFI_FEATURES = ["liveview", "lvsize", "af_area", "stages", "scp", "time_lapse", "ae_bkt", "movie",
                 "long", "playback", "transfer", "share_order", "poweroff"]

cam = None   # active connection, None before the choice on the start screen
live = None
conn_type = None
options = {"host": "192.168.0.10", "allow_write": False}
allowed_hosts = set()
movtime_cache = {}  # (path, size) -> seconds
lens_cache = {}  # card path -> lens data from EXIF
exif_cache = {}  # card path -> picture info (shooting data) from EXIF
# Last JPGs read completely (USB: shooting data uses partial reads): /api/full and /api/exif share them,
# so opening a picture over USB reads the file from the card only once.
jpg_cache = {}  # card path -> bytes, oldest first
JPG_CACHE_MAX = 40 << 20


def read_jpg(path):
    """Whole JPG from the card, kept for a short while (size-limited)."""
    if path in jpg_cache:
        return jpg_cache[path]
    data = cam.read_file(path)
    jpg_cache[path] = data
    while len(jpg_cache) > 1 and sum(len(v) for v in list(jpg_cache.values())) > JPG_CACHE_MAX:
        jpg_cache.pop(next(iter(jpg_cache)))
    return data

busy = threading.Lock()  # only one shooting sequence at a time
stop_job = threading.Event()
job = {"name": None, "running": False, "done": 0, "total": 0, "error": None}
state = {"transfer": "sd", "latest": None, "transfer_error": None,
         "take": None, "movie": None, "resume_live": False, "seen": None, "wifi_field": 41,
         "wifi_af": None, "pressing": False, "indexing": False, "play": None,
         "last_shot": None}


DEVICE_TTL = 30  # seconds; do not query card space and battery on every tick
device = {"at": 0.0, "card": None, "battery": None}


def device_status(force=False):
    """Free card space (bytes) and battery (%), cached; errors give None."""
    now = time.time()
    if cam is None:
        return {"card": None, "battery": None}
    # do not ask the camera during a shot, movie, long exposure or half press
    busy_now = (busy.locked() or state["pressing"] or cam.stage or state["movie"] or state["take"]
                or state["indexing"])
    if (force or now - device["at"] >= DEVICE_TTL) and not busy_now:
        for key, read in (("card", cam.free_bytes), ("battery", cam.battery)):
            try:
                device[key] = read()
            except (CameraError, ET.ParseError, OSError, ValueError):
                device[key] = None
        device["at"] = now
    return {"card": device["card"], "battery": device["battery"]}


def invalidate_device():
    device["at"] = 0.0


# --- Verbindung --------------------------------------------------------------
def wifi_name():
    """Model name via get_caminfo (read-only) or None if no camera answers."""
    try:
        return Camera(options["host"], timeout=1).caminfo() or "Camera"
    except (CameraError, WriteBlocked, ET.ParseError):
        return None


def connections():
    """Detected connections with camera names for the start screen."""
    if conn_type is not None:
        return {"connected": conn_type, "wifi": conn_type == "wifi", "usb": conn_type == "usb",
                "names": {}}
    names = {"wifi": wifi_name(), "usb": usb_camera.detect_name()}
    return {"connected": None, "wifi": names["wifi"] is not None, "usb": names["usb"] is not None,
            "names": names}


def connect(kind):
    global cam, live, conn_type
    disconnect()
    if kind == "wifi":
        c = Camera(options["host"], allow_write=options["allow_write"])
        c.features = WIFI_FEATURES
        c.caminfo()  # reports at once if the camera does not answer
        cam, live = c, LiveView(LV_PORT)
    elif kind == "usb":
        c = usb_camera.UsbCamera(allow_write=options["allow_write"])
        cam, live = c, c.live
        start_index(c)
    else:
        raise ValueError("Unknown connection")
    conn_type = kind


def disconnect():
    global cam, live, conn_type
    if cam is None:
        return
    try:
        if live.running:
            cam.stop_liveview()
    except (CameraError, WriteBlocked):
        pass
    live.stop()
    if conn_type == "usb":
        cam.close()
    cam, live, conn_type = None, None, None
    lens_cache.clear()
    exif_cache.clear()
    jpg_cache.clear()
    device.update(at=0.0, card=None, battery=None)
    movtime_cache.clear()
    state.update(play=None, indexing=False)
    state.update(transfer="sd", latest=None, transfer_error=None, take=None, movie=None,
                 resume_live=False, seen=None, wifi_field=41, wifi_af=None, last_shot=None)


def af_area():
    """Over Wi-Fi there is no AF mode command: always a single field there."""
    if conn_type == "usb":
        return {**cam.af_area(), "modes": True}
    f = cam.touch_frame()
    return {"mode": 33025, "field": state["wifi_field"], "modes": False, "last_af": state["wifi_af"],
            "area": {"x0": f["x"], "x1": f["x"] + f["w"], "y0": f["y"], "y1": f["y"] + f["h"],
                     "w": f["base_w"], "h": f["base_h"]}}


def set_af_area(mode, field):
    if conn_type == "usb":
        if field is not None and cam.stage:
            cam.press(0)  # a latched "Press halfway" would block the new focus
        cam.set_af_area(mode, field)
        if field is not None:
            cam.focus()
        return
    if mode not in (None, 33025):
        raise CameraError("AF modes can only be changed over USB")
    field = int(field)
    if not 1 <= field <= 81:
        raise CameraError("AF point must be between 1 and 81")
    a = af_area()["area"]
    row, col = divmod(field - 1, 9)
    state["wifi_af"] = None
    res = cam.af_focus((a["x0"] + (col + .5) / 9 * (a["x1"] - a["x0"])) / a["w"],
                       (a["y0"] + (row + .5) / 9 * (a["y1"] - a["y0"])) / a["h"])
    state["wifi_field"] = field
    # Report the frame centre only for affocus=ok; the UI then colours the field green
    if res["ok"] and res["x"] is not None:
        state["wifi_af"] = {"x": res["x"], "y": res["y"]}


# --- Shooting sequences ------------------------------------------------------
def ensure_idle():
    if state["indexing"]:
        raise CameraError("Reading the card index, please wait")
    if cam.stage or state["take"] or state["movie"] or job["running"] or state["play"] is not None:
        raise CameraError("Camera is busy")


def start_index(c):
    """USB: read the card directory in the background (about 1 min), after that every photo is fast."""
    state["indexing"] = True

    def run():
        t0 = time.monotonic()
        try:
            newest = c.warm_index()
            print("USB card index: %.1f s, newest JPG %s" % (time.monotonic() - t0, newest), flush=True)
        except Exception as e:  # reading it in is only a speed-up
            print("USB card index failed:", e, flush=True)
        finally:
            if cam is c:
                state["indexing"] = False
    threading.Thread(target=run, daemon=True).start()


def power_off():
    """Switch the camera off via Wi-Fi and return to the start screen."""
    if conn_type != "wifi":
        raise CameraError("Only available over Wi-Fi")
    ensure_idle()
    # check first so that a real error is not swallowed as "Wi-Fi gone"
    if not cam.allow_write:
        raise WriteBlocked("Writing not enabled (--allow-write)")
    if not cam.supports("exec_pwoff"):
        raise CameraError("exec_pwoff is not in the camera's command list")
    try:
        if live.running:
            cam.stop_liveview()
    except CameraError:
        pass  # live view does not matter, the camera is about to switch off
    live.stop()
    try:
        cam.power_off()
    except CameraError:
        pass  # the camera cuts the Wi-Fi, often without an answer
    disconnect()


def start_live():
    if conn_type == "usb":
        cam.start_liveview(LV_PORT)  # checks the write permission
        live.start()
    else:
        live.start()
        # Right after switch_cammode the camera may answer 520 for a moment; if frames
        # already arrive, the live view runs anyway
        for attempt in range(4):
            try:
                cam.start_liveview(LV_PORT)
                return
            except CameraError as e:
                if e.code != 520 or attempt == 3:
                    raise
                if live.age is not None and live.age < 1:
                    return
                time.sleep(0.5)


@contextlib.contextmanager
def capture():
    """Locks the camera for a sequence and restarts the live view afterwards."""
    if not busy.acquire(blocking=False):
        raise CameraError("Camera is busy")
    was_live = live.running
    try:
        yield
    finally:
        try:
            if was_live:  # a mode switch ends the live view
                start_live()
        finally:
            busy.release()


def jpg_last(items, name=lambda x: x):
    """JPG last, so that it is shown as the newest image."""
    return sorted(items, key=lambda x: name(x).lower().endswith((".jpg", ".jpeg")))


def dcf_number(name):
    """DCF file number (characters 5-8, e.g. PB082156 / _B082156 -> 2156); -1 if not numeric."""
    digits = name[4:8]
    return int(digits) if digits.isdigit() else -1


def wifi_images_newest():
    """Wi-Fi after a shot: re-read only the newest DCIM folder and merge it into the saved list.

    The camera needs ~3 ms per file, so the whole card (2900 files) takes ~8 s and blocks
    the camera; one folder is enough to find new shots. Without a saved list: whole card."""
    cached = card_cache("wifi")
    folders = [e for e in cam.listdir("/DCIM") if e["isdir"] and e["name"][:3].isdigit()]
    if cached is None or not folders:
        imgs = cam.images("/DCIM")
    else:
        newest = "/DCIM/" + max(folders, key=lambda e: e["name"][:3])["name"]
        imgs = [e for e in cached if not e["path"].startswith(newest + "/")] + cam.images(newest)
    imgs.sort(key=lambda e: (e["date"], e["time"]), reverse=True)
    return card_cache("wifi", imgs)


DCF_JPG = re.compile(r"(/DCIM/\d{3}\w{5}/)([P_])([1-9ABC])(\d\d)(\d{4})\.JPG")
MONTHS = "123456789ABC"


def wifi_guess_new(before, rounds=8):
    """Wi-Fi after a shot: (path, thumbnail) of the next picture without reading the folder.

    DCF names count up (PB122211.JPG -> PB122212.JPG). A hit costs 0.4 s, a miss 1.2 s
    (measured, 2500 files in the folder), so the likely name is asked again while the camera
    still writes, and the other color space prefix and today's date only now and then."""
    m = DCF_JPG.fullmatch(before or "")
    if not m:
        return None
    folder, pre, stamp, num = m.group(1), m.group(2), m.group(3) + m.group(4), int(m.group(5))
    if num >= 9999:  # the camera starts a new folder
        return None
    t = time.localtime()
    today = "%s%02d" % (MONTHS[t.tm_mon - 1], t.tm_mday)
    name = "%04d.JPG" % (num + 1)
    likely = folder + pre + stamp + name
    others = [folder + p + d + name for p in (pre, "_" if pre == "P" else "P")
              for d in dict.fromkeys((stamp, today)) if folder + p + d + name != likely]
    for i in range(rounds):
        for path in [likely] + (others if i % 4 == 3 else []):
            try:
                data = cam.thumbnail(path)
            except CameraError:
                continue
            if data[:2] == b"\xff\xd8":
                return path, data
    return None


def newest_jpg(paths):
    """Card path of the JPG among the new files of one shot, or None (RAW only)."""
    jpgs = [p for p in paths if p.lower().endswith((".jpg", ".jpeg"))]
    return jpgs[-1] if jpgs else None


def remember_shot(paths):
    """USB: keep the newest JPG of the last shot for the "last shot" thumbnail."""
    p = newest_jpg(paths)
    if p:
        state["last_shot"] = p


def captures_dir():
    """Folder for pictures on the computer: the chosen one, else the default captures/."""
    return save_cfg["dir"] or CAPTURES


def _inside(p, root):
    """True if p is root or below it. Case-insensitive (APFS), symlinks resolved."""
    rp = os.path.normcase(os.path.realpath(p)).lower()
    rr = os.path.normcase(os.path.realpath(root)).lower()
    if rp == rr or rp.startswith(rr + os.sep):
        return True
    # samefile catches other spellings of an existing folder (e.g. Unicode, hard-to-compare case)
    if os.path.exists(root):
        q = os.path.realpath(p)
        while True:
            if os.path.exists(q) and os.path.samefile(q, root):
                return True
            up = os.path.dirname(q)
            if up == q:
                return False
            q = up
    return False


def _check_prefix(prefix):
    if not prefix or re.search(r'[/\\:\x00]', prefix) or ".." in prefix or prefix in (".", ".."):
        raise ValueError("Prefix contains characters that are not allowed")


def validate_save_dir(d):
    """Return the absolute, created, writable folder or raise ValueError."""
    d = str(d or "").strip()
    if not d:
        return ""
    d = os.path.expanduser(d)
    if not os.path.isabs(d):
        raise ValueError("Folder must be an absolute path (or start with ~)")
    d = os.path.normpath(d)
    for bad in PROTECTED_DIRS:
        if _inside(d, bad) and not any(_inside(d, ok) for ok in PROTECTED_EXCEPT):
            raise ValueError("This folder is not allowed: %s" % bad)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError as e:
        raise ValueError("Cannot create folder: %s" % e)
    if not os.path.isdir(d) or not os.access(d, os.W_OK | os.X_OK):
        raise ValueError("Folder is not writable")
    return d


def set_save_cfg(b):
    """Validate and store the save settings (folder, naming scheme, prefix)."""
    scheme = b.get("scheme", "original")
    if scheme not in SAVE_SCHEMES:
        raise ValueError("Unknown naming scheme")
    prefix = str(b.get("prefix") or "").strip()
    if scheme == "prefix":
        if not prefix:
            raise ValueError("Prefix is empty")
        _check_prefix(prefix)
    cfg = {"dir": validate_save_dir(b.get("dir")), "scheme": scheme, "prefix": prefix}
    tmp = SETTINGS_FILE + ".tmp"
    os.makedirs(os.path.dirname(SETTINGS_FILE) or ".", exist_ok=True)
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=1)
    os.replace(tmp, SETTINGS_FILE)
    save_cfg.update(cfg)
    return public_save_cfg()


def load_save_cfg():
    """Read the settings file at start; a broken or now-invalid file falls back to defaults."""
    try:
        with open(SETTINGS_FILE) as f:
            c = json.load(f)
        cfg = {"dir": validate_save_dir(c.get("dir")), "scheme": c.get("scheme", "original"),
               "prefix": str(c.get("prefix") or "")}
        if cfg["scheme"] not in SAVE_SCHEMES:
            raise ValueError
        if cfg["scheme"] == "prefix":
            _check_prefix(cfg["prefix"])
        save_cfg.update(cfg)
    except (OSError, ValueError, TypeError, AttributeError):
        pass


def public_save_cfg():
    return {**save_cfg, "effective_dir": captures_dir()}


def target_name(name, now=None):
    """Local file name by the chosen scheme (name = original name on the card)."""
    scheme = save_cfg["scheme"]
    if scheme == "datetime":
        # the file is fetched right after the shot, so the fetch time stands for the shot time
        return time.strftime("%Y%m%d_%H%M%S", now or time.localtime()) + "_" + name
    if scheme == "prefix" and save_cfg["prefix"]:
        return save_cfg["prefix"] + name
    return name


def save_capture(path, size=None):
    """Fetch a file from the card without overwriting existing ones."""
    folder = captures_dir()
    os.makedirs(folder, exist_ok=True)
    stem, ext = os.path.splitext(target_name(os.path.basename(path)))
    dest = os.path.join(folder, stem + ext)
    n = 0
    while os.path.exists(dest):
        if size is not None and save_cfg["scheme"] != "datetime" and os.path.getsize(dest) == size:
            return dest
        n += 1
        dest = os.path.join(folder, "%s-%d%s" % (stem, n, ext))
    cam.fetch_file(path, dest + ".part")
    os.replace(dest + ".part", dest)
    if hsl_auto["enabled"] and ext.lower() in (".jpg", ".jpeg", ".orf"):
        hsl_auto_run(dest)
    if ext.lower() in (".jpg", ".jpeg") or state["latest"] is None or \
            not state["latest"].lower().endswith((".jpg", ".jpeg")):
        state["latest"] = os.path.basename(dest)
    return dest


def card_snapshot():
    if state["transfer"] != "both" or conn_type == "usb":
        return None
    return {e["path"] for e in cam.images()}


def pull_new(seen):
    """Fetch new files from the card; the card needs a moment after the shot."""
    state["transfer_error"] = None
    try:
        for attempt in range(3):
            new = [e for e in cam.images() if e["path"] not in seen]
            if new:
                for e in jpg_last(new, lambda e: e["name"]):
                    save_capture(e["path"], e["size"])
                    seen.add(e["path"])
                return
            time.sleep(1.5)
        state["transfer_error"] = "No new file found on the card"
    except (CameraError, OSError, ET.ParseError) as e:
        state["transfer_error"] = str(e)


def shot(seen):
    new = cam.shoot()
    invalidate_device()  # card space has changed
    if conn_type == "usb":  # USB reports the new files directly
        remember_shot(new)
        if state["transfer"] == "both":
            state["transfer_error"] = None
            try:
                for path in jpg_last(new):
                    save_capture(path)
            except (CameraError, OSError) as e:
                state["transfer_error"] = str(e)
    elif seen is not None:
        pull_new(seen)


def run_job(name, total, work):
    if job["running"]:
        raise CameraError("A series is already running")
    ensure_idle()
    stop_job.clear()
    job.update(name=name, running=True, done=0, total=total, error=None)

    def runner():
        try:
            with capture():
                work(card_snapshot())
        except (CameraError, WriteBlocked, OSError, ValueError, ET.ParseError) as e:
            job["error"] = str(e)
        finally:
            job["running"] = False

    threading.Thread(target=runner, daemon=True).start()


def start_interval(count, seconds):
    count, seconds = int(count), float(seconds)
    if not 1 <= count <= 999:
        raise ValueError("Frame count must be between 1 and 999")
    if seconds < MIN_INTERVAL:
        raise ValueError("Interval must be at least %d s" % MIN_INTERVAL)

    def work(seen):
        for i in range(count):
            if stop_job.is_set():
                return
            begin = time.monotonic()
            shot(seen)
            job["done"] = i + 1
            if i + 1 < count:
                stop_job.wait(max(0, seconds - (time.monotonic() - begin)))

    run_job("Intervall", count, work)


def bracket_plan(enum, current, frames, step):
    """Exposure values of a series, step in thirds of the camera grid."""
    if frames not in (3, 5, 7) or step not in (1, 2, 3):
        raise ValueError("Bracketing: 3, 5 or 7 frames, step 1 to 3")
    i = enum.index(current)
    wanted = [i + k * step for k in range(-(frames // 2), frames // 2 + 1)]
    if wanted[0] < 0 or wanted[-1] >= len(enum):
        raise ValueError("Bracketing exceeds the camera's compensation range")
    return [enum[j] for j in wanted]


def start_bracket(frames, step):
    p = cam.props()["expcomp"]
    plan = bracket_plan(p["enum"], p["value"], int(frames), int(step))

    def work(seen):
        try:
            for i, value in enumerate(plan):
                if stop_job.is_set():
                    return
                cam.set_prop("expcomp", value)
                shot(seen)
                job["done"] = i + 1
        finally:
            cam.set_prop("expcomp", p["value"])

    run_job("Reihe", len(plan), work)


def orf_preview(path):
    """Largest embedded JPEG of an ORF file (browsers cannot show ORF)."""
    with open(path, "rb") as f:
        data = f.read()
    best, i = b"", data.find(b"\xff\xd8\xff")
    while i >= 0:
        end = data.find(b"\xff\xd9", i)
        if end < 0:
            break
        if end + 2 - i > len(best):
            best = data[i:end + 2]
        i = data.find(b"\xff\xd8\xff", end)
    return best


def local_files():
    folder = captures_dir()
    if not os.path.isdir(folder):
        return []
    out = []
    for name in os.listdir(folder):
        p = os.path.join(folder, name)
        if name.lower().endswith((".jpg", ".jpeg", ".orf")) and os.path.isfile(p):
            out.append({"name": name, "size": os.path.getsize(p), "mtime": os.path.getmtime(p)})
    return sorted(out, key=lambda e: e["mtime"], reverse=True)


# ---------- Software HSL (runs on the computer, so it works over USB and Wi-Fi) ----------
HSL_OUT = os.path.join(os.getcwd(), "out", "hsl")
hsl_lock = threading.Lock()      # one render at a time (an ORF needs a few 100 MB)
hsl_auto = {"enabled": False, "preset": "Neutral", "error": None}


def _hsl_module():
    try:
        from omcap import hsl
        import imageio.v2  # noqa: F401
    except ImportError as e:
        raise ValueError("HSL needs numpy and imageio (RAW also rawpy): %s" % e)
    return hsl


def hsl_presets():
    hsl = _hsl_module()
    with open(hsl.PRESET_FILE, encoding="utf-8") as f:
        return [p["name"] for p in json.load(f)["presets"]]


def hsl_apply(name, profile, tiff=False):
    """Apply a profile (preset name or profile dict) to a file in captures/.

    Writes <stem>_<EXT>_hsl.jpg (and <stem>_<EXT>_hsl.tif for ORF if tiff) to HSL_OUT, never next to the source.
    """
    hsl = _hsl_module()
    src = capture_path(name)
    prof = hsl.validate_profile(profile) if isinstance(profile, dict) else hsl.load_profile(profile or "Neutral")
    import imageio.v2 as imageio
    import numpy as np
    with hsl_lock:
        rgb, is_raw = hsl._read_image(src)
        res = hsl.apply_hsl(rgb, prof)
        stem, ext = os.path.splitext(os.path.basename(src))
        stem += "_" + ext[1:].upper()  # x.JPG and x.ORF must not overwrite each other
        os.makedirs(HSL_OUT, exist_ok=True)
        out = stem + "_hsl.jpg"
        imageio.imwrite(os.path.join(HSL_OUT, out), hsl._to_u8(res), quality=95)
        res_tif = None
        if is_raw and tiff:
            res_tif = stem + "_hsl.tif"
            imageio.imwrite(os.path.join(HSL_OUT, res_tif), (np.clip(res, 0, 1) * 65535 + 0.5).astype("uint16"))
    return {"name": out, "tiff": res_tif, "source": os.path.basename(src)}


def hsl_out_path(name):
    p = os.path.join(HSL_OUT, os.path.basename(name))
    if not os.path.isfile(p):
        raise KeyError("File not found: %s" % name)
    return p


def hsl_auto_run(dest):
    """After a save to the computer: extra _hsl.jpg in a background thread (errors go to state)."""
    def run():
        try:
            hsl_apply(os.path.basename(dest), hsl_auto["preset"])
            hsl_auto["error"] = None
        except (ValueError, KeyError, OSError) as e:
            hsl_auto["error"] = str(e)
    threading.Thread(target=run, daemon=True).start()


def capture_path(name):
    p = os.path.join(captures_dir(), os.path.basename(name))
    if not os.path.isfile(p):
        raise KeyError("File not found: %s" % name)
    return p


def card_cache(kind, imgs=None):
    """Card list saved on the computer per connection type (the camera needs ~3 ms per file,
    about 8 s for 2900 files over Wi-Fi). With `imgs` store it, else return it or None."""
    path = os.path.join(os.path.dirname(PREVIEW_CACHE), "cardlist_%s.json" % kind)
    if imgs is not None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=os.path.dirname(path), suffix=".part", delete=False) as f:
            json.dump(imgs, f)  # own temp file per request: two tabs may save at once
        os.replace(f.name, path)
        return imgs
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def cached_preview(kind, path, size, fetch):
    """Preview from the card, cached on disk (key: path, file size, kind).

    Without a file size nothing is cached, because a different image could hide behind the path.
    """
    if not size:
        return fetch()
    name = "%s_%s_%s.jpg" % (path.strip("/").replace("/", "_"), int(size), kind)
    dest = os.path.join(PREVIEW_CACHE, name)
    if os.path.isfile(dest):
        with open(dest, "rb") as f:
            return f.read()
    data = fetch()
    if data[:2] == b"\xff\xd8":
        os.makedirs(PREVIEW_CACHE, exist_ok=True)
        with open(dest + ".part", "wb") as f:
            f.write(data)
        os.replace(dest + ".part", dest)
        prune_preview_cache()
    return data


def prune_preview_cache():
    """Limit the cache to PREVIEW_CACHE_MAX, deleting the oldest files first (down to 80 %)."""
    files = [e for e in os.scandir(PREVIEW_CACHE) if e.is_file()]
    total = sum(e.stat().st_size for e in files)
    if total <= PREVIEW_CACHE_MAX:
        return
    for e in sorted(files, key=lambda e: e.stat().st_mtime):
        if total <= PREVIEW_CACHE_MAX * 0.8:
            break
        total -= e.stat().st_size
        os.remove(e.path)


def playback(enter):
    """Wi-Fi: for playback switch to mode "play", only there the camera delivers medium previews.

    The live view pauses meanwhile and resumes on leaving.
    """
    if conn_type != "wifi":
        return
    if enter:
        if state["play"] is not None:
            return
        ensure_idle()
        resume = live.running
        if resume:
            cam.stop_liveview()
            live.stop()
        cam.set_mode("play")
        state["play"] = {"resume": resume}
    elif state["play"] is not None:
        resume = state["play"]["resume"]
        state["play"] = None
        cam.set_mode("rec")
        if resume:
            start_live()


def movie_length(path, size):
    """Movie length only in mode "play" (otherwise errorcode 1001), read once per path and size."""
    if conn_type != "wifi":
        raise CameraError("Movie length only over Wi-Fi")
    if state["play"] is None:
        raise CameraError("Movie length only in Playback")
    key = (path, size)
    if key not in movtime_cache:
        movtime_cache[key] = cam.movie_length(path)
    return movtime_cache[key]


def reset_share_order():
    """Reset Share Order: changes the card, so never during a shot."""
    if conn_type != "wifi":
        raise CameraError("Share Order only over Wi-Fi")
    if cam.stage or state["take"] or state["movie"] or job["running"] or busy.locked():
        raise CameraError("Camera is busy")
    cam.reset_share_order()


def usb_lens():
    """USB: lens from the last reported JPG, otherwise only the focal length range (d04a).

    Searching the card for the newest JPG takes over 30 s over USB and stops the live view.
    """
    if conn_type != "usb":
        raise CameraError("Lens without a file only over USB")
    path = getattr(cam, "last_jpg", None)
    info = None
    if path:
        try:
            info = lens(path)
        except (CameraError, OSError):
            info = None
    if info is None or not info.get("focal_min"):
        try:
            lo, hi, now = cam.lens_focal()
            info = dict(info or {}, focal_min=lo or now, focal_max=hi or now, focal=now)
        except CameraError as e:
            print("USB lens: d04a not readable:", e)
    return info


def picture_info(path):
    """Shooting data of a JPG on the card for the playback info display, read once per path.

    Both connections read only the file head (USB: partial read, whole file as fallback).
    """
    if not path.lower().endswith((".jpg", ".jpeg")):
        raise CameraError("Picture info only from JPG files")
    if path not in exif_cache:
        if len(exif_cache) > 2000:
            exif_cache.clear()
        # a file already read in full for /api/full is reused (USB); otherwise only the head
        head = jpg_cache.get(path) or cam.read_head(path, exif.HEAD_BYTES)
        exif_cache[path] = exif.picture_info(head)
    return exif_cache[path]


def lens(path):
    """Lens data of the shot path (JPG on the card), read only once per path."""
    if not path.lower().endswith((".jpg", ".jpeg")):
        raise CameraError("Lens data only from JPG files")
    if path not in lens_cache:
        lens_cache[path] = exif.lens_info(cam.read_head(path, exif.HEAD_BYTES))
    return lens_cache[path]


def preview_path(path):
    """For previews use the JPG of the same shot if present (instead of the small preview in the ORF)."""
    stem, ext = os.path.splitext(path)
    if ext.lower() != ".orf":
        return path
    for jpg in (".JPG", ".jpg", ".JPEG", ".jpeg"):
        if os.path.isfile(stem + jpg):
            return stem + jpg
    return path


def public_state():
    now = time.time()
    return {
        # busy: shooting sequence or shutter command running (camera may not be in mode "rec")
        "stage": cam.stage, "busy": busy.locked() or state["pressing"], "indexing": state["indexing"], "live": live.running, "lv_age": live.age, "lvqty": cam.lvqty, "job": job,
        "transfer": state["transfer"], "latest": state["latest"], "play": state["play"] is not None,
        "transfer_error": state["transfer_error"], "hsl_error": hsl_auto["error"],
        "take": now - state["take"] if state["take"] else None,
        "movie": now - state["movie"]["since"] if state["movie"] else None,
        # Wi-Fi only: values the camera sends with every live view frame (REQ-F29)
        "lvinfo": live.live_values() if hasattr(live, "live_values") else None,
    }


# --- HTTP --------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    timing = False  # --timing: print each API request with its duration (performance checks)

    def log_message(self, *a):
        pass

    def log_request(self, code="-", size="-"):
        t0 = getattr(self, "_t0", None)
        if self.timing and t0 is not None and not self.path.startswith(("/api/state", "/api/connections")):
            print("%s %6.0f ms %s %s %s" % (time.strftime("%H:%M:%S"), (time.monotonic() - t0) * 1000,
                                              code, self.command, self.path[:80]), flush=True)

    def _send(self, body, ctype="application/json", code=200):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _image(self, body, q):
        """Send JPG; with the file size in the URL the browser may keep it for a week."""
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        if q.get("size"):
            self.send_header("Cache-Control", "private, max-age=%d, immutable" % IMAGE_MAX_AGE)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _trusted(self):
        """Only our own UI may control the camera, no foreign web page."""
        if self.headers.get("Host") not in allowed_hosts:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in {"http://" + h for h in allowed_hosts}

    def do_GET(self):
        self._t0 = time.monotonic()
        if not self._trusted():
            return self._send({"error": "Access denied"}, code=403)
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path == "/":
                with open(os.path.join(ROOT, "web", "index.html"), "rb") as f:
                    return self._send(f.read(), "text/html; charset=utf-8")
            if u.path == "/api/app":
                # Lets a second start recognise that this app already runs on the port.
                return self._send({"app": APP_ID, "version": __version__,
                                   "allow_write": options.get("allow_write", False)})
            if u.path == "/api/connections":
                return self._send(connections())
            if u.path == "/api/savecfg":
                return self._send(public_save_cfg())
            if u.path == "/api/local":
                return self._send(local_files())
            if u.path == "/api/hsl/presets":
                return self._send({"presets": hsl_presets(), "auto": dict(hsl_auto)})
            if u.path.startswith("/out-hsl/"):
                p = hsl_out_path(urllib.parse.unquote(u.path[len("/out-hsl/"):]))
                with open(p, "rb") as f:
                    return self._send(f.read(), "image/tiff" if p.lower().endswith(".tif") else "image/jpeg")
            if u.path.startswith("/captures/"):
                p = preview_path(capture_path(urllib.parse.unquote(u.path[len("/captures/"):])))
                if p.lower().endswith(".orf"):
                    return self._send(orf_preview(p), "image/jpeg")
                with open(p, "rb") as f:
                    return self._send(f.read(), "image/jpeg")
            if cam is None:
                return self._send({"error": "Not connected"}, code=409)
            if u.path == "/api/status":
                return self._send({
                    "type": conn_type, "features": cam.features,
                    "model": cam.caminfo(), "host": cam.host,
                    "cgis": sorted(cam.commandlist()), "allow_write": cam.allow_write,
                })
            if u.path == "/api/level":
                if conn_type != "usb":
                    raise CameraError("Level Gauge only works over USB")
                return self._send(cam.level())
            if u.path == "/api/afarea":
                return self._send(af_area())
            if u.path == "/api/lvext":  # research: camera status sent with the Wi-Fi live view
                return self._send(live.ext_info() if hasattr(live, "ext_info") else {"error": "no Wi-Fi live view"})
            if u.path == "/api/state":
                return self._send(public_state())
            if u.path == "/api/device":
                return self._send(device_status(force=q.get("fresh") == "1"))
            if u.path == "/api/props":
                return self._send(cam.props())
            if u.path == "/api/afframe":
                return self._send(cam.touch_frame())
            if u.path == "/api/images":
                if q.get("cached") == "1":  # last list of this connection type, instant
                    return self._send(card_cache(conn_type) or [])
                if q.get("newest") == "1" and conn_type == "wifi":
                    return self._send(wifi_images_newest())
                root = q.get("dir", "/DCIM")
                imgs = cam.images(root)
                imgs.sort(key=lambda e: (e["date"], e["time"]), reverse=True)
                if root == "/DCIM":  # only the whole card replaces the saved list
                    card_cache(conn_type, imgs)
                return self._send(imgs)
            if u.path == "/api/shareorder":
                if conn_type != "wifi":
                    raise CameraError("Share Order only over Wi-Fi")
                return self._send(cam.share_order())
            if u.path == "/api/movlength":
                return self._send({"seconds": movie_length(q["path"], q.get("size"))})
            if u.path == "/api/newshot":  # Wi-Fi: thumbnail of the next picture after q["before"]
                hit = wifi_guess_new(q.get("before")) if conn_type == "wifi" else None
                if not hit:
                    return self._send({"error": "not found"}, code=404)
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(hit[1])))
                self.send_header("X-Path", hit[0])
                self.end_headers()
                return self.wfile.write(hit[1])
            if u.path == "/api/lastshot":
                # USB: the camera reports the new files of a shot (Wi-Fi uses /api/newshot)
                return self._send({"path": state["last_shot"] if conn_type == "usb" else None})
            if u.path == "/api/exif":
                return self._send({"exif": picture_info(q["path"])})
            if u.path == "/api/lens":
                return self._send({"lens": lens(q["path"]) if q.get("path") else usb_lens()})
            if u.path == "/api/thumb":
                return self._image(cached_preview("thumb", q["path"], q.get("size"),
                                                  lambda: cam.thumbnail(q["path"])), q)
            if u.path == "/api/resize":  # only in mode "play" (playback over Wi-Fi)
                px = q.get("px", "1024")
                return self._image(cached_preview("r" + px, q["path"], q.get("size"),
                                                  lambda: cam.resizeimg(q["path"], px)), q)
            if u.path == "/api/screen":
                return self._image(cam.screennail(q["path"]), q)
            if u.path == "/api/full":  # in shooting mode there are no large previews
                if not q["path"].lower().endswith((".jpg", ".jpeg")):
                    raise CameraError("Only JPG files can be shown this way")
                return self._image(read_jpg(q["path"]) if conn_type == "usb" else cam.read_file(q["path"]), q)
            if u.path == "/live.mjpg":
                return self._mjpeg()
            self._send({"error": "not found"}, code=404)
        except (CameraError, WriteBlocked, KeyError, OSError, ValueError, ET.ParseError) as e:
            self._send({"error": str(e)}, code=502)

    def _mjpeg(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=f")
        self.end_headers()
        seq = 0
        stream = live  # stays valid even if the connection is switched
        try:
            while live is stream:
                seq, frame = stream.wait_frame(seq)
                if frame is None:
                    continue
                self.wfile.write(b"--f\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(frame))
                self.wfile.write(frame + b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        self._t0 = time.monotonic()
        if not self._trusted():
            return self._send({"error": "Access denied"}, code=403)
        try:
            b = self._body()
            extra = self._action(self.path, b)
            if extra is False:
                return self._send({"error": "not found"}, code=404)
            self._send({"ok": True, **(extra or {})})
        except WriteBlocked as e:
            self._send({"error": str(e)}, code=403)
        except (CameraError, KeyError, OSError, ValueError, TypeError,
                ET.ParseError, subprocess.SubprocessError) as e:
            self._send({"error": str(e)}, code=502)

    def _shutter(self, stage):
        """Set shutter stage: 0 release, 1 half, 2 full."""
        if cam.stage == 0 and stage:
            ensure_idle()
            state["resume_live"] = live.running
            state["seen"] = card_snapshot()  # no longer readable in mode "shutter"
        cam.press(stage)
        if conn_type == "usb":  # over USB the live view simply keeps running
            state["resume_live"] = False
            if stage == 0:
                new = cam.take_new_files()
                remember_shot(new)
                if state["transfer"] == "both":
                    for p in jpg_last(new):
                        save_capture(p)
            if stage == 1:
                # same grid as /api/afarea (focus position comes in 1280x960)
                return {"last_af": cam.af_area()["last_af"]}
        elif stage == 0:
            if state["seen"] is not None:
                pull_new(state["seen"])
                state["seen"] = None
            if state["resume_live"]:
                state["resume_live"] = False
                start_live()
        return None

    def _action(self, path, b):
        if path == "/api/connect":
            connect(b["type"])
            return {"type": conn_type}
        if path == "/api/disconnect":
            disconnect()
            return None
        if path == "/api/poweroff":
            power_off()
            return None
        if path == "/api/savecfg":
            return {"cfg": set_save_cfg(b)}
        if path == "/api/open":
            subprocess.run(["open", "-a", "OM Workspace", capture_path(b["name"])], check=True)
            return None
        if path == "/api/hsl":
            return hsl_apply(b["name"], b.get("profile"), bool(b.get("tiff")))
        if path == "/api/hslauto":
            if b.get("enabled"):
                hsl_presets()   # clear error if numpy is missing
            hsl_auto.update(enabled=bool(b.get("enabled")), preset=str(b.get("preset") or "Neutral"))
            return {"auto": dict(hsl_auto)}
        if cam is None:
            raise CameraError("Not connected")
        if path == "/api/refresh":
            if conn_type != "usb":
                raise CameraError("Only needed over USB")
            ensure_idle()
            cam.refresh()
            return None
        if path == "/api/afarea":
            if b.get("focus") and conn_type == "usb":  # All Targets: focus only
                cam.focus()
            else:
                set_af_area(b.get("mode"), b.get("field"))
            return af_area()
        if path == "/api/playback":
            playback(b.get("action") == "enter")
            return {"play": state["play"] is not None}
        if path == "/api/liveview":
            if b.get("action") == "start":
                cam.set_mode("rec", b.get("lvqty", "0800x0600") if conn_type == "wifi" else b.get("lvqty"))
                start_live()
            else:
                cam.stop_liveview()
                live.stop()
        elif path == "/api/mode":
            if conn_type == "usb":
                cam.press(0)
            cam.set_mode(b["mode"])
            if b["mode"] == "rec":
                cam.stage = 0  # emergency exit in case the camera is stuck in "shutter"
        elif path == "/api/set":
            cam.set_prop(b["prop"], b["value"])
        elif path == "/api/shoot":
            ensure_idle()
            with capture():
                shot(card_snapshot())
        elif path == "/api/shutter":
            state["pressing"] = True
            try:
                return self._shutter(int(b["stage"]))
            finally:
                state["pressing"] = False
        elif path == "/api/interval":
            start_interval(b["count"], b["seconds"])
        elif path == "/api/bracket":
            start_bracket(b["frames"], b["step"])
        elif path == "/api/job/stop":
            stop_job.set()
        elif path == "/api/take":
            if b.get("action") == "prepare":
                ensure_idle()
                cam.take_prepare()
            elif b.get("action") == "start":
                ensure_idle()
                cam.take_start(b.get("exposuremin"), b.get("upperlimit"))
                state["take"] = time.time()
            else:
                try:
                    cam.take_stop()
                finally:
                    state["take"] = None
        elif path == "/api/movie":
            if b.get("action") == "start":
                # Over Wi-Fi the camera only records movies in Movie mode (n): switch briefly
                ensure_idle()
                before = cam.prop("takemode")
                if before != "movie":
                    cam.set_prop("takemode", "movie")
                try:
                    cam.movie_start()
                except (CameraError, WriteBlocked):
                    if before != "movie":
                        cam.set_prop("takemode", before)
                    raise
                state["movie"] = {"since": time.time(), "before": before}
            else:
                before = (state["movie"] or {}).get("before")
                try:
                    cam.movie_stop()
                finally:
                    state["movie"] = None
                if before and before != "movie":
                    cam.set_prop("takemode", before)
        elif path == "/api/transfer":
            if b["target"] not in ("sd", "both"):
                raise ValueError("Unknown target")
            state["transfer"] = b["target"]
        elif path == "/api/shareorder/clear":
            reset_share_order()
        elif path == "/api/download":
            dest = save_capture(b["path"], b.get("size"))
            return {"saved": dest, "name": os.path.basename(dest)}
        else:
            return False


APP_ID = "em1-capture"


def running_app(port, timeout=1.5):
    """Info dict if E-M1 Capture already answers on this port, else None."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/app" % port, timeout=timeout) as r:
            info = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) and info.get("app") == APP_ID else None


def open_browser(url, delay=0.6):
    """Open the app in the default browser shortly after the server is up."""
    threading.Timer(delay, webbrowser.open, (url,)).start()


def main(argv=None):
    global CAPTURES, PREVIEW_CACHE, SETTINGS_FILE, HSL_OUT
    p = argparse.ArgumentParser(prog="em1-capture", description="Local web app to control an Olympus OM-D E-M1 over Wi-Fi or USB.")
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    p.add_argument("--host", default="192.168.0.10", help="camera IP in the camera's Wi-Fi (default 192.168.0.10)")
    p.add_argument("--port", type=int, default=8765, help="local port of the web app (default 8765)")
    p.add_argument("--allow-write", action="store_true",
                   help="allow taking pictures and changing settings (default: read only)")
    p.add_argument("--data-dir", default=os.getcwd(),
                   help="folder for saved pictures (captures/) and the preview cache (out/cache/); default: current folder")
    p.add_argument("--no-browser", action="store_true", help="do not open the browser at start")
    p.add_argument("--timing", action="store_true", help="print every request with its duration")
    a = p.parse_args(argv)
    Handler.timing = a.timing
    url = "http://127.0.0.1:%d/" % a.port
    try:
        server = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    except OSError as e:
        if e.errno != errno.EADDRINUSE:
            raise
        info = running_app(a.port)
        if info is None:
            print("Port %d is used by another program. Start with --port 8766 (or another free port)." % a.port)
            return 1
        print("E-M1 Capture is already running: %s (%s)" % (url, "WRITE ENABLED" if info.get("allow_write") else "read only"))
        if a.allow_write and not info.get("allow_write"):
            print("It runs read only. To take pictures, stop it (Ctrl+C in its window) and start again.")
        if not a.no_browser:
            webbrowser.open(url)
        return 0
    CAPTURES = os.path.join(a.data_dir, "captures")
    PREVIEW_CACHE = os.path.join(a.data_dir, "out", "cache", "previews")
    SETTINGS_FILE = os.path.join(a.data_dir, "omcap-settings.json")
    load_save_cfg()
    HSL_OUT = os.path.join(a.data_dir, "out", "hsl")
    options.update(host=a.host, allow_write=a.allow_write)
    allowed_hosts.update({"127.0.0.1:%d" % a.port, "localhost:%d" % a.port})
    print("em1-capture %s  %s  (%s)" % (__version__, url, "WRITE ENABLED" if a.allow_write else "read only"))
    print("Keep this window open while you use the app; stop with Ctrl+C.")
    if not a.no_browser:
        open_browser(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nE-M1 Capture stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
