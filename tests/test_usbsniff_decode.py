"""usbsniff: backends, decoders, compare and outputs with synthetic traffic (no camera, no USB)."""
import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from usbsniff import backends, compare, decoders, output  # noqa: E402
from usbsniff.model import IN, OUT, Transfer  # noqa: E402

NAMES = decoders.load_names()


def cont(ctype, code, tid, payload=b""):
    return struct.pack("<IHHI", 12 + len(payload), ctype, code, tid) + payload


def cmd(code, tid, *params):
    return cont(1, code, tid, struct.pack("<%dI" % len(params), *params))


def hook_lines(records):
    """Synthetic hook log like usbsniff_hook.dylib writes it."""
    return "".join(json.dumps(r) + "\n" for r in records)


def ptp_session(t, tid, code, params=(), out=None, data_in=None, resp=0x2001, seq=None):
    """cmd + resp records of the hook for one transaction (data phases without header, as ICC gives them)."""
    seq = seq or tid
    c = {"kind": "cmd", "seq": seq, "t": t, "pid": 1, "cmd": cmd(code, tid, *params).hex(), "cmd_len": 12 + 4 * len(params)}
    if out is not None:
        c.update(out=out.hex(), out_len=len(out))
    r = {"kind": "resp", "seq": seq, "t": t + 0.002, "pid": 1, "resp": cont(3, resp, tid).hex(), "resp_len": 12}
    if data_in is not None:
        r.update({"in": data_in.hex(), "in_len": len(data_in)})
    return [c, r]


class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, records):
        p = os.path.join(self.tmp.name, name)
        with open(p, "w") as f:
            f.write(hook_lines(records))
        return p

    def decode(self, path):
        kind, transfers = backends.load(path)
        self.assertEqual(kind, "hook")
        self.assertEqual(decoders.pick(transfers), "ptp")
        return decoders.DECODERS["ptp"](transfers, NAMES)

    def test_set_prop_with_data_and_names(self):
        recs = [{"kind": "note", "t": 0, "msg": "loaded"}]
        recs += ptp_session(1.0, 5, 0x1016, (0xD0CF,), out=struct.pack("<H", 2))
        recs += ptp_session(1.1, 6, 0x1015, (0xD0D0,), data_in=struct.pack("<H", 512))
        ops = self.decode(self.write("a.jsonl", recs))
        self.assertEqual([o.name for o in ops], ["SetDevicePropValue", "GetDevicePropValue"])
        s = ops[0]
        self.assertEqual(s.params, (0xD0CF,))
        self.assertEqual(s.data_out, b"\x02\x00")
        self.assertEqual(s.resp_name, "OK")
        self.assertIn("LoupeStage", " ".join(s.notes))
        self.assertAlmostEqual(s.duration_ms, 2.0, places=3)
        self.assertEqual(ops[1].data_in, struct.pack("<H", 512))
        line = output.log_line(s, 0)
        self.assertIn("0x1016 SetDevicePropValue(0xD0CF)", line)
        self.assertIn("out=2B [02 00]", line)

    def test_truncated_data_keeps_full_length(self):
        big = bytes(range(256)) * 40  # 10240 bytes, stored only 4096
        recs = ptp_session(1.0, 2, 0x9484, (1,))
        recs[1].update({"in": big[:4096].hex(), "in_len": len(big)})
        op = self.decode(self.write("lv.jsonl", recs))[0]
        self.assertEqual(op.data_in_len, 10240)
        self.assertEqual(len(op.data_in), 4096)
        self.assertEqual(op.resp_name, "OK")

    def test_event_and_error(self):
        recs = ptp_session(1.0, 3, 0x9483, (2, 640, 480, 1), resp=0x2006)
        recs[1]["err"] = "Error Domain=x"
        recs.append({"kind": "event", "t": 1.5, "pid": 1, "event": cont(4, 0xC003, 0, struct.pack("<I", 1)).hex()})
        ops = self.decode(self.write("e.jsonl", recs))
        self.assertEqual(ops[0].resp_name, "ParameterNotSupported")
        self.assertTrue(any("error" in n for n in ops[0].notes))
        self.assertEqual((ops[1].kind, ops[1].name, ops[1].params), ("event", "OMD_AF_Frame", (1,)))

    def test_tid_reuse_across_sessions(self):
        recs = ptp_session(1.0, 0, 0x1002, (1,)) + ptp_session(2.0, 0, 0x1002, (1,), resp=0x201E, seq=99)
        ops = self.decode(self.write("s.jsonl", recs))
        self.assertEqual([o.resp_name for o in ops], ["OK", "SessionAlreadyOpen"])

    def test_diff_finds_only_the_action(self):
        base = []
        for i in range(5):
            base += ptp_session(1.0 + i, 10 + i, 0x9484, (1,), data_in=bytes([i]) * 20, seq=10 + i)
            base += ptp_session(1.5 + i, 30 + i, 0x948A, (), data_in=b"\0\0\0\0", seq=30 + i)
        act = list(base)
        act += ptp_session(9.0, 50, 0x1016, (0xD0CF,), out=b"\x02\x00", seq=50)
        act += ptp_session(9.1, 51, 0x948A, (), data_in=b"\x01\0\0\0\xcf\xd0", seq=51)  # poll reports change
        act += ptp_session(9.2, 52, 0x9484, (1,), data_in=b"new frame", seq=52)   # noise
        b = self.decode(self.write("base.jsonl", base))
        a = self.decode(self.write("act.jsonl", act))
        new = compare.diff(b, a)
        self.assertEqual([(o.code, o.params) for o in new], [(0x1016, (0xD0CF,)), (0x948A, ())])


