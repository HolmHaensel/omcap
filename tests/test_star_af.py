"""Offline unit tests for Star AF (REQ-F24): HFR measurement, V-curve focus, server guards, UI. No camera."""
import io
import threading
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from omcap import server, star_af, usb_camera
from omcap.camera import CameraError, WriteBlocked

HTML = Path(__file__).resolve().parent.parent / "omcap" / "web" / "index.html"


def make_star_frame(w=240, h=180, sx=120.0, sy=90.0, sigma=2.0, peak=200.0, bg=12.0):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.full((h, w), bg, dtype=np.float32)
    img += peak * np.exp(-((xx - sx) ** 2 + (yy - sy) ** 2) / (2.0 * sigma * sigma))
    return np.clip(img, 0, 255)


def to_jpeg(luma):
    import imageio.v2 as imageio
    buf = io.BytesIO()
    imageio.imwrite(buf, luma.astype(np.uint8), format="JPEG")
    return buf.getvalue()


class StarMeasurement(unittest.TestCase):
    def test_hfr_increases_monotonically_with_defocus(self):
        h1 = star_af.measure_star(make_star_frame(sigma=1.3))
        h2 = star_af.measure_star(make_star_frame(sigma=3.0))
        h3 = star_af.measure_star(make_star_frame(sigma=6.0))
        for m in (h1, h2, h3):
            self.assertTrue(m["found"], m)
        self.assertLess(h1["hfr"], h2["hfr"])
        self.assertLess(h2["hfr"], h3["hfr"])
        self.assertAlmostEqual(h1["x"], 0.5, places=2)
        self.assertAlmostEqual(h1["y"], 0.5, places=2)

    def test_rejects_isolated_hot_pixel(self):
        img = np.full((160, 200), 10.0, dtype=np.float32)
        img[80, 100] = 255.0  # single hot pixel
        # 3x3 average is ~27, wait: 10 + 245/9 = 37.2 -> check with dimmer sky/single pixel vs real star
        img2 = np.full((160, 200), 10.0, dtype=np.float32)
        img2[80, 100] = 75.0  # hot pixel: 3x3 mean delta = 65/9 = 7.2 < 8.0
        self.assertFalse(star_af.measure_star(img2)["found"])

    def test_prefers_real_star_over_hot_pixel(self):
        img = make_star_frame(w=240, h=180, sx=110.0, sy=85.0, sigma=2.2, peak=160.0, bg=10.0)
        img[95, 130] = 255.0  # isolated hot pixel elsewhere
        m = star_af.measure_star(img)
        self.assertTrue(m["found"])
        self.assertAlmostEqual(m["x"], 110.0 / 240.0, delta=0.02)
        self.assertAlmostEqual(m["y"], 85.0 / 180.0, delta=0.02)

    def test_empty_sky_returns_not_found(self):
        img = np.full((160, 200), 15.0, dtype=np.float32)
        self.assertFalse(star_af.measure_star(img)["found"])

    def test_bright_edge_pixel_does_not_crash(self):
        # Regression test: bright edge inside the ROI previously caused negative slicing IndexError
        img = np.full((180, 240), 10.0, dtype=np.float32)
        img[0:4, 0:4] = 250.0  # bright patch right on the ROI corner
        img[:, 0:3] = 240.0    # bright strip along the left edge
        m = star_af.measure_star(img, cx=0.05, cy=0.05, box=40)
        self.assertIn("found", m)

    def test_jpeg_decode_round_trip(self):
        jpg = to_jpeg(make_star_frame(sigma=1.8, peak=210.0))
        m = star_af.measure_jpeg(jpg)
        self.assertTrue(m["found"])
        self.assertLess(m["hfr"], 3.5)

    def test_full_frame_finder_prefers_unsaturated_star(self):
        # Blown-out beacon at (60, 50) + clean unsaturated star at (180, 120)
        img = make_star_frame(w=240, h=180, sx=60.0, sy=50.0, sigma=2.5, peak=255.0, bg=10.0)
        img += make_star_frame(w=240, h=180, sx=180.0, sy=120.0, sigma=2.0, peak=160.0, bg=0.0)
        img = np.clip(img, 0, 255)
        hit = star_af.find_brightest_star(img)
        self.assertTrue(hit["found"])
        self.assertFalse(hit["saturated"])
        self.assertAlmostEqual(hit["x"], 180.0 / 240.0, delta=0.03)
        self.assertAlmostEqual(hit["y"], 120.0 / 180.0, delta=0.03)

    def test_full_frame_finder_falls_back_to_saturated_with_flag(self):
        img = make_star_frame(w=240, h=180, sx=170.0, sy=110.0, sigma=2.5, peak=255.0, bg=10.0)
        hit = star_af.find_brightest_star(img)
        self.assertTrue(hit["found"])
        self.assertTrue(hit["saturated"])


