"""Wi-Fi: the live view stops when the Wi-Fi drops and comes back; the app restarts it once the camera answers
(REQ-Q14, seen 2026-11-15: camera reachable again, last frame 82 s old, nothing happened)."""
import unittest
from unittest import mock

from omcap import server
from omcap.camera import CameraError


class FakeLive:
    running = True
    age = 30.0


class FakeCam:
    stage = 0
    lvqty = "0800x0600"

    def __init__(self, answers=True, allow_write=True, restart_ok=True):
        self.answers, self.allow_write, self.restart_ok = answers, allow_write, restart_ok
        self.calls = []

    def get(self, cgi, **q):
        self.calls.append(cgi)
        if self.answers is not True:
            raise CameraError("get_connectmode: timed out", self.answers)
        return "<connectmode>private</connectmode>"

    def set_mode(self, mode, lvqty=None):
        self.calls.append(("set_mode", mode, lvqty))
        if not self.restart_ok:
            raise CameraError("switch_cammode: 520", 520)


class Watch(unittest.TestCase):
    def setUp(self):
        self.old = server.cam, server.live, server.conn_type
        server.live, server.conn_type = FakeLive(), "wifi"
        server.wifi_watch.update(lost=False, backoff=5.0, retry_at=0.0)
        server.state.update(pressing=False, take=None, movie=None, play=None)
        server.job["running"] = False
        self.starts = []
        self.p = mock.patch.object(server, "start_live", lambda: self.starts.append(1))
        self.p.start()

    def tearDown(self):
        self.p.stop()
        server.cam, server.live, server.conn_type = self.old
        server.wifi_watch.update(lost=False, backoff=5.0, retry_at=0.0)

    def check(self, c):
        server.cam = c
        server.wifi_check(c)

    def test_restarts_when_camera_answers(self):
        c = FakeCam()
        self.check(c)
        self.assertIn(("set_mode", "rec", "0800x0600"), c.calls)
        self.assertEqual(self.starts, [1])
        self.assertFalse(server.busy.locked())

    def test_frames_flowing_nothing_happens(self):
        server.live.age = 0.1
        c = FakeCam()
        self.check(c)
        self.assertEqual(c.calls, [])

    def test_camera_gone_marks_lost_no_restart(self):
        c = FakeCam(answers=None)
        self.check(c)
        self.assertTrue(server.wifi_watch["lost"])
        self.assertEqual(self.starts, [])

    def test_busy_520_counts_as_there(self):
        c = FakeCam(answers=520)
        self.check(c)
        self.assertFalse(server.wifi_watch["lost"])

    def test_paused_on_purpose_is_left_alone(self):
        for key, value in (("play", "play"), ("movie", "on"), ("take", "bulb"), ("pressing", True)):
            server.state[key] = value
            c = FakeCam()
            self.check(c)
            self.assertEqual(c.calls, [], key)
            server.state[key] = None if key != "pressing" else False

    def test_read_only_does_not_restart(self):
        c = FakeCam(allow_write=False)
        self.check(c)
        self.assertEqual(self.starts, [])

    def test_failed_restart_backs_off(self):
        c = FakeCam(restart_ok=False)
        self.check(c)
        self.assertEqual(server.wifi_watch["backoff"], 10.0)
        before = len(c.calls)
        self.check(c)  # still inside the wait
        self.assertEqual(len(c.calls), before)

    def test_restart_without_frames_backs_off_too(self):
        c = FakeCam()
        self.check(c)
        self.check(c)  # frames still missing (e.g. firewall): no second restart right away
        self.assertEqual(self.starts, [1])
        server.live.age = 0.1
        self.check(c)  # frames again: the wait starts over
        self.assertEqual(server.wifi_watch["backoff"], 5.0)


if __name__ == "__main__":
    unittest.main()
