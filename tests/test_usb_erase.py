"""Erase selected pictures from the card over USB (REQ-F50): DeleteObject 0x100B, no Wi-Fi counterpart."""
import os
import tempfile
import threading
import unittest

from omcap import ptp, ptp_gphoto as pg, server, usb_camera
from omcap.camera import CameraError, WriteBlocked
from test_ptp_gphoto import FakePtp, camera

D = "/store_00010001/DCIM/100OLYMP/"
JPG, ORF = D + "P1010001.JPG", D + "P1010001.ORF"


class ErasePtp(FakePtp):
    protected = ()

    def delete_object(self, h):
        self.calls.append(("delete", h))
        if h in self.protected:
            raise ptp.PtpError("protected", code=0x200D)
        del self.objects[h]


class Layer(unittest.TestCase):
    def test_delete_uses_handle_and_updates_index(self):
        fake = ErasePtp()
        with tempfile.TemporaryDirectory() as d:
            c = camera(fake, os.path.join(d, "idx.json"))
            c.file_delete("/store_00010001/DCIM/100OLYMP", "P1010001.JPG")
            self.assertEqual([x for x in fake.calls if x[0] == "delete"], [("delete", 3)])
            self.assertEqual(c.file_paths(), [ORF])
            with self.assertRaises(pg.GPhoto2Error):
                c.file_delete("/store_00010001/DCIM/100OLYMP", "P1010001.JPG")  # already gone

    def test_folder_and_stale_handle_refused(self):
        fake = ErasePtp()
        with tempfile.TemporaryDirectory() as d:
            c = camera(fake, os.path.join(d, "idx.json"))
            h = c._handle("/store_00010001/DCIM/100OLYMP", "P1010001.JPG")
            c._index.objects[h] = c._index.objects[h][:2] + ("P1019999.JPG",) + c._index.objects[h][3:]
            c._index._by_name[c._index.objects[h][:3]] = h  # the saved index says another name for this handle
            with self.assertRaises(pg.GPhoto2Error):
                c.file_delete("/store_00010001/DCIM/100OLYMP", "P1019999.JPG")
            self.assertFalse([x for x in fake.calls if x[0] == "delete"])

    def test_erase_refuses_folder_path(self):
        cam = make(ErasePtp())
        with self.assertRaises(CameraError):
            cam.erase(["/store_00010001/DCIM/100OLYMP"])

    def test_ptp_operation_code(self):
        sent = []

        class Cam(ptp.PtpCamera):
            def transact(self, code, params=(), **kw):
                sent.append((code, params))
        Cam(None).delete_object(7)
        self.assertEqual(sent, [(0x100B, (7,))])


def make(fake, allow_write=True):
    cam = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)
    cam.gp, cam._lock, cam.allow_write, cam.gone = pg, threading.Lock(), allow_write, False
    cam._hold, cam._hold_lock = 0, threading.Lock()
    cam._c = camera(fake)
    cam._files = {JPG: {}, ORF: {}}
    cam._pending, cam.last_jpg = [], JPG
    return cam


class Erase(unittest.TestCase):
    def test_pair_erased_and_lists_updated(self):
        fake = ErasePtp()
        cam = make(fake)
        r = cam.erase([JPG, ORF])
        self.assertEqual(r, {"erased": [JPG, ORF], "failed": []})
        self.assertEqual([x[1] for x in fake.calls if x[0] == "delete"], [3, 4])
        self.assertEqual(cam._files, {})
        self.assertIsNone(cam.last_jpg)
        self.assertEqual(cam.hold, 0)  # live view released again

    def test_failure_keeps_the_rest(self):
        fake = ErasePtp()
        fake.protected = (3,)
        cam = make(fake)
        r = cam.erase([JPG, ORF])
        self.assertEqual(r, {"erased": [ORF], "failed": [JPG]})
        self.assertIn(JPG, cam._files)
        self.assertNotIn(ORF, cam._files)
        self.assertEqual(cam.hold, 0)

    def test_read_only_refuses(self):
        fake = ErasePtp()
        with self.assertRaises(WriteBlocked):
            make(fake, allow_write=False).erase([JPG])
        self.assertFalse([x for x in fake.calls if x[0] == "delete"])

    def test_bad_path_refused(self):
        with self.assertRaises(CameraError):
            make(ErasePtp()).erase(["/etc/passwd"])

    def test_feature_is_usb_only(self):
        self.assertIn("erase", usb_camera.FEATURES)
        self.assertNotIn("erase", server.WIFI_FEATURES)


def act(path, b):
    return server.Handler._action(server.Handler.__new__(server.Handler), path, b)


class Endpoint(unittest.TestCase):
    def setUp(self):
        self.saved = (server.cam, server.conn_type, server.card_cache, server.ensure_idle)
        server.ensure_idle = lambda: None

    def tearDown(self):
        server.cam, server.conn_type, server.card_cache, server.ensure_idle = self.saved

    def test_wifi_refuses(self):
        server.cam, server.conn_type = object(), "wifi"
        with self.assertRaises(CameraError):
            act("/api/erase", {"paths": ["/DCIM/100OLYMP/P1.JPG"]})

    def test_usb_updates_saved_list(self):
        store = {"usb": [{"path": JPG}, {"path": ORF}, {"path": D + "P1010002.JPG"}]}

        def cache(kind, imgs=None):
            if imgs is not None:
                store[kind] = imgs
            return store.get(kind)

        class Cam:
            def erase(self, paths):
                return {"erased": [JPG, ORF], "failed": []}
        server.cam, server.conn_type, server.card_cache = Cam(), "usb", cache
        r = act("/api/erase", {"paths": [JPG, ORF]})
        self.assertEqual(r["erased"], [JPG, ORF])
        self.assertEqual(store["usb"], [{"path": D + "P1010002.JPG"}])


if __name__ == "__main__":
    unittest.main()
