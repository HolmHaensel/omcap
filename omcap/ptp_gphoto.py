"""The part of the python-gphoto2 API that UsbCamera uses, on top of the own PTP layer (omcap/ptp.py).

UsbCamera talks to `self.gp` (a module) and `self._c` (a Camera). With this module as `self.gp` the app runs
on the own PTP layer without libgphoto2; libgphoto2 stays the fallback (and the backend on Linux).

Widget names and value texts follow libgphoto2 (camlibs/ptp2/config.c, Olympus OM-D), so the app sees the
same strings with both backends: shutterspeed "1/250", "60", "32/10", "Composite", "Bulb"; aperture "3.5";
exposurecompensation "-0.3"; iso "Auto", "Low", "200"; liveviewsize "1280x960"; batterylevel "100%";
other properties as "dXXX" with the decimal value; opcode "0x9481,0x3" runs an operation.

What is faster than libgphoto2 (measured 2026-11-13, out/research/usb_performance.md):
- card index: all object handles in one call (0.01 s); object infos are kept on disk by handle, so only new
  files are asked for after the first connect (libgphoto2 reads all 2900 files at every connect, 51-72 s);
- event check: one interrupt read (10 ms) instead of ~0.3 s;
- live view size: any size the camera offers, also with libgphoto2 2.5.34 installed.
"""
import json
import os
import struct
import tempfile
import time

from . import ptp

# Constants with the names of python-gphoto2 (values only used inside this module and UsbCamera)
GP_WIDGET_TEXT, GP_WIDGET_RANGE, GP_WIDGET_RADIO, GP_WIDGET_MENU = 2, 3, 5, 6
GP_EVENT_UNKNOWN, GP_EVENT_TIMEOUT, GP_EVENT_FILE_ADDED, GP_EVENT_FOLDER_ADDED = 0, 1, 2, 3
GP_FILE_TYPE_PREVIEW, GP_FILE_TYPE_NORMAL = 0, 1
GP_ERROR, GP_ERROR_NOT_SUPPORTED, GP_ERROR_IO = -1, -6, -7

EV_OBJECT_ADDED = (0x4002, 0xC002, 0xC102)  # standard and Olympus OM-D "object added"
EV_PROP_CHANGED = (0xC008, 0xC108)
FOLDER_FORMAT = 0x3001
LV_SIZES = ("320x240", "640x480", "800x600", "1024x768", "1280x960")
INDEX_VERSION = 1


class GPhoto2Error(Exception):
    def __init__(self, message, code=GP_ERROR):
        super().__init__(message)
        self.code = code


