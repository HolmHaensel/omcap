"""USB partial read with a fake gphoto2 camera object (no camera)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from omcap import usb_camera  # noqa: E402
from omcap.camera import CameraError  # noqa: E402

PATH = "/store_00010001/DCIM/100OLYMP/P1010001.JPG"
DATA = bytes(range(256)) * 40


class FakeGp:
    GP_FILE_TYPE_NORMAL = 1
    GP_FILE_TYPE_PREVIEW = 2

    class GPhoto2Error(Exception):
        pass


class FakeFile:
    def get_data_and_size(self):
        return DATA


class FakeCam:
    def __init__(self, partial=True, fail=False):
        self.partial, self.fail, self.full_reads, self.part_reads = partial, fail, 0, 0
        if partial:
            self.file_read = self._file_read

    def _file_read(self, folder, name, kind, offset, buf):
        self.part_reads += 1
        if self.fail:
            raise FakeGp.GPhoto2Error("not supported")
        n = min(len(buf), len(DATA) - offset)
        buf[:n] = DATA[offset:offset + n]
        return n

    def file_get(self, folder, name, kind):
        self.full_reads += 1
        return FakeFile()


def make(cam):
    u = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)
    import threading
    u._lock = threading.Lock()
    u.gp = FakeGp
    u._c = cam
    return u


class Head(unittest.TestCase):
    def test_partial(self):
        c = FakeCam()
        self.assertEqual(make(c).read_head(PATH, 100), DATA[:100])
        self.assertEqual(c.full_reads, 0)

    def test_fallback_without_binding(self):
        c = FakeCam(partial=False)
        self.assertEqual(make(c).read_head(PATH, 100), DATA[:100])
        self.assertEqual(c.full_reads, 1)

    def test_fallback_on_error_once(self):
        c = FakeCam(fail=True)
        u = make(c)
        self.assertEqual(u.read_head(PATH, 100), DATA[:100])
        u.read_head(PATH, 100)
        self.assertEqual(c.part_reads, 1)  # not retried after the first failure
        self.assertEqual(c.full_reads, 2)

    def test_path_check(self):
        for fn in (lambda u: u.read_head("/etc/passwd", 10), lambda u: u.thumbnail("/store_00010001/DCIM/../x"),
                   lambda u: u.fetch_file("/x", "/tmp/y"), lambda u: u.read_file("/x")):
            with self.assertRaises(CameraError):
                fn(make(FakeCam()))


if __name__ == "__main__":
    unittest.main()
