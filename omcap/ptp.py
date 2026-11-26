"""Own PTP layer over USB (libusb via ctypes) for the E-M1 Mark I, as a faster replacement for libgphoto2.

Why: libgphoto2 reads every file one by one at connect (51–72 s for 2900 files), waits 0.3 s per idle
event check and forces the live view to 1024x768. The camera itself lists all object handles in 0.01 s
and answers GetObjectInfo in 10 ms (measured 2026-11-13, out/research/usb_performance.md).

This module only speaks PTP: transactions, datasets and the Olympus OM-D operations. It knows nothing
about the app. The sequences follow libgphoto2 (camlibs/ptp2, master 2026-11-12): PC mode via d052
(write 1, then poll the property until it reads 1), live view 0x9484 with param 1 and short retries
while the camera is busy, shutter 0x9481 with steps 1/3/6.
"""
import ctypes
import ctypes.util
import glob
import os
import struct
import subprocess
import time

# Container types and response codes (PTP 1.0)
CMD, DATA, RESP, EVENT = 1, 2, 3, 4
RC_OK, RC_BUSY, RC_SESSION_OPEN = 0x2001, 0x2019, 0x201E

OLYMPUS_VID = 0x07B4
KNOWN_PIDS = (0x0130,)  # E-M1 Mark I; other OM-D bodies to be added when tested

# Data type codes (PTP) -> struct format
DTYPES = {1: "b", 2: "B", 3: "h", 4: "H", 5: "i", 6: "I", 7: "q", 8: "Q"}
DT_STRING = 0xFFFF

OP_GET_DEVICE_INFO, OP_OPEN, OP_CLOSE = 0x1001, 0x1002, 0x1003
OP_STORAGE_IDS, OP_STORAGE_INFO, OP_HANDLES, OP_OBJECT_INFO = 0x1004, 0x1005, 0x1007, 0x1008
OP_GET_OBJECT, OP_GET_THUMB, OP_GET_PARTIAL = 0x1009, 0x100A, 0x101B
OP_DELETE_OBJECT = 0x100B
OP_PROP_DESC, OP_GET_PROP, OP_SET_PROP = 0x1014, 0x1015, 0x1016
DPC_LV_SIZE, LV_SIZE_DEFAULT = 0xD06D, 0x04000300  # live view size (w << 16 | h); 0 = live view off
OP_SHUTTER, OP_LIVEVIEW = 0x9481, 0x9484
# Direct store (no card): the camera keeps the shot in memory and hands it over in pieces (traced from OM Capture,
# out/research/omcapture_trace_codes.md "Round B"): 0x9495 gives the info of the next file, 0x9493 reads it.
OP_DS_INFO, OP_DS_PART = 0x9495, 0x9493
DS_CHUNK = 0x200000  # piece size OM Capture used
OP_GET_IMAGE = 0x9485  # OMD_GetImage: JPEG of the shot just taken, before the card lists it (traced from OM Capture)
DPC_CONTROL_MODE = 0xD052  # 1 = PC control, 2 = camera
DPC_MODE = 0xD006  # shooting mode (mode dial)
# Change poll (traced from OM Capture, round_c 2026-11-22): 0x9489 SetProperties chooses a list of properties
# (UINT32 count, UINT16 codes), then 0x9486 ChangedProperties returns their current descriptors (UINT32 count,
# DevicePropDescs back to back) - also after a mode dial turn, which 0x1014 only shows in a new session.
# OM Capture polls it every 0.6 s (~26 ms each). Without 0x9489 the E-M1 returns only d052.
OP_SET_POLL_LIST, OP_CHANGED_PROPS = 0x9489, 0x9486