def _wrap(fn):
    """PTP and USB errors look like libgphoto2 errors to the caller."""
    def call(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ptp.PtpError as e:
            raise GPhoto2Error("PTP: %s" % e, GP_ERROR_IO)
        except (struct.error, IndexError, KeyError) as e:
            raise GPhoto2Error("PTP: unexpected answer (%s)" % e)
    call.__name__ = fn.__name__
    return call


# --- Value texts like libgphoto2 ---------------------------------------------------------------
SHUTTER_SPECIAL = {0xFFFFFFFF: "Auto", 0xFFFFFFFC: "Bulb", 0xFFFFFFFA: "Composite", 0xFFFFFFFB: "Time"}
ISO_SPECIAL = {65535: "Auto", 65533: "Low"}


def shutter_text(v):
    if v in SHUTTER_SPECIAL:
        return SHUTTER_SPECIAL[v]
    x, y = v >> 16, v & 0xFFFF
    if x % 10 == 0 and y % 10 == 0:  # libgphoto2: 600/10 -> 60/1
        x, y = x // 10, y // 10
    return "%d" % x if y == 1 else "%d/%d" % (x, y)


def signed(v, dtype):
    bits = {1: 8, 3: 16, 5: 32, 7: 64}.get(dtype)
    return v - (1 << bits) if bits and v >= 1 << (bits - 1) else v


def generic_text(v, dtype):
    return str(v) if isinstance(v, str) else str(signed(v, dtype))


def parse_int(text, dtype):
    """Decimal text to the raw value of the type (accepts negative values for unsigned types)."""
    v = int(float(text))
    size = struct.calcsize("<" + ptp.DTYPES[dtype])
    return v & ((1 << (8 * size)) - 1)


# widget name -> (property code, raw -> text, widget type)
NAMED = {
    "shutterspeed": (0xD01C, lambda v, t: shutter_text(v), GP_WIDGET_RADIO),
    "aperture": (0xD002, lambda v, t: "%.1f" % (v / 10.0), GP_WIDGET_RADIO),
    "exposurecompensation": (0xD008, lambda v, t: "%g" % (signed(v, 3) / 1000.0), GP_WIDGET_RADIO),
    "iso": (0xD007, lambda v, t: ISO_SPECIAL.get(v, str(v)), GP_WIDGET_RADIO),
    "whitebalance": (0xD01E, generic_text, GP_WIDGET_RADIO),
    "liveviewsize": (0xD06D, lambda v, t: "%dx%d" % (v >> 16, v & 0xFFFF), GP_WIDGET_RADIO),
}


class Widget:
    def __init__(self, name, value, choices=(), readonly=False, wtype=GP_WIDGET_MENU, rng=None, apply=None):
        self.name, self._value, self._choices = name, value, list(choices)
        self._readonly, self._type, self._range, self._apply = readonly, wtype, rng, apply

    def get_value(self):
        return self._value

    def set_value(self, value):
        self._value = str(value)

    def get_choices(self):
        return iter(self._choices)

    def count_choices(self):
        return len(self._choices)

    def get_choice(self, i):
        return self._choices[i]

    def get_readonly(self):
        return int(self._readonly)

    def get_type(self):
        return self._type

    def get_range(self):
        if self._range is None:
            raise GPhoto2Error("not a range widget", GP_ERROR_NOT_SUPPORTED)
        return self._range


class CameraFile:
    def __init__(self, data):
        self._data = data

    def get_data_and_size(self):
        return self._data

    def save(self, dest):
        with open(dest, "wb") as f:
            f.write(self._data)


class CameraList:
    def __init__(self, names):
        self._names = list(names)

    def count(self):
        return len(self._names)

    def get_name(self, i):
        return self._names[i]


class _Info:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class CameraFilePath:
    def __init__(self, folder, name):
        self.folder, self.name = folder, name


def ptp_time(text):
    """PTP date "20261113T142530" (optionally with ".s" or a zone) -> epoch seconds, local time; 0 if missing."""
    try:
        return time.mktime(time.strptime(text[:15], "%Y%m%dT%H%M%S"))
    except (TypeError, ValueError):
        return 0


# --- Card index ------------------------------------------------------------------------------------
class CardIndex:
    """Object handle -> (storage, parent, name, size, mtime, folder), kept on disk between sessions.

    The E-M1 keeps the handles of a card across sessions. A cached entry is trusted only after a spot check:
    the newest and the oldest cached handle must still have the same name, otherwise the cache is dropped
    (other card, or the card was formatted)."""

    def __init__(self, cache_path=None):
        self.cache_path = cache_path
        self.objects = {}
        self._by_name = {}  # (storage, parent, name) -> handle
        self.loaded = False

    def _set(self, objects):
        self.objects = objects
        self._by_name = {(v[0], v[1], v[2]): h for h, v in objects.items()}

    def _read_cache(self):
        if not self.cache_path:
            return {}
        try:
            with open(self.cache_path) as f:
                data = json.load(f)
            if data.get("version") != INDEX_VERSION:
                return {}
            return {int(h): tuple(v) for h, v in data["objects"].items()}
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def save(self):
        if not self.cache_path:
            return
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.cache_path), suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump({"version": INDEX_VERSION, "objects": {str(h): list(v) for h, v in self.objects.items()}}, f)
            os.replace(tmp, self.cache_path)
        except OSError:
            pass

    @staticmethod
    def entry(info):
        return (info["storage"], info["parent"], info["name"], info["size"],
                ptp_time(info["modified"] or info["captured"]), bool(info["folder"]))

    def load(self, cam):
        """Read the handles of all storages and the infos of handles not in the cache."""
        handles = cam.handles()
        cached = self._read_cache()
        known = [h for h in handles if h in cached]
        for h in (known[:1] + known[-1:]) if known else []:
            if cam.object_info(h)["name"] != cached[h][2]:
                cached = {}
                break
        objects = {}
        for h in handles:
            objects[h] = cached.get(h) or self.entry(cam.object_info(h))
        self._set(objects)
        self.loaded = True
        if objects != cached:
            self.save()

    def add(self, cam, handle):
        v = self.objects[handle] = self.entry(cam.object_info(handle))
        self._by_name[(v[0], v[1], v[2])] = handle
        self.save()
        return self.objects[handle]

    # paths like libgphoto2: /store_00010001/DCIM/100OLYMP/P1010001.JPG
    def path(self, handle):
        parts = []
        storage = None
        while handle in self.objects and len(parts) < 16:  # 16: guard against a parent loop
            storage, parent, name = self.objects[handle][:3]
            parts.append(name)
            handle = parent
        return "/store_%08x/" % (storage or 0) + "/".join(reversed(parts))

    def folder_of(self, handle):
        return self.path(handle).rsplit("/", 1)[0]

    def storages(self):
        return sorted({v[0] for v in self.objects.values()})

    def find(self, path):
        """Handle of a folder or file path; 0 for a storage root; None if unknown."""
        parts = [p for p in path.split("/") if p]
        if not parts or not parts[0].startswith("store_"):
            return None
        try:
            storage = int(parts[0][6:], 16)
        except ValueError:
            return None
        handle = 0
        for name in parts[1:]:
            handle = self._by_name.get((storage, handle, name))
            if handle is None:
                return None
        return handle

    def children(self, path, folders):
        parts = [p for p in path.split("/") if p]
        if not parts:
            return ["store_%08x" % s for s in self.storages()] if folders else []
        parent = self.find(path)
        if parent is None:
            raise GPhoto2Error("folder not found: %s" % path)
        storage = int(parts[0][6:], 16)
        return sorted(v[2] for v in self.objects.values()
                      if v[0] == storage and v[1] == parent and v[5] == folders)


