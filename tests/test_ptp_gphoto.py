"""Offline tests of the gphoto2-compatible layer on the own PTP layer (omcap/ptp_gphoto.py)."""
import os
import tempfile
import unittest
from unittest import mock

from omcap import ptp, ptp_gphoto as pg, usb_camera

STORE = 0x00010001


def info(name, parent, folder=False, size=100):
    return {"storage": STORE, "format": 0x3001 if folder else 0x3801, "size": size, "width": 0, "height": 0,
            "parent": parent, "folder": folder, "name": name, "captured": "20261113T142530",
            "modified": ""}


class FakePtp:
    """Card: DCIM(1)/100OLYMP(2)/P1010001.JPG(3), P1010001.ORF(4); 101OLYMP(5)."""

    def __init__(self):
        self.objects = {1: info("DCIM", 0, True), 2: info("100OLYMP", 1, True), 3: info("P1010001.JPG", 2),
                        4: info("P1010001.ORF", 2, size=999), 5: info("101OLYMP", 1, True)}
        self.props = {
            0xD01C: {"type": 6, "writable": True, "value": 1 << 16 | 250,
                     "enum": [0xFFFFFFFA, 0xFFFFFFFD, 0xFFFFFFFC, 600 << 16 | 10, 32 << 16 | 10, 1 << 16 | 250]},
            0xD002: {"type": 4, "writable": True, "value": 35, "enum": [35, 40, 220]},
            0xD008: {"type": 4, "writable": True, "value": 65236, "enum": [60536, 65236, 0, 300]},
            0xD007: {"type": 4, "writable": True, "value": 65533, "enum": [65535, 65533, 200]},
            0xD06D: {"type": 6, "writable": True, "value": 1024 << 16 | 768,
                     "enum": [0, 640 << 16 | 480, 1024 << 16 | 768, 1280 << 16 | 960]},
            0xD006: {"type": 4, "writable": False, "value": 1, "enum": [1, 2, 3, 4, 8]},
            0xD04A: {"type": 4, "writable": False, "value": 14, "range": (14, 140, 1)},
            0x5001: {"type": 2, "writable": False, "value": 80},
        }
        self.calls = []
        self.queue = []
        self.info_calls = 0

    def handles(self):
        return list(self.objects)

    def object_info(self, h):
        self.info_calls += 1
        return self.objects[h]

    def prop_desc(self, code):
        return dict(self.props[code])

    def set_prop(self, code, value, dtype):
        self.calls.append(("set", code, value, dtype))
        self.props[code]["value"] = value

    def transact(self, code, params=()):
        self.calls.append(("op", code, params))

    def event(self, timeout):
        return self.queue.pop(0) if self.queue else None

    def get_partial(self, h, offset, size):
        raise ptp.PtpError("not supported", code=0x2005)


def camera(fake, cache=None):
    c = pg.Camera()
    c._index = pg.CardIndex(cache)
    c._ptp = fake
    return c