# Zoom frame AF / Zoom AF (the camera's own magnified live view, E-M1 manual p.56), from OM Capture traces
# and confirmed on the camera 2026-11-16 (out/research/loupe_protocol.md): d0cf = ratio, 0x9483 = point
# as ONE packed parameter (y << 16 | x) in the 1024x768 live view grid, d04b = on (1) / off (2),
# 0x9488 = move the frame one step. A magnified view can outlive a session: write d04b = 2 at start and stop.
# The app sends them through the gphoto2-style widgets ("d04b", "opcode"), so both USB backends can.
DPC_LOUPE, LOUPE_ON, LOUPE_OFF = 0xD04B, 1, 2
DPC_LOUPE_RATIO = 0xD0CF
LOUPE_RATIOS = {1: 3, 2: 5, 3: 7, 4: 10, 5: 14}  # d0cf value -> magnification
OP_LOUPE_POINT, OP_LOUPE_MOVE = 0x9483, 0x9488
LOUPE_MOVES = {"up": 1, "down": 2, "left": 3, "right": 4}
LOUPE_GRID = (1024, 768)  # default grid of the 0x9483 point (live view size 1024x768)
# Measured on the E-M1 2026-11-16 (live view 1024x768, crop matched against the normal frame, x3/x5/x10/x14): the crop
# is 1/ratio of the picture, y lands where it was sent, but x lands 1.135x as far from the centre as sent (sent 0.30
# -> 0.2705, 0.70 -> 0.725; centre exact). The camera also keeps the crop inside the middle 80 % of the picture.
LOUPE_X_GAIN = 1.135


def loupe_grid(lvqty):
    """The grid the camera reads the 0x9483 point in: that of the current live view size ("1280x0960" -> 1280x960),
    1024x768 when unknown. Measured 2026-11-18 at 1280x960 (crop landed at p/1280 and p/960) and at 1024x768;
    320x240, 640x480 and 800x600 are assumed to follow the same rule (not measured)."""
    try:
        w, h = (int(v) for v in lvqty.split("x"))
        return (w, h) if w > 0 and h > 0 else LOUPE_GRID
    except (AttributeError, ValueError):
        return LOUPE_GRID


def loupe_point(x, y, grid=LOUPE_GRID):
    """The one 0x9483 parameter for a point in the given grid (default 1024x768), clamped to it (centre = 0x01800200)."""
    w, h = grid
    x, y = min(max(int(round(x)), 0), w - 1), min(max(int(round(y)), 0), h - 1)
    return (y << 16) | x



class PtpError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


# --- Datasets -------------------------------------------------------------------------------------
def read_string(buf, off):
    """PTP string: u8 number of UTF-16 chars incl. the terminating 0. Returns (text, new offset)."""
    n = buf[off]
    off += 1
    text = buf[off:off + 2 * n].decode("utf-16-le", "replace").rstrip("\x00")
    return text, off + 2 * n


def read_value(buf, off, dtype):
    if dtype == DT_STRING:
        return read_string(buf, off)
    fmt = "<" + DTYPES[dtype]
    return struct.unpack_from(fmt, buf, off)[0], off + struct.calcsize(fmt)


def read_array(buf, off, fmt):
    """u32 count followed by values (fmt one struct char)."""
    n = struct.unpack_from("<I", buf, off)[0]
    off += 4
    size = struct.calcsize("<" + fmt)
    return list(struct.unpack_from("<%d%s" % (n, fmt), buf, off)), off + n * size


def parse_device_info(buf):
    off = 8  # StandardVersion u16, VendorExtensionID u32, VendorExtensionVersion u16
    _, off = read_string(buf, off)  # VendorExtensionDesc
    off += 2  # FunctionalMode
    ops, off = read_array(buf, off, "H")
    events, off = read_array(buf, off, "H")
    props, off = read_array(buf, off, "H")
    _, off = read_array(buf, off, "H")  # capture formats
    _, off = read_array(buf, off, "H")  # image formats
    manufacturer, off = read_string(buf, off)
    model, off = read_string(buf, off)
    version, off = read_string(buf, off)
    return {"operations": ops, "events": events, "properties": props,
            "manufacturer": manufacturer, "model": model, "version": version}


