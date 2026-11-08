"""Liveview-Empfang: Die Kamera schickt RTP/UDP mit JPEG-Fragmenten."""
import socket
import threading
import time


class LiveView:
    def __init__(self, port=5555):
        self.port = port
        self.frame = None
        self.seq = 0
        self.last_frame = None  # Zeitpunkt des letzten vollständigen Bildes
        self.cond = threading.Condition()
        self._sock = None
        self._run = False

    @property
    def running(self):
        return self._run

    @property
    def age(self):
        """Sekunden seit dem letzten vollständigen Bild, None vor dem ersten."""
        return None if self.last_frame is None else time.monotonic() - self.last_frame

    def start(self):
        self.stop()  # erneuter Start gibt den Port erst frei
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
                damaged = True  # Paket im WLAN verloren
            expected = (number + 1) & 0xFFFF
            hdr = 12 + 4 * (pkt[0] & 0x0F)
            if pkt[0] & 0x10:  # Header-Extension überspringen
                hdr += 4 + 4 * int.from_bytes(pkt[hdr + 2:hdr + 4], "big")
            buf += pkt[hdr:]
            if pkt[1] & 0x80:  # Marker: Bild komplett
                # Bilder mit verlorenen Paketen nicht weitergeben (im WLAN rund 10 %).
                if not damaged and buf[:2] == b"\xff\xd8" and buf[-2:] == b"\xff\xd9":
                    with self.cond:
                        self.frame = bytes(buf)
                        self.seq += 1
                        self.last_frame = time.monotonic()
                        self.cond.notify_all()
                buf = bytearray()
                damaged = False

    def wait_frame(self, last_seq, timeout=3.0):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != last_seq, timeout)
            return self.seq, self.frame
