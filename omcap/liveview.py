"""Live view reception: the camera sends RTP/UDP with JPEG fragments.

The first packet of a frame may carry an RTP header extension with camera status
(Olympus OPC protocol 1.0a, chapter 4): entries of function ID, length in 32-bit
words and data. `parse_extension` decodes the entries we know; unknown IDs are kept raw.
"""
import socket
import struct
import threading
import time


def _words(data):
    return list(struct.unpack(">%dI" % (len(data) // 4), data[:len(data) // 4 * 4]))


def _s32(v):
    return v - 0x100000000 if v & 0x80000000 else v


def _s16(v):
    return v - 0x10000 if v & 0x8000 else v


def _ratio(w):
    """min/max/current as numerator/denominator pairs (3 words of 16+16 bit)."""
    vals = [((x >> 16), x & 0xFFFF) for x in w[:3]]
    return {k: (n / d if d else None) for k, (n, d) in zip(("min", "max", "now"), vals)}


def decode_entry(fid, w):
    """Readable value for the IDs documented in the OPC spec; None if unknown."""
    if not w:
        return None
    if fid == 2:  # AF result: 0 not done, 1 ok, 2 failed; frame x/y/w/h
        return {"result": w[0], "frame": w[1:5]}
    if fid == 3:  # memory card status bits; bits 0-1 = mount state (E-M1 with card sends 2)
        m = w[0]
        return {"mount_state": m & 3, "not_full": bool(m & 4), "protected": bool(m & 8),
                "error": bool(m & 16), "writing": bool(m & 32)}
    if fid in (1, 4, 5, 7, 16, 17, 19):
        # JPEG frame size, orientation, free shots, 7 battery level? (E-M1: 100 -> 75 after a shot,
        # unconfirmed), warning, focus mode, 19 unknown counter (E-M1: -5 per shot)
        return w[0]
    if fid == 8:  # shutter speed: longest / shortest / now as ratios
        return _ratio(w)
    # Layouts below as sent by the E-M1 Mark I (differ from the AIR A01 spec, which uses ratios)
    if fid == 9 and len(w) >= 3:  # f-number x10: smallest aperture / open at this focal length / now
        return {"max": w[0] / 10, "open": w[1] / 10, "now": w[2] / 10}
    if fid == 10 and len(w) >= 3:  # exposure compensation x10, signed: max / min / now
        return {"max": _s32(w[0]) / 10, "min": _s32(w[1]) / 10, "now": _s32(w[2]) / 10}
    if fid == 12:  # ISO now (also with ISO Auto); w[1] = 0x10000 seen with Auto
        return {"now": w[0]}
    if fid == 18 and len(w) >= 2:  # focal length in mm: lens wide end, tele end, now
        return {"min_mm": w[0] & 0xFFFF, "max_mm": w[1] & 0xFFFF, "now_mm": w[1] >> 16}
    if fid == 107 and len(w) >= 3:  # level meter: roll/pitch in 1/10 degree
        return {"reliable_roll": bool(w[0] >> 16 & 1), "reliable_pitch": bool(w[0] >> 16 & 2),
                "orientation": w[0] & 0xFFFF, "roll": _s16(w[1] & 0xFFFF), "pitch": _s16(w[2] & 0xFFFF)}
    if 108 <= fid <= 115 and len(w) >= 2:  # face frames
        return {"x": w[0] >> 16, "y": w[0] & 0xFFFF, "w": w[1] >> 16, "h": w[1] & 0xFFFF}
    return None


def parse_extension(ext):
    """Entries of the extension data (without the 4-byte RTP extension header): {id: words}."""
    out, i = {}, 0
    while i + 4 <= len(ext):
        fid, n = struct.unpack_from(">HH", ext, i)
        i += 4
        out[fid] = _words(ext[i:i + 4 * n])
        i += 4 * n
    return out


class LiveView:
    def __init__(self, port=5555):
        self.port = port
        self.frame = None
        self.seq = 0
        self.last_frame = None  # time of the last complete frame
        self.ext = {}           # latest RTP extension entries {function id: words}
        self.ext_seen = {}      # function id -> number of frames that carried it
        self.cond = threading.Condition()
        self._sock = None
        self._run = False

    @property
    def running(self):
        return self._run

    @property
    def age(self):
        """Seconds since the last complete frame, None before the first."""
        return None if self.last_frame is None else time.monotonic() - self.last_frame

    def start(self):
        self.stop()  # a restart only frees the port afterwards
        self.ext = {}
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 21)
        s.bind(("0.0.0.0", self.port))
        s.settimeout(1.0)
        self.last_frame = time.monotonic()
        self._sock, self._run = s, True
        threading.Thread(target=self._loop, args=(s,), daemon=True).start()

    def stop(self):
        self._run = False
        if self._sock:
            self._sock.close()
            self._sock = None

    def _loop(self, sock):
        buf = bytearray()
        expected = None
        damaged = False
        while self._run and sock is self._sock:
            try:
                pkt = sock.recv(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(pkt) < 12:
                continue
            number = int.from_bytes(pkt[2:4], "big")
            if expected is not None and number != expected:
                damaged = True  # packet lost on Wi-Fi
            expected = (number + 1) & 0xFFFF
            hdr = 12 + 4 * (pkt[0] & 0x0F)
            if pkt[0] & 0x10:  # header extension: camera status (OPC protocol)
                n = int.from_bytes(pkt[hdr + 2:hdr + 4], "big")
                try:
                    ext = parse_extension(pkt[hdr + 4:hdr + 4 + 4 * n])
                    self.ext = ext
                    for fid in ext:
                        self.ext_seen[fid] = self.ext_seen.get(fid, 0) + 1
                except struct.error:
                    pass
                hdr += 4 + 4 * n
            buf += pkt[hdr:]
            if pkt[1] & 0x80:  # marker: frame complete
                # do not pass on frames with lost packets (about 10 % on Wi-Fi).
                if not damaged and buf[:2] == b"\xff\xd8" and buf[-2:] == b"\xff\xd9":
                    with self.cond:
                        self.frame = bytes(buf)
                        self.seq += 1
                        self.last_frame = time.monotonic()
                        self.cond.notify_all()
                buf = bytearray()
                damaged = False

    def live_values(self):
        """Camera values for the page while frames arrive (E-M1 layouts), else None.

        shots: free shots on the card; iso: ISO in use (also with ISO Auto);
        shutter: [numerator, denominator] in use; aperture: f-number in use;
        focal: [wide, tele, now] in mm; af: 1 in focus, 0 no result."""
        age = self.age
        if not self.running or age is None or age > 3 or not self.ext:
            return None
        e, out = self.ext, {}
        if e.get(5):
            out["shots"] = e[5][0]
        if e.get(12):
            out["iso"] = e[12][0]
        if len(e.get(8, ())) >= 3 and e[8][2] & 0xFFFF:
            out["shutter"] = [e[8][2] >> 16, e[8][2] & 0xFFFF]
        if len(e.get(9, ())) >= 3:
            out["aperture"] = e[9][2] / 10
        f = decode_entry(18, e.get(18))
        if f and f["now_mm"]:
            out["focal"] = [f["min_mm"], f["max_mm"], f["now_mm"]]
        if e.get(2):
            out["af"] = e[2][0]
        return out or None

    def ext_info(self):
        """Latest extension data: decoded where known, raw words otherwise."""
        ext = dict(self.ext)
        return {"seen": {str(k): v for k, v in sorted(self.ext_seen.items())},
                "decoded": {str(k): decode_entry(k, w) for k, w in ext.items() if decode_entry(k, w) is not None},
                "raw": {str(k): w for k, w in ext.items()}}

    def wait_frame(self, last_seq, timeout=3.0):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != last_seq, timeout)
            return self.seq, self.frame