class AutoStarAfVcurve(unittest.TestCase):
    def _run_sim(self, start_pos, true_focus, stop_after=None):
        state = {"pos": start_pos, "moves": 0}
        stop = threading.Event()
        STEP_UNITS = {1: 1, 2: 3, 3: 8}

        def drive(direction, step):
            state["pos"] += STEP_UNITS[step] if direction == "far" else -STEP_UNITS[step]
            state["moves"] += 1
            if stop_after is not None and state["moves"] >= stop_after:
                stop.set()

        def grab():
            defocus = abs(state["pos"] - true_focus)
            sigma = 1.2 + 0.35 * defocus
            return make_star_frame(sigma=sigma, peak=max(40.0, 220.0 - 5.0 * defocus))

        af = star_af.AutoStarAF(drive, grab, stop, frames_per_step=1, settle_s=0.0)
        res = af.run()
        return res, state["pos"]

    def test_converges_when_focus_is_farther(self):
        res, final_pos = self._run_sim(start_pos=0, true_focus=9)
        self.assertEqual(res["phase"], "done")
        self.assertLessEqual(abs(final_pos - 9), 1)
        self.assertLess(res["best_hfr"], res["start_hfr"])

    def test_converges_when_focus_is_nearer(self):
        res, final_pos = self._run_sim(start_pos=12, true_focus=2)
        self.assertEqual(res["phase"], "done")
        self.assertLessEqual(abs(final_pos - 2), 1)
        self.assertLess(res["best_hfr"], res["start_hfr"])

    def test_stops_cleanly_when_cancelled(self):
        res, _ = self._run_sim(start_pos=0, true_focus=15, stop_after=2)
        self.assertEqual(res["phase"], "stopped")

    def test_reports_error_when_no_star(self):
        dark = np.full((160, 200), 10.0, dtype=np.float32)
        af = star_af.AutoStarAF(lambda d, s: None, lambda: dark, threading.Event(),
                                frames_per_step=1, settle_s=0.0)
        res = af.run()
        self.assertEqual(res["phase"], "error")
        self.assertIn("No star", res["message"])

    def test_reports_bright_scene_error(self):
        daylight = np.full((160, 200), 210.0, dtype=np.float32)
        m = star_af.measure_star(daylight)
        self.assertFalse(m["found"])
        self.assertTrue(m["bright"])
        af = star_af.AutoStarAF(lambda d, s: None, lambda: daylight, threading.Event(),
                                frames_per_step=1, settle_s=0.0)
        res = af.run()
        self.assertEqual(res["phase"], "error")
        self.assertIn("Too bright", res["message"])


