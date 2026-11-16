"""Capture backends: each turns a recording into a list of Transfer objects.

- hook:  JSON lines written by hook/usbsniff_hook.dylib (PTP through ImageCaptureCore)
- pcap:  classic pcap or pcapng with USBPcap (Windows) or usbmon (Linux) link types
"""
import json
import struct

from .model import IN, OUT, Transfer

PTP_DATA = 2


def _hex(s):
    return bytes.fromhex(s) if s else b""


def _as_container(payload, full_len, ctype, code, tid):
    """ImageCaptureCore hands data phases without the 12-byte header; add one so all
    backends feed the decoders the same container stream. Already wrapped data is kept."""
    if len(payload) >= 12:
        ln, ty = struct.unpack_from("<IH", payload)
        if ty == ctype and ln == full_len:
            return payload, full_len
    head = struct.pack("<IHHI", full_len + 12, ctype, code, tid)
    return head + payload, full_len + 12


def _set_tid(container, tid):
    return container[:8] + struct.pack("<I", tid) + container[12:] if len(container) >= 12 else container


def read_hook(path):
    """Read a hook log. Returns transfers in time order (commands, data, responses, events).

    ImageCaptureCore takes commands with transaction id 0 and ptpcamerad puts in its own id, so the
    response carries another id than the command. The hook pairs both by its own sequence number;
    here every container of one transaction gets that sequence number as its id."""
    out, pending = [], {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            kind, t, dev = r.get("kind"), float(r.get("t", 0)), "pid%s" % r.get("pid", "")
            if kind == "cmd":
                tid = r["seq"]
                cmd = _set_tid(_hex(r.get("cmd")), tid)
                code = struct.unpack_from("<H", cmd, 6)[0] if len(cmd) >= 12 else 0
                pending[r["seq"]] = (code, tid)
                out.append(Transfer(t, OUT, "ptp-cmd", cmd, length=r.get("cmd_len"), device=dev))
                if "out" in r:
                    d, ln = _as_container(_hex(r["out"]), r.get("out_len", 0), PTP_DATA, code, tid)
                    out.append(Transfer(t, OUT, "ptp-data", d, length=ln, device=dev))
            elif kind == "resp":
                code, tid = pending.pop(r.get("seq"), (0, 0))
                status = "error: " + r["err"] if r.get("err") else "ok"
                if r.get("in_len"):
                    d, ln = _as_container(_hex(r.get("in")), r["in_len"], PTP_DATA, code, tid)
                    out.append(Transfer(t, IN, "ptp-data", d, length=ln, device=dev))
                out.append(Transfer(t, IN, "ptp-resp", _set_tid(_hex(r.get("resp")), tid), status=status,
                                    length=r.get("resp_len"), device=dev))
            elif kind == "event":
                out.append(Transfer(t, IN, "ptp-event", _hex(r.get("event")), kind="interrupt",
                                    length=r.get("event_len"), device=dev))
    return out


# ---- pcap / pcapng ---------------------------------------------------------------------------
LT_USB_LINUX, LT_USB_LINUX_MMAPPED, LT_USBPCAP = 189, 220, 249
XFER = {0: "iso", 1: "interrupt", 2: "control", 3: "bulk"}


def _iter_pcap(raw):
    """Yield (linktype, ts, packet) from classic pcap or pcapng bytes."""
    magic = raw[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4", b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d"):
        e = "<" if magic[0] in (0xD4, 0x4D) else ">"
        nano = magic in (b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d")
        lt = struct.unpack_from(e + "I", raw, 20)[0]
        pos = 24
        while pos + 16 <= len(raw):
            sec, frac, incl, _ = struct.unpack_from(e + "IIII", raw, pos)
            pos += 16
            yield lt, sec + frac / (1e9 if nano else 1e6), raw[pos:pos + incl]
            pos += incl
        return
    if magic != b"\x0a\x0d\x0d\x0a":
        raise ValueError("not a pcap or pcapng file")
    e, pos, ifaces = "<", 0, []
    while pos + 12 <= len(raw):
        btype = struct.unpack_from("<I", raw, pos)[0]
        if btype == 0x0A0D0D0A:
            e = "<" if raw[pos + 8:pos + 12] == b"\x4d\x3c\x2b\x1a" else ">"
            ifaces = []
        btype, blen = struct.unpack_from(e + "II", raw, pos)
        body = raw[pos + 8:pos + blen - 4]
        if btype == 1:      # interface description: link type and time resolution (option 9)
            lt, scale, opos = struct.unpack_from(e + "H", body)[0], 1e6, 8
            while opos + 4 <= len(body):
                code, olen = struct.unpack_from(e + "HH", body, opos)
                if code == 0:
                    break
                if code == 9 and olen >= 1:
                    v = body[opos + 4]
                    scale = float(2 ** (v & 0x7F)) if v & 0x80 else 10.0 ** v
                opos += 4 + olen + (-olen % 4)
            ifaces.append((lt, scale))
        elif btype == 6:    # enhanced packet
            iface, hi, lo, cap, _ = struct.unpack_from(e + "IIIII", body)
            lt, scale = ifaces[iface]
            yield lt, ((hi << 32) | lo) / scale, body[20:20 + cap]
        elif btype == 3:    # simple packet
            yield ifaces[0][0], 0.0, body[4:]
        pos += blen


def _usbpcap(ts, pkt):
    hlen, _irp, status, _fn, info, bus, dev, ep, xfer, dlen = struct.unpack_from("<HQIHBHHBBI", pkt)
    data = pkt[hlen:hlen + dlen]  # may be shorter than dlen (snap length or a truncated recording)
    if not data or xfer not in (1, 3):
        return None
    d_in = bool(ep & 0x80)
    if bool(info & 1) != d_in:  # OUT data rides on the request, IN data on the completion
        return None
    return Transfer(ts, IN if d_in else OUT, "0x%02x" % ep, data, "ok" if status == 0 else "0x%x" % status,
                    length=max(dlen, len(data)), kind=XFER[xfer], device="%d:%d" % (bus, dev))


def _usbmon(ts, pkt, hlen):
    _id, etype, xfer, ep, dev, bus = struct.unpack_from("<QcBBBH", pkt)
    status, length, cap = struct.unpack_from("<iII", pkt, 28)
    data = pkt[hlen:hlen + cap]
    d_in = bool(ep & 0x80)
    if not data or xfer not in (1, 3) or (etype == b"C") != d_in:
        return None
    return Transfer(ts, IN if d_in else OUT, "0x%02x" % ep, data, "ok" if status in (0, -115) else str(status),
                    length=length, kind=XFER[xfer], device="%d:%d" % (bus, dev))


def read_pcap(path, device=None):
    with open(path, "rb") as f:
        raw = f.read()
    out = []
    for lt, ts, pkt in _iter_pcap(raw):
        if lt == LT_USBPCAP:
            t = _usbpcap(ts, pkt)
        elif lt in (LT_USB_LINUX, LT_USB_LINUX_MMAPPED):
            t = _usbmon(ts, pkt, 48 if lt == LT_USB_LINUX else 64)
        else:
            raise ValueError("unsupported link type %d (need USBPcap or usbmon)" % lt)
        if t and (device is None or t.device == device):
            out.append(t)
    return out


def load(path, device=None):
    """Pick the backend by file content."""
    with open(path, "rb") as f:
        head = f.read(4)
    if head[:1] == b"{":
        return "hook", read_hook(path)
    return "pcap", read_pcap(path, device)