def parse_object_info(buf):
    (storage, fmt, _prot, size, _tf, _ts, _tw, _th, width, height, _depth, parent, assoc, _ad,
     _seq) = struct.unpack_from("<IHHIHIIIIIIIHII", buf, 0)
    off = struct.calcsize("<IHHIHIIIIIIIHII")
    name, off = read_string(buf, off)
    captured, off = read_string(buf, off)
    modified, off = read_string(buf, off)
    return {"storage": storage, "format": fmt, "size": size, "width": width, "height": height,
            "parent": parent, "folder": assoc == 1 or fmt == 0x3001, "name": name,
            "captured": captured, "modified": modified}


def parse_prop_desc(buf):
    return _prop_desc_at(buf, 0)[0]


def parse_prop_descs(buf):
    """0x9486 answer: UINT32 count, then DevicePropDescs back to back -> {code: descriptor}."""
    n = struct.unpack_from("<I", buf, 0)[0]
    off, out = 4, {}
    for _ in range(n):
        desc, off = _prop_desc_at(buf, off)
        out[desc["code"]] = desc
    return out


def _prop_desc_at(buf, off):
    """One DevicePropDesc starting at `off`: (descriptor, offset after it)."""
    code, dtype, getset = struct.unpack_from("<HHB", buf, off)
    off += 5
    default, off = read_value(buf, off, dtype)
    current, off = read_value(buf, off, dtype)
    form = buf[off] if off < len(buf) else 0
    off += 1
    out = {"code": code, "type": dtype, "writable": bool(getset), "default": default, "value": current}
    if form == 1:  # range
        lo, off = read_value(buf, off, dtype)
        hi, off = read_value(buf, off, dtype)
        step, off = read_value(buf, off, dtype)
        out["range"] = (lo, hi, step)
    elif form == 2:  # enumeration
        n = struct.unpack_from("<H", buf, off)[0]
        off += 2
        values = []
        for _ in range(n):
            v, off = read_value(buf, off, dtype)
            values.append(v)
        out["enum"] = values
    return out, off


def pack_value(value, dtype):
    if dtype == DT_STRING:
        text = str(value) + "\x00"
        return bytes([len(text)]) + text.encode("utf-16-le")
    return struct.pack("<" + DTYPES[dtype], value)


# --- USB transport ---------------------------------------------------------------------------------
class _Timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long)]


_TRANSFER_CB = ctypes.CFUNCTYPE(None, ctypes.c_void_p)


class _Transfer(ctypes.Structure):
    """struct libusb_transfer (without the iso packet descriptors)."""
    _fields_ = [("dev_handle", ctypes.c_void_p), ("flags", ctypes.c_uint8), ("endpoint", ctypes.c_ubyte),
                ("type", ctypes.c_ubyte), ("timeout", ctypes.c_uint), ("status", ctypes.c_int),
                ("length", ctypes.c_int), ("actual_length", ctypes.c_int), ("callback", _TRANSFER_CB),
                ("user_data", ctypes.c_void_p), ("buffer", ctypes.c_void_p), ("num_iso_packets", ctypes.c_int)]