class ServerGuards(unittest.TestCase):
    def setUp(self):
        self.orig = (server.cam, server.live, server.conn_type,
                     dict(server.job), dict(server.star_af_state))
        server.job.update(name=None, running=False, done=0, total=0, error=None)
        server.star_af_state.update(running=False, phase="idle", hfr=None, best_hfr=None,
                                    start_hfr=None, step=0, message=None, error=None, samples=[])

    def tearDown(self):
        server.stop_job.set()
        server.cam, server.live, server.conn_type, job0, sa0 = self.orig
        server.job.update(job0)
        server.star_af_state.update(sa0)

    def _setup_cam(self, conn="usb", allow_write=True, live_on=True, fm="1", mode="M"):
        cam = mock.MagicMock()
        cam.allow_write = allow_write
        cam.stage = 0
        cam.loupe_on = False
        cam.focus_mode.return_value = fm
        cam.take_mode.return_value = mode
        live = mock.MagicMock()
        live.running = live_on
        live.seq = 1
        live.frame = to_jpeg(make_star_frame(sigma=1.5))
        live.wait_frame.return_value = (2, live.frame, (0, 0))
        server.cam, server.live, server.conn_type = cam, live, conn
        return cam, live

    def test_refused_over_wifi(self):
        self._setup_cam(conn="wifi")
        with self.assertRaises(CameraError) as ctx:
            server.start_star_af()
        self.assertIn("USB", str(ctx.exception))

    def test_refused_in_read_only_mode(self):
        self._setup_cam(allow_write=False)
        with self.assertRaises(WriteBlocked):
            server.start_star_af()

    def test_refused_without_live_view(self):
        self._setup_cam(live_on=False)
        with self.assertRaises(CameraError):
            server.start_star_af()

    def test_refused_in_saf_and_caf_modes(self):
        for bad_fm in ("2", "32770"):
            self._setup_cam(fm=bad_fm)
            with self.assertRaises(CameraError) as ctx:
                server.start_star_af()
            self.assertIn("MF", str(ctx.exception))

    def test_refused_in_movie_mode_and_bad_priority(self):
        self._setup_cam(mode="movie")
        with self.assertRaises(CameraError) as ctx:
            server.start_star_af()
        self.assertIn("photo", str(ctx.exception))
        self._setup_cam(mode="M")
        with self.assertRaises(CameraError) as ctx:
            server.start_star_af(priority="turbo")
        self.assertIn("priority", str(ctx.exception))

    def test_accuracy_priority_uses_more_frames_and_longer_settle(self):
        self._setup_cam(fm="1", mode="M")
        seen = {}
        orig_init = star_af.AutoStarAF.__init__
        def spy_init(af_self, *args, **kwargs):
            seen["frames_per_step"] = kwargs.get("frames_per_step")
            seen["settle_s"] = kwargs.get("settle_s")
            orig_init(af_self, *args, **kwargs)
        with mock.patch.object(star_af.AutoStarAF, "__init__", spy_init), \
             mock.patch.object(star_af.AutoStarAF, "run", return_value={"phase": "done", "message": "Focused"}):
            server.start_star_af(x=0.5, y=0.5, zoom=False, boost=False, priority="accuracy")
            for _ in range(100):
                if not server.star_af_state["running"]:
                    break
                threading.Event().wait(0.01)
        self.assertEqual(server.star_af_state["priority"], "accuracy")
        self.assertEqual((seen["frames_per_step"], seen["settle_s"]), star_af.PRIORITIES["accuracy"])

    def test_usb_and_wifi_expose_star_af_feature(self):
        self.assertIn("star_af", usb_camera.FEATURES)
        self.assertIn("star_af", server.WIFI_FEATURES)

    def test_star_af_endpoint_works_from_phone_without_local_gate(self):
        # /api/staraf must work over --lan from a phone (unlike /api/pickfolder which calls _local())
        src = Path(server.__file__).read_text(encoding="utf-8")
        block = src[src.index('elif path == "/api/staraf":'):][:300]
        self.assertNotIn("_local()", block)

    def test_auto_star_af_boosts_finds_star_switches_to_mf_and_restores_boost(self):
        cam, live = self._setup_cam(fm="32769", mode="A")  # S-AF+MF; boost acts in P/A/S only
        boost_calls = []
        def set_lv_boost(val):
            boost_calls.append(val)
            return 2 if len(boost_calls) == 1 else 3
        cam.set_lv_boost.side_effect = set_lv_boost
        # Off-center star for full-frame scan, then centered sharp star while zoomed
        off_jpg = to_jpeg(make_star_frame(w=240, h=180, sx=180.0, sy=120.0, sigma=2.0, peak=180.0))
        ctr_jpg = to_jpeg(make_star_frame(w=240, h=180, sx=120.0, sy=90.0, sigma=1.4, peak=190.0))
        frames = [off_jpg] + [ctr_jpg] * 30
        live.wait_frame.side_effect = lambda seq, timeout=1.5: (seq + 1, frames.pop(0) if frames else ctr_jpg, (0, 0))

        with mock.patch.object(server.stop_job, "wait", return_value=False), \
             mock.patch.object(star_af.AutoStarAF, "run", return_value={"phase": "done", "message": "Focused · HFR 1.40 px"}):
            server.start_star_af(x=None, y=None, zoom=True, boost=True)
            for _ in range(100):
                if not server.star_af_state["running"]:
                    break
                threading.Event().wait(0.01)

        self.assertEqual(boost_calls, [3, 2])  # On2 during Star AF, restored to Off in finally
        self.assertEqual(cam.loupe.call_count, 2)  # Zoom AF x10 on, then explicitly off in finally
        _, ratio, lx, ly = cam.loupe.call_args_list[0][0]
        self.assertEqual(ratio, 10)
        self.assertAlmostEqual(lx, 180.0 / 240.0, delta=0.05)
        self.assertAlmostEqual(ly, 120.0 / 180.0, delta=0.05)
        self.assertEqual(cam.loupe.call_args_list[1][0], (False,))
        cam.set_prop.assert_called_with("focusmode", "1")
        self.assertTrue(server.star_af_state["switched_to_mf"])
        self.assertFalse(server.star_af_state["boost_on"])

    def test_ensure_idle_blocks_while_star_af_running(self):
        self._setup_cam()
        server.star_af_state["running"] = True
        with self.assertRaises(CameraError):
            server.ensure_idle()

    def test_concurrent_start_refused_without_race(self):
        self._setup_cam()
        gate = threading.Event()
        entered = threading.Event()
        def slow_run(af_self):
            entered.set()
            gate.wait(2.0)
            return {"phase": "stopped", "code": "stopped", "message": "Star AF stopped"}
        with mock.patch.object(star_af.AutoStarAF, "run", slow_run):
            server.start_star_af(x=0.5, y=0.5, zoom=False, boost=False)
            self.assertTrue(entered.wait(1.0))
            with self.assertRaises(CameraError):
                server.start_star_af(x=0.5, y=0.5, zoom=False, boost=False)
            gate.set()
            if server.star_af_thread:
                server.star_af_thread.join(timeout=2.0)

    def test_disconnect_stops_runner_and_restores_loupe_and_boost(self):
        cam, _ = self._setup_cam(mode="A")  # boost acts in P/A/S only
        boost_calls = []
        def set_lv_boost(val):
            boost_calls.append(val)
            return 2 if len(boost_calls) == 1 else 3
        cam.set_lv_boost.side_effect = set_lv_boost
        in_run = threading.Event()
        def blocking_run(af_self):
            in_run.set()
            server.stop_job.wait(2.0)
            return {"phase": "stopped", "code": "stopped", "message": "Star AF stopped"}
        with mock.patch.object(server.stop_job, "wait", side_effect=[False, False, True]), \
             mock.patch.object(star_af.AutoStarAF, "run", blocking_run):
            server.start_star_af(x=0.5, y=0.5, zoom=True, boost=True)
            self.assertTrue(in_run.wait(1.0))
            server.disconnect()
        self.assertEqual(boost_calls, [3, 2])
        self.assertEqual(cam.loupe.call_args_list[-1][0], (False,))
        cam.close.assert_called_once()


