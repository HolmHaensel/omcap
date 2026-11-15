"""USB: no endless session rebuild when the camera is gone (seen 2026-11-15: after the cable was pulled the app
rebuilt the session every few seconds, stopped the macOS camera service each time and blocked other apps)."""
import time
import unittest
from unittest import mock

from omcap import usb_camera


class FakeCamera:
    shooting = False
    stage = 0
    hold = 0
    last_press = 0.0
    gone = False
    lv_reason = "test"

    def __init__(self, reopen_ok=True):
        self.reopens = 0
        self.reopen_ok = reopen_ok

    def dial_turned(self):
        return False

    def preview_frame(self):
        return None  # live view keeps failing

    def reopen(self, reason="?"):
        self.reopens += 1
        return self.reopen_ok


class Gone(unittest.TestCase):
    def run_loop(self, cam, seconds, present):
        live = usb_camera.UsbLive(cam)
        with mock.patch.object(usb_camera, "detect_name", lambda: "Olympus E-M1" if present() else None), \
                mock.patch.object(usb_camera.time, "sleep", lambda s: None):
            live._run = True
            end = time.monotonic() + seconds

            def stop_later():
                while time.monotonic() < end:
                    pass
                live._run = False
            import threading
            t = threading.Thread(target=stop_later)
            t.start()
            live._loop()
            t.join()
        return live

    def test_camera_gone_no_rebuild(self):
        cam = FakeCamera()
        self.run_loop(cam, 0.2, present=lambda: False)
        self.assertEqual(cam.reopens, 0)
        self.assertTrue(cam.gone)

    def test_camera_back_rebuilds(self):
        cam = FakeCamera()
        self.run_loop(cam, 0.2, present=lambda: True)
        self.assertGreaterEqual(cam.reopens, 1)
        self.assertFalse(cam.gone)

    def test_failed_rebuild_backs_off(self):
        cam = FakeCamera(reopen_ok=False)
        live = self.run_loop(cam, 0.3, present=lambda: True)
        self.assertEqual(cam.reopens, 1)  # the next try waits at least 5 s
        self.assertGreaterEqual(live._backoff, 5.0)

    def test_back_camera_must_stay_3_s(self):
        # the camera appears and vanishes while its USB menu is open (camera test 2026-11-15)
        cam = FakeCamera()
        cam.gone = True
        live = usb_camera.UsbLive(cam)
        now = [100.0]
        with mock.patch.object(usb_camera, "detect_name", lambda: "Olympus E-M1"), \
                mock.patch.object(usb_camera.time, "monotonic", lambda: now[0]), \
                mock.patch.object(usb_camera.time, "sleep", lambda s: None):
            self.assertFalse(live._rebuild())
            now[0] += 2.0
            self.assertFalse(live._rebuild())
            self.assertEqual(cam.reopens, 0)
            now[0] += 1.5
            self.assertTrue(live._rebuild())
        self.assertEqual(cam.reopens, 1)
        self.assertFalse(cam.gone)

    def test_backoff_doubles_up_to_a_minute(self):
        cam = FakeCamera(reopen_ok=False)
        live = usb_camera.UsbLive(cam)
        with mock.patch.object(usb_camera, "detect_name", lambda: "Olympus E-M1"):
            waits = []
            for _ in range(6):
                live._retry_at = 0.0
                live._rebuild()
                waits.append(live._backoff)
        self.assertEqual(waits, [5.0, 10.0, 20.0, 40.0, 60.0, 60.0])



class FakeLib:
    """libusb stand-in: records calls; the interrupt transfer never comes back after a cancel (camera unplugged)."""
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def f(*args):
            self.calls.append(name)
            return 0
        return f


class CloseUnplugged(unittest.TestCase):
    """Closing the transport of an unplugged camera crashed the server (segmentation fault, 2026-11-15)."""
    def make(self, irq_live):
        import ctypes
        from omcap import ptp
        t = ptp.UsbTransport.__new__(ptp.UsbTransport)
        t.lib, t.ctx, t.h = FakeLib(), ctypes.c_void_p(1), 1
        t._irq, t._irq_live = object(), irq_live
        return t

    def test_pending_transfer_keeps_everything(self):
        from omcap import ptp
        t = self.make(irq_live=True)
        with mock.patch.object(ptp.time, "monotonic", side_effect=[0.0, 2.0, 2.0]):
            t.close()
        self.assertIn(t, ptp._LEAKED)  # buffer and callback stay alive
        for name in ("libusb_free_transfer", "libusb_close", "libusb_release_interface", "libusb_exit"):
            self.assertNotIn(name, t.lib.calls)
        ptp._LEAKED.remove(t)

    def test_normal_close_frees_all(self):
        from omcap import ptp
        t = self.make(irq_live=False)
        t.close()
        self.assertNotIn(t, ptp._LEAKED)
        for name in ("libusb_free_transfer", "libusb_release_interface", "libusb_close", "libusb_exit"):
            self.assertIn(name, t.lib.calls)

if __name__ == "__main__":
    unittest.main()
