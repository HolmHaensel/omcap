"""Live view switch d06d: at 0 the E-M1 sends 0-byte frames; the PTP layer sets 1024x768 once per session."""
import struct
import unittest

from omcap import ptp

JPEG = b"\xff\xd8" + b"\0" * 2000 + b"\xff\xd9"


def desc(value):  # d06d, UINT32, writable, default 0, current value, no form
    return struct.pack("<HHBIIB", 0xD06D, 6, 1, 0, value, 0)


class Fake(ptp.PtpCamera):
    def __init__(self, lv_size):
        self.lv_size, self.sets = lv_size, []

    def transact(self, code, params=(), data=None, want_data=False, timeout=5000):
        if code == ptp.OP_PROP_DESC:
            return [desc(self.lv_size)]
        if code == ptp.OP_SET_PROP:
            self.lv_size = struct.unpack("<I", data)[0]
            self.sets.append(self.lv_size)
            return [None]
        if code == ptp.OP_LIVEVIEW:
            return [JPEG if self.lv_size else b""]
        raise AssertionError(hex(code))


class LiveviewOn(unittest.TestCase):
    def test_switches_on_when_zero(self):
        cam = Fake(0)
        self.assertEqual(cam.liveview_frame(), JPEG)
        self.assertEqual(cam.sets, [0x04000300])

    def test_keeps_chosen_size(self):
        cam = Fake(0x050003C0)
        self.assertEqual(cam.liveview_frame(), JPEG)
        cam.liveview_frame()
        self.assertEqual(cam.sets, [])


if __name__ == "__main__":
    unittest.main()