class Values(unittest.TestCase):
    def test_texts_like_libgphoto2(self):
        c = camera(FakePtp())
        w = c.get_single_config("shutterspeed")
        self.assertEqual(w.get_value(), "1/250")
        self.assertEqual(list(w.get_choices()), ["Composite", "65535/65533", "Bulb", "60", "32/10", "1/250"])
        self.assertEqual(c.get_single_config("aperture").get_value(), "3.5")
        self.assertEqual(list(c.get_single_config("exposurecompensation").get_choices()), ["-5", "-0.3", "0", "0.3"])
        self.assertEqual(list(c.get_single_config("iso").get_choices()), ["Auto", "Low", "200"])
        self.assertEqual(c.get_single_config("liveviewsize").get_value(), "1024x768")
        self.assertEqual(list(c.get_single_config("liveviewsize").get_choices()), ["640x480", "1024x768", "1280x960"])
        self.assertEqual(c.get_single_config("batterylevel").get_value(), "80%")
        self.assertTrue(c.get_single_config("d006").get_readonly())
        self.assertEqual(c.get_single_config("d04a").get_range(), (14, 140, 1))

    def test_long_exposure_labels_known_to_the_app(self):
        texts = [pg.shutter_text(v) for v in (0xFFFFFFFA, 0xFFFFFFFD, 0xFFFFFFFC)]
        self.assertTrue(all(t in usb_camera.LONG_LABELS for t in texts))

    def test_set_by_text_and_raw(self):
        fake = FakePtp()
        c = camera(fake)
        for name, text in (("exposurecompensation", "-0.3"), ("liveviewsize", "1280x960"), ("d01c", "4294967290")):
            w = c.get_single_config(name)
            w.set_value(text)
            c.set_single_config(name, w)
        self.assertEqual([x[2] for x in fake.calls], [65236, 1280 << 16 | 960, 0xFFFFFFFA])

    def test_unknown_named_value_is_refused(self):
        c = camera(FakePtp())
        for name, text in (("aperture", "1.2"), ("liveviewsize", "800x600"), ("d00c", "Auto")):
            fake = c._ptp
            fake.props.setdefault(0xD00C, {"type": 4, "writable": True, "value": 1})
            w = c.get_single_config(name)
            w.set_value(text)
            with self.assertRaises(pg.GPhoto2Error):
                c.set_single_config(name, w)

    def test_busy_set_is_retried(self):
        fake = FakePtp()
        calls = []
        real = fake.set_prop

        def busy_once(code, value, dtype):
            calls.append(code)
            if len(calls) == 1:
                raise ptp.PtpError("busy", code=ptp.RC_BUSY)
            real(code, value, dtype)
        fake.set_prop = busy_once
        c = camera(fake)
        w = c.get_single_config("iso")
        w.set_value("200")
        with mock.patch.object(pg.time, "sleep"):
            c.set_single_config("iso", w)
        self.assertEqual(len(calls), 2)
        self.assertEqual(fake.props[0xD007]["value"], 200)

    def test_file_paths_for_resync(self):
        c = camera(FakePtp())
        self.assertEqual(sorted(c.file_paths()), ["/store_00010001/DCIM/100OLYMP/P1010001.JPG",
                                                  "/store_00010001/DCIM/100OLYMP/P1010001.ORF"])

    def test_opcode_runs_operation(self):
        fake = FakePtp()
        c = camera(fake)
        w = c.get_single_config("opcode")
        w.set_value("0x9481,0x3")
        c.set_single_config("opcode", w)
        self.assertEqual(fake.calls, [("op", 0x9481, (3,))])

    def test_ptp_error_becomes_gphoto2_error(self):
        c = camera(FakePtp())
        c._ptp.prop_desc = mock.Mock(side_effect=ptp.PtpError("busy", 0x2019))
        with self.assertRaises(pg.GPhoto2Error):
            c.get_single_config("d00c")


class Events(unittest.TestCase):
    def test_dial_event_text_matches_the_app(self):
        fake = FakePtp()
        fake.queue = [(0xC003, (3,))]
        kind, data = camera(fake).wait_for_event(100)
        self.assertEqual(kind, pg.GP_EVENT_UNKNOWN)
        self.assertTrue(usb_camera.DIAL_EVENT.search(data))

    def test_object_added_gives_path(self):
        fake = FakePtp()
        c = camera(fake)
        c.folder_list_folders("/")  # index loaded
        fake.objects[6] = info("P1010002.JPG", 5)
        fake.queue = [(0xC002, (6,))]
        kind, data = c.wait_for_event(100)
        self.assertEqual(kind, pg.GP_EVENT_FILE_ADDED)
        self.assertEqual((data.folder, data.name), ("/store_00010001/DCIM/101OLYMP", "P1010002.JPG"))

    def test_timeout(self):
        self.assertEqual(camera(FakePtp()).wait_for_event(1)[0], pg.GP_EVENT_TIMEOUT)