def parse_event(raw):
    """Interrupt container: length u32, type u16, code u16, transaction u32, then u32 params."""
    if len(raw) < 12:
        return None
    _, _, code, _ = struct.unpack_from("<IHHI", raw)
    return code, struct.unpack_from("<%dI" % ((len(raw) - 12) // 4), raw, 12)


def _libusb():
    """libusb-1.0: the copy bundled with python-gphoto2, else Homebrew or the system."""
    candidates = []
    try:
        import gphoto2
        candidates += glob.glob(os.path.join(os.path.dirname(gphoto2.__file__), ".dylibs", "libusb-1.0*.dylib"))
    except ImportError:
        pass
    candidates += ["/opt/homebrew/lib/libusb-1.0.dylib", "/usr/local/lib/libusb-1.0.dylib"]
    found = ctypes.util.find_library("usb-1.0")
    if found:
        candidates.append(found)
    for path in candidates:
        if path and (os.path.exists(path) or not os.path.isabs(path)):
            try:
                lib = ctypes.CDLL(path)
                break
            except OSError:
                continue
    else:
        raise PtpError("libusb not found")
    vp, cint, cu8, cu16 = ctypes.c_void_p, ctypes.c_int, ctypes.c_uint8, ctypes.c_uint16
    lib.libusb_open_device_with_vid_pid.restype = vp
    lib.libusb_open_device_with_vid_pid.argtypes = [vp, cu16, cu16]
    for f in ("libusb_claim_interface", "libusb_release_interface"):
        getattr(lib, f).argtypes = [vp, cint]
    lib.libusb_bulk_transfer.argtypes = [vp, ctypes.c_ubyte, vp, cint, ctypes.POINTER(cint), ctypes.c_uint]
    lib.libusb_interrupt_transfer.argtypes = lib.libusb_bulk_transfer.argtypes
    lib.libusb_control_transfer.argtypes = [vp, cu8, cu8, cu16, cu16, vp, cu16, ctypes.c_uint]
    lib.libusb_close.argtypes = [vp]
    lib.libusb_exit.argtypes = [vp]
    lib.libusb_alloc_transfer.restype = ctypes.POINTER(_Transfer)
    lib.libusb_alloc_transfer.argtypes = [cint]
    for f in ("libusb_submit_transfer", "libusb_cancel_transfer", "libusb_free_transfer"):
        getattr(lib, f).argtypes = [ctypes.POINTER(_Transfer)]
    lib.libusb_handle_events_timeout_completed.argtypes = [vp, ctypes.POINTER(_Timeval), ctypes.POINTER(cint)]
    return lib


# Transports whose interrupt transfer libusb still owns after close() (camera unplugged: the cancel never
# completes). They stay referenced for the whole run: freeing their buffer and callback while libusb can still
# write into them crashed the server with a segmentation fault (camera test 2026-11-15, cable pulled and plugged in).
_LEAKED = []  # grows by one small transport per such unplug; acceptable for a desktop session


class UsbTransport:
    """Bulk in/out and interrupt endpoint of the camera's still image interface."""

    def __init__(self, pids=KNOWN_PIDS, tries=10):
        self.lib = _libusb()
        self.ctx = ctypes.c_void_p()
        self.lib.libusb_init(ctypes.byref(self.ctx))
        self.h = None
        self._buf = None
        self._events, self._irq, self._irq_live = [], None, False
        for _ in range(tries):
            # macOS: the ptpcamerad service claims the camera as soon as it is plugged in
            subprocess.run(["killall", "-9", "ptpcamerad"], capture_output=True)
            for pid in pids:
                h = self.lib.libusb_open_device_with_vid_pid(self.ctx, OLYMPUS_VID, pid)
                if h and self.lib.libusb_claim_interface(h, 0) == 0:
                    self.h = h
                    break
                if h:
                    self.lib.libusb_close(h)
            if self.h:
                break
            time.sleep(0.5)
        if not self.h:
            self.close()
            raise PtpError("USB camera not reachable")
        self.ep_in, self.ep_out, self.ep_int = self._endpoints()
        self._start_events()

    # Events: on macOS a synchronous interrupt read shorter than ~150 ms never returns an event (measured
    # 2026-11-13: 10/20/50 ms nothing, 150 ms both AF events), and each check would cost that long. So one
    # asynchronous interrupt transfer stays submitted, like libgphoto2's libusb1 port does; it completes
    # while any other transfer runs (libusb handles events then) or in read_event().
    def _start_events(self):
        if self.ep_int is None:
            return
        self._irq_buf = ctypes.create_string_buffer(64)
        self._irq_cb = _TRANSFER_CB(self._on_irq)  # keep a reference: libusb calls it later
        tr = self.lib.libusb_alloc_transfer(0)
        if not tr:
            return
        tr.contents.dev_handle, tr.contents.endpoint, tr.contents.type = self.h, self.ep_int, 3  # interrupt
        tr.contents.timeout, tr.contents.length = 0, 64
        tr.contents.callback = self._irq_cb
        tr.contents.buffer = ctypes.cast(self._irq_buf, ctypes.c_void_p)
        self._irq, self._irq_live = tr, False
        self._submit_irq()

    def _submit_irq(self):
        self._irq_live = self.lib.libusb_submit_transfer(self._irq) == 0

    def _on_irq(self, _ptr):
        if self._irq is None:  # late callback after close()
            self._irq_live = False
            return
        t = self._irq.contents
        self._irq_live = False
        if t.status == 0:  # LIBUSB_TRANSFER_COMPLETED
            ev = parse_event(ctypes.string_at(self._irq_buf, t.actual_length))
            if ev:
                self._events.append(ev)
        if t.status in (0, 2) and self.h:  # completed or timed out: keep listening (not after an error)
            self._submit_irq()

    def _pump(self, timeout_ms):
        tv = _Timeval(timeout_ms // 1000, (timeout_ms % 1000) * 1000)
        self.lib.libusb_handle_events_timeout_completed(self.ctx, ctypes.byref(tv), None)

    def _endpoints(self):
        buf = (ctypes.c_ubyte * 512)()
        n = self.lib.libusb_control_transfer(self.h, 0x80, 6, 0x0200, 0, buf, 512, 1000)
        desc, i, eps = bytes(buf[:max(n, 0)]), 0, {}
        while i + 1 < len(desc):
            ln, typ = desc[i], desc[i + 1]
            if typ == 5:
                addr, attr = desc[i + 2], desc[i + 3] & 3
                eps[(attr, bool(addr & 0x80))] = addr
            i += ln or 1
        return eps.get((2, True)), eps.get((2, False)), eps.get((3, True))

    def write(self, data, timeout=5000):
        got = ctypes.c_int()
        b = ctypes.create_string_buffer(bytes(data), len(data))
        r = self.lib.libusb_bulk_transfer(self.h, self.ep_out, b, len(data), ctypes.byref(got), timeout)
        if r != 0:
            raise PtpError("USB write failed (%d)" % r)

    def read(self, size=1 << 20, timeout=5000):
        # one buffer for all reads: a new 1 MB buffer per read (and copying all of it) cost ~20 ms
        if self._buf is None or len(self._buf) < size:
            self._buf = ctypes.create_string_buffer(size)
        got = ctypes.c_int()
        r = self.lib.libusb_bulk_transfer(self.h, self.ep_in, self._buf, size, ctypes.byref(got), timeout)
        if r != 0 and not (r == -7 and got.value > 0):  # a timeout after some bytes: keep them
            raise PtpError("USB read failed (%d)" % r, code=r)
        return ctypes.string_at(self._buf, got.value)

    def read_event(self, timeout=10):
        """Next event (code, params) or None after `timeout` ms."""
        self.poll_events(timeout)
        return self._events.pop(0) if self._events else None

    def poll_events(self, timeout=10):
        """Collect pending events into the queue (without taking one)."""
        if self._irq is not None and not self._irq_live and self.h:
            self._submit_irq()  # after a transfer error: listen again
        if not self._events and self._irq is not None and self._irq_live:
            end = time.monotonic() + timeout / 1000.0
            while not self._events:
                left = int((end - time.monotonic()) * 1000)
                if left <= 0:
                    break
                self._pump(left)
        elif not self._events:  # no async transfer: synchronous read (>= 150 ms on macOS)
            got = ctypes.c_int()
            b = ctypes.create_string_buffer(64)
            if self.lib.libusb_interrupt_transfer(self.h, self.ep_int, b, 64, ctypes.byref(got), timeout) == 0:
                ev = parse_event(b.raw[:got.value])
                if ev:
                    self._events.append(ev)

    def close(self):
        if self._irq is not None:
            h, self.h = self.h, None  # the callback must not resubmit
            if self._irq_live:
                self.lib.libusb_cancel_transfer(self._irq)
                end = time.monotonic() + 1.0
                while self._irq_live and time.monotonic() < end:
                    self._pump(50)
            if not self._irq_live:  # never free a transfer libusb still owns
                self.lib.libusb_free_transfer(self._irq)
            if self._irq_live:
                self._leaked = True  # libusb still owns the transfer: do not tear libusb down under it
                _LEAKED.append(self)  # and keep its buffer and callback alive
            self._irq, self.h = None, h
        if self.h and not getattr(self, "_leaked", False):  # never close a handle with a transfer still pending
            self.lib.libusb_release_interface(self.h, 0)
            self.lib.libusb_close(self.h)
        self.h = None
        if self.ctx.value and not getattr(self, "_leaked", False):
            self.lib.libusb_exit(self.ctx)
            self.ctx = ctypes.c_void_p()


DS_KINDS = {2: ".ORF", 5: ".JPG"}


def parse_ds_info(buf):
    """Answer of 0x9495, 20 bytes (traced 2026-11-16, ORF and JPG), all little endian:

    0..3  u32 kind: 2 = ORF, 5 = JPG
    4..7  extension reversed ("FRO." = ".ORF", "GPJ." = ".JPG")
    8..11 u32 size in bytes (ORF 0x00ED4268, JPG 0x002C474B)
    12..15 zero
    16..19 u32 id for 0x9493 (0x7F02 in both answers)
    Returns None for an empty or all-zero answer (no file waiting).
    """
    if not buf or len(buf) < 20:
        return None
    kind, ext, size, _zero, ident = struct.unpack_from("<I4sIII", buf, 0)
    if not size:
        return None
    ext = ext[::-1].decode("ascii", "replace").upper()
    if not ext.startswith(".") or not ext[1:].isalnum():
        ext = DS_KINDS.get(kind, ".BIN")
    return {"kind": kind, "ext": ext, "size": size, "id": ident}


# --- PTP session -----------------------------------------------------------------------------------
class PtpCamera:
    """One PTP session. All calls are blocking; the caller serialises them (one at a time)."""

    def __init__(self, transport):
        self.t = transport
        self.tid = 0

    def transact(self, code, params=(), data=None, want_data=False, timeout=5000):
        """Returns (data or None, response params). Raises PtpError on a response other than OK."""
        self.tid += 1
        tid = self.tid
        self.t.write(struct.pack("<IHHI%dI" % len(params), 12 + 4 * len(params), CMD, code, tid, *params))
        if data is not None:
            self.t.write(struct.pack("<IHHI", 12 + len(data), DATA, code, tid) + bytes(data))
        payload = None
        deadline = time.monotonic() + timeout / 1000
        while True:
            # Read in short slices and keep the event pipe empty meanwhile: libgphoto2 polls the
            # interrupt endpoint all the time; the camera may hold its answer until its event is taken
            try:
                pkt = self.t.read(timeout=200)
            except PtpError as e:
                if e.code != -7 or time.monotonic() > deadline:  # -7 = LIBUSB_ERROR_TIMEOUT
                    raise
                self.t.poll_events(10)  # without the async transfer: take the event the camera may wait on
                continue
            if len(pkt) < 12:
                continue
            length, typ, rc, ptid = struct.unpack_from("<IHHI", pkt)
            if ptid != tid:
                continue  # stale packet from an earlier, aborted transaction
            if typ == DATA:
                body = bytearray(pkt[12:])
                while len(body) < length - 12:
                    body += self.t.read(timeout=timeout)
                payload = bytes(body[:length - 12])
            elif typ == RESP:
                if rc != RC_OK:
                    raise PtpError("PTP 0x%04x answered 0x%04x" % (code, rc), code=rc)
                n = (length - 12) // 4
                return payload, struct.unpack_from("<%dI" % n, pkt, 12) if n else ()

    def get_image(self, wait=1.2):
        """JPEG of the last shot (0x9485, param 1), or b"" when the camera has none (RAW only, no card, not ready).

        The camera answers busy or empty for a moment after the release (camera test 2026-11-21: the JPEG came
        0.9 s after the release; a 0.3 s window never got it), so retry for `wait` seconds.
        Never raises for a camera answer: the caller falls back to the card.
        """
        end = time.monotonic() + wait
        while True:
            try:
                data = self._retry_busy(OP_GET_IMAGE, (1,), True, 0, timeout=1500)
                if data and data[:2] == b"\xff\xd8":
                    return data
            except PtpError as e:
                if e.code not in (RC_BUSY, None) and e.code > 0:
                    return b""  # a real refusal (not supported, no object): no retry
            if time.monotonic() >= end:
                return b""
            time.sleep(0.1)

    def _retry_busy(self, code, params, want_data, wait, timeout=5000):
        """transact() that retries a busy answer for `wait` seconds."""
        end = time.monotonic() + wait
        while True:
            try:
                return self.transact(code, params, want_data=want_data, timeout=timeout)[0]
            except PtpError as e:
                if e.code != RC_BUSY or time.monotonic() >= end:
                    raise
            time.sleep(0.05)

    def direct_store_info(self, wait=1.0):
        """Info of the next picture the camera offers without a card (0x9495, no parameters), or None when none.

        Dict kind (2 = ORF, 5 = JPG), ext (".ORF"/".JPG"), size, id. Raises PtpError on a refusal.
        """
        return parse_ds_info(self._retry_busy(OP_DS_INFO, (), True, wait))

    def direct_store_read(self, id, size, chunk=DS_CHUNK, wait=2.0):
        """Yield the file in pieces of `chunk` bytes (0x9493 id, offset, length, clear).

        Exactly as OM Capture: clear = 0 on every piece but the last, clear = 1 on the last one of each file
        (it lets the camera drop its copy). Raises PtpError on a refusal or a short piece.
        """
        offset = 0
        while offset < size:
            length = min(chunk, size - offset)
            last = 1 if offset + length >= size else 0
            data = self._retry_busy(OP_DS_PART, (id, offset, length, last), True, wait, timeout=15000)
            if not data or len(data) != length:
                raise PtpError("direct store piece at %d: %d of %d bytes" % (offset, len(data or b""), length))
            yield data
            offset += length

    def drain(self):
        """Throw away data left in the pipe by an earlier program or aborted transaction."""
        while True:
            try:
                self.t.read(timeout=200)
            except PtpError:
                break
        while self.t.read_event(50):
            pass

    def open(self):
        self.drain()
        self._lv_checked = False  # a new session may start with live view off (d06d = 0)
        try:
            self.transact(OP_OPEN, (1,))
        except PtpError as e:
            if e.code != RC_SESSION_OPEN:
                raise

    def close(self):
        try:
            self.transact(OP_CLOSE)
        finally:
            self.t.close()

    # Information and files
    def device_info(self):
        return parse_device_info(self.transact(OP_GET_DEVICE_INFO, want_data=True)[0])

    def storage_ids(self):
        return read_array(self.transact(OP_STORAGE_IDS, want_data=True)[0], 0, "I")[0]

    def storage_info(self, storage):
        """Capacity and free space in bytes (GetStorageInfo 0x1005)."""
        buf = self.transact(OP_STORAGE_INFO, (storage,), want_data=True)[0]
        _type, _fs, _access, capacity, free, _images = struct.unpack_from("<HHHQQI", buf, 0)
        return {"capacity": capacity, "free": free}

    def handles(self, storage=0xFFFFFFFF, parent=0):
        return read_array(self.transact(OP_HANDLES, (storage, 0, parent), want_data=True)[0], 0, "I")[0]

    def object_info(self, handle):
        return parse_object_info(self.transact(OP_OBJECT_INFO, (handle,), want_data=True)[0])

    def get_object(self, handle, timeout=30000):
        return self.transact(OP_GET_OBJECT, (handle,), want_data=True, timeout=timeout)[0]

    def get_partial(self, handle, offset, size):
        return self.transact(OP_GET_PARTIAL, (handle, offset, size), want_data=True)[0]

    def delete_object(self, handle):
        """DeleteObject 0x100B (the camera refuses protected pictures with an error response)."""
        self.transact(OP_DELETE_OBJECT, (handle,))

    def get_thumb(self, handle):
        return self.transact(OP_GET_THUMB, (handle,), want_data=True)[0]

    # Properties
    def prop_desc(self, code):
        return parse_prop_desc(self.transact(OP_PROP_DESC, (code,), want_data=True)[0])

    def prop_value(self, code, dtype):
        """Current value (GetDevicePropValue 0x1015). Unlike the descriptor, it follows the camera
        live under PC control (E-M1: tilt d053/d055, camera-tested 2026-11-14)."""
        return read_value(self.transact(OP_GET_PROP, (code,), want_data=True)[0], 0, dtype)[0]

    def set_prop(self, code, value, dtype, timeout=5000):
        self.transact(OP_SET_PROP, (code,), data=pack_value(value, dtype), timeout=timeout)

    def set_poll_list(self, codes):
        """0x9489: the properties 0x9486 reports (sends a list, changes no setting)."""
        self.transact(OP_SET_POLL_LIST, data=struct.pack("<I%dH" % len(codes), len(codes), *codes))

    def changed_props(self):
        """0x9486: current descriptors of the poll list, {code: descriptor}."""
        return parse_prop_descs(self.transact(OP_CHANGED_PROPS, want_data=True)[0] or b"\0\0\0\0")

    def pc_mode(self, on=True, wait=5.0):
        """Camera control mode d052: 1 = PC control (needed for live view and shooting), 2 = camera.
        Like libgphoto2: write, then poll the property until it reads the new value."""
        want = 1 if on else 2
        # libgphoto2 waits up to 20 s (its port timeout) for this answer; the E-M1 needs longer than 5 s
        t0 = time.monotonic()
        while True:
            try:
                self.set_prop(DPC_CONTROL_MODE, want, 4, timeout=20000)
                break
            except PtpError as e:
                # a camera just switched on (or after an earlier session) answers "busy" for a few seconds: OM Capture
                # got DeviceBusy once and succeeded on the retry (trace 2026-11-16); without this the app fell back to libgphoto2
                if e.code != RC_BUSY or time.monotonic() - t0 > 8:
                    raise
                time.sleep(0.5)
        self.pc_answer_s = time.monotonic() - t0  # how long the camera took to answer (connect log)
        end = time.monotonic() + wait
        while time.monotonic() < end:
            try:
                if self.prop_desc(DPC_CONTROL_MODE)["value"] == want:
                    return True
            except PtpError as e:
                if e.code != RC_BUSY:
                    raise
            time.sleep(0.1)
        return False

    # Olympus OM-D
    def liveview_on(self):
        """The live view size d06d doubles as the live view switch: at 0 the camera answers 0x9484 with
        0 bytes (seen 2026-11-13 after switching the camera off and on). Like libgphoto2, set 1024x768 then;
        a size chosen in the app stays. Checked once per session."""
        if getattr(self, "_lv_checked", False):
            return
        # writes only after the app checked the write permission (UsbCamera.start_liveview starts the loop)
        desc = self.prop_desc(DPC_LV_SIZE)
        if not desc["value"]:
            self.set_prop(DPC_LV_SIZE, LV_SIZE_DEFAULT, desc["type"])
        self._lv_checked = True

    def liveview_frame(self, wait=1.0):
        """One JPEG from the live view (0x9484, param 1); retries while the camera is busy, up to `wait` s
        (libgphoto2: 25 x 40 ms). The app rebuilds the session after 10 failed frames, so a shorter wait
        would end long exposures (BULB, LIVE TIME, LIVECOMP) after about a second (seen 2026-11-13)."""
        end = time.monotonic() + wait
        self.liveview_on()
        while True:
            try:
                data = self.transact(OP_LIVEVIEW, (1,), want_data=True)[0]
                self.lv_reason = "answer of %d bytes, no JPEG" % len(data or b"")
            except PtpError as e:
                if e.code != RC_BUSY:
                    self.lv_reason = str(e)
                    raise
                data, self.lv_reason = None, "camera busy"
            if data and len(data) >= 1024 and data[:2] == b"\xff\xd8":
                return data
            if time.monotonic() > end:
                return None
            time.sleep(0.005)

    def shutter(self, step):
        """0x9481: 1 half press, 3 press all the way, 6 release (tested on the E-M1)."""
        self.transact(OP_SHUTTER, (step,))

    def event(self, timeout=10):
        return self.t.read_event(timeout)