class PageMarkup(unittest.TestCase):
    def test_star_af_controls_and_i18n_keys_present(self):
        h = HTML.read_text(encoding="utf-8")
        for frag in ('id="starAfOn"', 'id="starAfLab"', 'id="starRow"', 'id="starPrio"',
                     'id="starHfr"', 'id="starBest"', 'id="starHyp"', 'id="starLock"',
                     'id="starLockLab"', 'id="starReset"', 'id="starAuto"',
                     'data-feat="star_af"', 'data-feat="mf_drive"', "lvboost:{show:inMode('P','A','S')}"):
            self.assertIn(frag, h)
        self.assertNotIn('id="rowStar"', h)
        self.assertNotIn('#starPanelAuto', h)
        self.assertRegex(h, r"if\(isStarActive\(\)\)|curFm\(\)==='1'")  # grid hidden with Star AF and in MF (user 2026-11-23)
        for key in ("lv.starAf", "star.auto", "star.stop", "star.speed", "star.accuracy",
                    "star.prioAria", "star.prioHint", "star.lock", "star.hfrTitle",
                    "star.hfr", "star.hfrClip", "star.best", "star.hyp", "star.noStar",
                    "star.tooBright", "star.reset", "star.manualHint", "star.needMf",
                    "star.running", "star.boostNote", "star.inFocus", "star.inFocusMf",
                    "star.noFocus", "star.stopped", "prop.lvboost"):
            self.assertIn('"%s":' % key, h)
        self.assertIn("'/api/staraf'", h)



class ReReviewFixes(unittest.TestCase):
    """Re-review 2026-11-23: stop only stops Star AF; the Wi-Fi refusal is plain words."""

    def test_stop_does_not_touch_other_jobs(self):
        from omcap import server
        from unittest import mock
        server.stop_job.clear()
        server.star_af_state["running"] = False
        h = server.Handler.__new__(server.Handler)
        with mock.patch.object(server, "cam", mock.MagicMock()):
            h._action("/api/staraf", {"action": "stop"})
        self.assertFalse(server.stop_job.is_set())  # a running series or time-lapse keeps going

    def test_boost_only_in_p_a_s(self):
        src = open(server_path()).read()
        self.assertIn('cam_ref.take_mode() in ("P", "A", "S")', src)


def server_path():
    import os
    from omcap import server
    return os.path.join(os.path.dirname(server.__file__), "server.py")


if __name__ == "__main__":
    unittest.main()