class Card(unittest.TestCase):
    def test_listing_and_info(self):
        c = camera(FakePtp())
        self.assertEqual(c.folder_list_folders("/").get_name(0), "store_00010001")
        self.assertEqual(list(c.folder_list_folders("/store_00010001/DCIM")._names), ["100OLYMP", "101OLYMP"])
        files = c.folder_list_files("/store_00010001/DCIM/100OLYMP")
        self.assertEqual(files._names, ["P1010001.JPG", "P1010001.ORF"])
        self.assertEqual(c.file_get_info("/store_00010001/DCIM/100OLYMP", "P1010001.ORF").file.size, 999)
        with self.assertRaises(pg.GPhoto2Error):
            c.file_get_info("/store_00010001/DCIM/100OLYMP", "nope.JPG")

    def test_partial_read_not_supported(self):
        c = camera(FakePtp())
        with self.assertRaises(pg.GPhoto2Error) as e:
            c.file_read("/store_00010001/DCIM/100OLYMP", "P1010001.JPG", pg.GP_FILE_TYPE_NORMAL, 0,
                        memoryview(bytearray(10)))
        self.assertEqual(e.exception.code, pg.GP_ERROR_NOT_SUPPORTED)

    def test_cache_reused_and_checked(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "idx.json")
            first = FakePtp()
            camera(first, path).folder_list_folders("/")
            self.assertEqual(first.info_calls, 5)
            second = FakePtp()
            camera(second, path).folder_list_folders("/")
            self.assertEqual(second.info_calls, 2)  # only the spot check
            other = FakePtp()  # another card: same handles and names, other size
            other.objects[4]["size"] = 1234
            camera(other, path).folder_list_folders("/")
            self.assertEqual(other.info_calls, 2 + 5)


class FakeLib:
    """libusb stand-in for UsbTransport: bulk reads from a script of (rc, bytes)."""

    def __init__(self, reads):
        self.reads = reads

    def libusb_bulk_transfer(self, h, ep, buf, size, got, timeout):
        rc, data = self.reads.pop(0)
        ctypes_memmove(buf, data, len(data))
        got._obj.value = len(data)
        return rc


def ctypes_memmove(buf, data, n):
    import ctypes
    ctypes.memmove(buf, data, n)


class Transport(unittest.TestCase):
    def transport(self, reads):
        t = ptp.UsbTransport.__new__(ptp.UsbTransport)
        t.lib, t.h, t.ep_in, t._buf = FakeLib(reads), 1, 0x82, None
        t._events, t._irq, t._irq_live = [], None, False
        return t

    def test_timeout_after_some_bytes_keeps_them(self):
        t = self.transport([(-7, b"abc"), (-7, b"")])
        self.assertEqual(t.read(timeout=200), b"abc")
        with self.assertRaises(ptp.PtpError):
            t.read(timeout=200)

    def test_late_callback_after_close_is_ignored(self):
        t = self.transport([])
        t._irq_live = True
        t._on_irq(None)
        self.assertFalse(t._irq_live)


class Backend(unittest.TestCase):
    def test_auto_falls_back_to_libgphoto2(self):
        with mock.patch.object(usb_camera.UsbCamera, "_open") as op, \
                mock.patch.object(usb_camera, "_gp") as gp:
            op.side_effect = [usb_camera.CameraError("no PTP"), None, None]
            gp.return_value.Camera.return_value.get_single_config.side_effect = Exception("no widget")
            gp.return_value.GPhoto2Error = Exception
            cam = usb_camera.UsbCamera(backend="auto")
        self.assertEqual(cam.backend, "gphoto2")

    def test_ptp_does_not_fall_back(self):
        with mock.patch.object(usb_camera.UsbCamera, "_open", side_effect=usb_camera.CameraError("no PTP")):
            with self.assertRaises(usb_camera.CameraError):
                usb_camera.UsbCamera(backend="ptp")


if __name__ == "__main__":
    unittest.main()