# --- Camera ----------------------------------------------------------------------------------------
class Camera:
    """One USB session over the own PTP layer, with the method names of gphoto2.Camera."""

    index_cache = None  # path of the card index on disk, set by the app

    def __init__(self):
        self._ptp = None
        self._model = None
        self._index = CardIndex(Camera.index_cache)

    @_wrap
    def init(self):
        transport = ptp.UsbTransport(tries=4)
        cam = ptp.PtpCamera(transport)
        try:
            cam.open()
            self._model = cam.device_info()["model"]
            # Card index first: GetObjectInfo takes 10-12 ms in camera mode but ~26 ms under PC control
            # (measured 2026-11-13, 2948 files: ~30 s instead of 88 s; with the disk cache well under 1 s)
            try:
                self._index.load(cam)
            except ptp.PtpError:
                pass  # loaded later on first use
            # PC control: needed for live view and shooting (libgphoto2 does the same at init)
            if not cam.pc_mode(True):
                raise ptp.PtpError("camera did not switch to computer control")
        except Exception:
            transport.close()
            raise
        self._ptp = cam

    def exit(self):
        cam, self._ptp = self._ptp, None
        if cam is None:
            return
        try:
            cam.pc_mode(False, wait=2.0)
        except ptp.PtpError:
            pass
        try:
            cam.close()
        except ptp.PtpError:
            cam.t.close()

    def _cam(self):
        if self._ptp is None:
            raise GPhoto2Error("camera not initialised")
        return self._ptp

    # Settings
    @_wrap
    def get_single_config(self, name):
        cam = self._cam()
        if name == "cameramodel":
            return Widget(name, self._model or "", readonly=True, wtype=GP_WIDGET_TEXT)
        if name == "batterylevel":
            return Widget(name, "%d%%" % cam.prop_desc(0x5001)["value"], readonly=True, wtype=GP_WIDGET_TEXT)
        if name == "opcode":
            return Widget(name, "0x1001,0xparam1,0xparam2", wtype=GP_WIDGET_TEXT)
        code, text, wtype = self._lookup(name)
        desc = cam.prop_desc(code)
        dtype = desc["type"]
        values = desc.get("enum", [])
        if name == "liveviewsize" and not values:
            choices = list(LV_SIZES)
        else:
            choices = [text(v, dtype) for v in values]
        rng = desc.get("range")
        if rng and wtype == GP_WIDGET_MENU:
            wtype = GP_WIDGET_RANGE
        return Widget(name, text(desc["value"], dtype), choices, not desc["writable"], wtype,
                      rng=tuple(signed(v, dtype) for v in rng) if rng else None)

    @staticmethod
    def _lookup(name):
        if name in NAMED:
            return NAMED[name]
        if len(name) == 4 and name[0] == "d":
            try:
                return int(name, 16), generic_text, GP_WIDGET_MENU
            except ValueError:
                pass
        raise GPhoto2Error("unknown setting: %s" % name, GP_ERROR_NOT_SUPPORTED)

    @_wrap
    def set_single_config(self, name, widget):
        cam = self._cam()
        value = widget.get_value()
        if name == "opcode":
            code, *params = [int(p, 16) for p in value.split(",")]
            cam.transact(code, tuple(params))
            return
        code, text, _ = self._lookup(name)
        desc = cam.prop_desc(code)
        dtype = desc["type"]
        # the raw value whose text is the wanted one (as libgphoto2 does); else a number for dXXX
        raw = next((v for v in desc.get("enum", []) if text(v, dtype) == value), None)
        if raw is None and name == "liveviewsize":
            w, h = (int(v) for v in value.split("x"))
            raw = w << 16 | h
        if raw is None:
            if name in NAMED:
                raise GPhoto2Error("value not offered: %s=%s" % (name, value), GP_ERROR_NOT_SUPPORTED)
            raw = parse_int(value, dtype)
        cam.set_prop(code, raw, dtype)

    @_wrap
    def get_storageinfo(self):
        cam = self._cam()
        return [_Info(freekbytes=cam.storage_info(s)["free"] // 1024) for s in cam.storage_ids()]

    # Live view and events
    @_wrap
    def capture_preview(self):
        data = self._cam().liveview_frame()
        if not data:
            raise GPhoto2Error("no live view image", GP_ERROR_IO)
        return CameraFile(data)

    @_wrap
    def wait_for_event(self, timeout):
        """Next event within `timeout` ms: (GP_EVENT_*, data) like gphoto2.Camera.wait_for_event."""
        cam = self._cam()
        end = time.monotonic() + timeout / 1000.0
        while True:
            left = int((end - time.monotonic()) * 1000)
            ev = cam.event(max(1, min(left, 50)))  # libusb: 0 would mean "wait forever"
            if ev:
                return self._event(*ev)
            if left <= 0:
                return GP_EVENT_TIMEOUT, None

    def _event(self, code, params):
        p1 = params[0] if params else 0
        if code in EV_OBJECT_ADDED and p1:
            if self._index.loaded:
                entry = self._index.add(self._cam(), p1)
            else:  # the path needs the folders: load the index now (it contains the new object)
                self._index.load(self._cam())
                entry = self._index.objects.get(p1) or self._index.add(self._cam(), p1)
            path = self._index.path(p1)
            folder, name = path.rsplit("/", 1)
            return (GP_EVENT_FOLDER_ADDED if entry[5] else GP_EVENT_FILE_ADDED), CameraFilePath(folder, name)
        if code in EV_PROP_CHANGED:
            return GP_EVENT_UNKNOWN, "PTP Property %04x changed" % (p1 & 0xFFFF)
        return GP_EVENT_UNKNOWN, "PTP Event %04x, Param1 %08x" % (code, p1)

    # Card
    def _ensure_index(self):
        if not self._index.loaded:
            self._index.load(self._cam())

    def _handle(self, folder, name):
        self._ensure_index()
        h = self._index.find(folder.rstrip("/") + "/" + name)
        if not h:
            raise GPhoto2Error("file not found: %s/%s" % (folder, name))
        return h

    @_wrap
    def folder_list_folders(self, folder):
        self._ensure_index()
        return CameraList(self._index.children(folder, True))

    @_wrap
    def folder_list_files(self, folder):
        self._ensure_index()
        return CameraList(self._index.children(folder, False))

    @_wrap
    def file_get_info(self, folder, name):
        v = self._index.objects[self._handle(folder, name)]
        return _Info(file=_Info(size=v[3], mtime=v[4]))

    @_wrap
    def file_get(self, folder, name, kind):
        h = self._handle(folder, name)
        cam = self._cam()
        return CameraFile(cam.get_thumb(h) if kind == GP_FILE_TYPE_PREVIEW else cam.get_object(h))

    @_wrap
    def file_read(self, folder, name, kind, offset, buf):
        if kind != GP_FILE_TYPE_NORMAL:
            raise GPhoto2Error("partial read only for files", GP_ERROR_NOT_SUPPORTED)
        try:
            data = self._cam().get_partial(self._handle(folder, name), offset, len(buf))
        except ptp.PtpError as e:
            if e.code == 0x2005:  # OperationNotSupported: the caller reads the whole file
                raise GPhoto2Error("partial read not supported", GP_ERROR_NOT_SUPPORTED)
            raise
        buf[:len(data)] = data
        return len(data)
