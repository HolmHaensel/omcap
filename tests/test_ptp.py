"""Own PTP layer (omcap/ptp.py): datasets and transaction framing, with synthetic packets (no camera)."""
import struct
import unittest

from omcap import ptp


def s(text):
    t = text + "\x00"
    return bytes([len(t)]) + t.encode("utf-16-le")


def arr(fmt, values):
    return struct.pack("<I%d%s" % (len(values), fmt), len(values), *values)


class Datasets(unittest.TestCase):
    def test_device_info(self):
        buf = (struct.pack("<HIH", 100, 0xFFFD, 100) + s("") + struct.pack("<H", 0) + arr("H", [0x1001, 0x9481])
               + arr("H", [0x4002]) + arr("H", [0xD052]) + arr("H", []) + arr("H", [0x3801])
               + s("OLYMPUS") + s("E-M1") + s("1.00"))
        d = ptp.parse_device_info(buf)
        self.assertEqual((d["operations"], d["events"], d["properties"], d["model"]),
                         ([0x1001, 0x9481], [0x4002], [0xD052], "E-M1"))

    def test_object_info(self):
        buf = (struct.pack("<IHHIHIIIIIIIHII", 0x10001, 0x3801, 0, 2965015, 0, 0, 0, 0, 4608, 3456, 0, 7, 0, 0, 0)
               + s("PB132213.JPG") + s("20261113T013800") + s(""))
        o = ptp.parse_object_info(buf)
        self.assertEqual((o["name"], o["size"], o["parent"], o["folder"], o["captured"]),
                         ("PB132213.JPG", 2965015, 7, False, "20261113T013800"))

    def test_prop_desc_enum_and_range(self):
        enum = struct.pack("<HHBHHB", 0xD006, 4, 0, 2, 2, 2) + struct.pack("<H5H", 5, 1, 2, 3, 4, 8)
        d = ptp.parse_prop_desc(enum)
        self.assertEqual((d["value"], d["enum"], d["writable"]), (2, [1, 2, 3, 4, 8], False))
        rng = struct.pack("<HHBBBB", 0x5001, 2, 0, 100, 75, 1) + struct.pack("<BBB", 1, 100, 1)
        self.assertEqual(ptp.parse_prop_desc(rng)["range"], (1, 100, 1))

    def test_pack_value(self):
        self.assertEqual(ptp.pack_value(1, 4), b"\x01\x00")
        self.assertEqual(ptp.pack_value("ab", ptp.DT_STRING), b"\x03a\x00b\x00\x00\x00")


class FakeTransport:
    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def write(self, data, timeout=5000):
        self.sent.append(bytes(data))

    def read(self, size=0, timeout=5000):
        if not self.replies:
            raise ptp.PtpError("timeout", code=-7)
        r = self.replies.pop(0)
        if r is None:  # simulated short timeout while the camera is busy
            raise ptp.PtpError("timeout", code=-7)
        return r

    def read_event(self, timeout=10):
        return (0x4005, (0x10001,)) if self.replies and self.replies[0] is not None else None


def pkt(typ, code, tid, body=b""):
    return struct.pack("<IHHI", 12 + len(body), typ, code, tid) + body


class Transactions(unittest.TestCase):
    def test_data_in_split_and_stale_packet(self):
        data = bytes(range(200))
        t = FakeTransport([pkt(ptp.RESP, 0x2001, 99),  # stale answer of an older transaction
                           struct.pack("<IHHI", 12 + len(data), ptp.DATA, 0x1009, 1) + data[:100], data[100:],
                           pkt(ptp.RESP, ptp.RC_OK, 1)])  # the data container spans two USB reads
        cam = ptp.PtpCamera(t)
        payload, _ = cam.transact(0x1009, (5,), want_data=True)
        self.assertEqual(payload, data)
        self.assertEqual(struct.unpack_from("<IHHII", t.sent[0]), (16, ptp.CMD, 0x1009, 1, 5))

    def test_events_read_while_waiting(self):
        t = FakeTransport([None, pkt(ptp.RESP, ptp.RC_OK, 1)])
        cam = ptp.PtpCamera(t)
        cam.set_prop(0xD052, 1, 4)
        self.assertEqual(cam.event(), (0x4005, (0x10001,)))

    def test_error_response(self):
        cam = ptp.PtpCamera(FakeTransport([pkt(ptp.RESP, ptp.RC_BUSY, 1)]))
        with self.assertRaises(ptp.PtpError) as e:
            cam.transact(0x9484, (1,))
        self.assertEqual(e.exception.code, ptp.RC_BUSY)

    def test_data_out(self):
        t = FakeTransport([pkt(ptp.RESP, ptp.RC_OK, 1)])
        ptp.PtpCamera(t).set_prop(0xD052, 1, 4)
        self.assertEqual(t.sent[1], pkt(ptp.DATA, ptp.OP_SET_PROP, 1, b"\x01\x00"))


if __name__ == "__main__":
    unittest.main()