def usbpcap_packet(ep, info, data, xfer=3):
    return struct.pack("<HQIHBHHBBI", 27, 1, 0, 0x09, info, 1, 4, ep, xfer, len(data)) + data


def pcap_file(packets, linktype=249):
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, linktype)
    for i, p in enumerate(packets):
        out += struct.pack("<IIII", 100 + i, 0, len(p), len(p)) + p
    return out


class Pcap(unittest.TestCase):
    def test_usbpcap_split_data_phase(self):
        payload = bytes(600)
        data = cont(2, 0x1009, 7, payload)
        pkts = [usbpcap_packet(0x01, 0, cmd(0x1009, 7, 0x42)),
                usbpcap_packet(0x81, 1, data[:512]), usbpcap_packet(0x81, 1, data[512:]),
                usbpcap_packet(0x81, 0, b""),                     # IN request without data: ignored
                usbpcap_packet(0x81, 1, cont(3, 0x2001, 7))]
        with tempfile.NamedTemporaryFile(suffix=".pcap", delete=False) as f:
            f.write(pcap_file(pkts))
        try:
            kind, tr = backends.load(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual(kind, "pcap")
        self.assertEqual(tr[0].device, "1:4")
        ops = decoders.DECODERS[decoders.pick(tr)](tr, NAMES)
        self.assertEqual(len(ops), 1)
        self.assertEqual((ops[0].name, ops[0].params, ops[0].data_in_len, ops[0].resp_name),
                         ("GetObject", (0x42,), 600, "OK"))

    def test_pcapng_roundtrip(self):
        tr = [Transfer(1.0, OUT, "0x01", cmd(0x1001, 1)), Transfer(1.001, IN, "0x81", cont(3, 0x2001, 1))]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.pcapng")
            output.write_pcapng(tr, p)
            kind, back = backends.load(p)
        self.assertEqual([t.data for t in back], [t.data for t in tr])
        self.assertAlmostEqual(back[1].time, 1.001, places=5)


class OtherDecoders(unittest.TestCase):
    def test_mass_storage(self):
        cbw = b"USBC" + struct.pack("<IIBBB", 9, 36, 0x80, 0, 6) + bytes([0x12, 0, 0, 0, 36, 0]) + bytes(10)
        csw = b"USBS" + struct.pack("<IIB", 9, 0, 0)
        tr = [Transfer(0, OUT, "0x02", cbw), Transfer(0.1, IN, "0x81", b"x" * 36), Transfer(0.2, IN, "0x81", csw)]
        self.assertEqual(decoders.pick(tr), "mass_storage")
        op = decoders.DECODERS["mass_storage"](tr, NAMES)[0]
        self.assertEqual((op.name, op.data_in_len, op.resp_name), ("Inquiry", 36, "OK"))

    def test_hid_and_hex(self):
        tr = [Transfer(0, IN, "0x83", b"\x01\x02\x03", kind="interrupt")]
        self.assertEqual(decoders.pick(tr), "hid")
        self.assertEqual(decoders.DECODERS["hid"](tr, NAMES)[0].data_in, b"\x01\x02\x03")
        self.assertEqual(decoders.pick([Transfer(0, OUT, "0x02", b"hello world!!")]), "hex")


if __name__ == "__main__":
    unittest.main()
