"""RTP header extension of the Wi-Fi live view (Olympus OPC protocol 1.0a), synthetic packets."""
import struct
import unittest

from omcap import liveview


def entry(fid, *words):
    return struct.pack(">HH", fid, len(words)) + b"".join(struct.pack(">I", w) for w in words)


class Extension(unittest.TestCase):
    def test_parse_and_decode(self):
        ext = (entry(3, 0b100101) + entry(5, 1234) + entry(107, (3 << 16) | 0, 0xFFF6, 25)
               + entry(108, (100 << 16) | 50, (40 << 16) | 30) + entry(2, 1, 10, 20, 30, 40) + entry(999, 7))
        e = liveview.parse_extension(ext)
        self.assertEqual(sorted(e), [2, 3, 5, 107, 108, 999])
        card = liveview.decode_entry(3, e[3])
        self.assertTrue(card["mount_state"] == 1 and card["not_full"] and card["writing"])
        self.assertEqual(liveview.decode_entry(5, e[5]), 1234)
        lvl = liveview.decode_entry(107, e[107])
        self.assertEqual((lvl["roll"], lvl["pitch"], lvl["reliable_roll"], lvl["reliable_pitch"]), (-10, 25, True, True))
        self.assertEqual(liveview.decode_entry(108, e[108]), {"x": 100, "y": 50, "w": 40, "h": 30})
        self.assertEqual(liveview.decode_entry(2, e[2])["result"], 1)
        self.assertIsNone(liveview.decode_entry(999, e[999]))  # unknown IDs stay raw

    def test_em1_layouts(self):
        # words recorded from a real E-M1 Mark I (FW 4.6) with a 14-140 mm lens
        d = liveview.decode_entry
        self.assertEqual(d(9, [220, 44, 45]), {"max": 22.0, "open": 4.4, "now": 4.5})
        self.assertEqual(d(10, [50, 4294967246, 0]), {"max": 5.0, "min": -5.0, "now": 0.0})
        self.assertEqual(d(12, [1600, 65536, 0]), {"now": 1600})
        self.assertEqual(d(18, [524302, 4259980, 0]), {"min_mm": 14, "max_mm": 140, "now_mm": 65})
        self.assertAlmostEqual(d(8, [3932161, 73536, 65596])["now"], 1 / 60)

    def test_live_values(self):
        lv = liveview.LiveView()
        self.assertIsNone(lv.live_values())  # not running
        lv._run, lv.last_frame = True, liveview.time.monotonic()
        lv.ext = {5: [1226], 12: [1600, 65536, 0], 8: [3932161, 73536, 65596], 9: [220, 44, 45],
                  18: [524302, 4259980, 0], 2: [1, 352, 340, 90, 90]}
        self.assertEqual(lv.live_values(), {"shots": 1226, "iso": 1600, "shutter": [1, 60], "aperture": 4.5,
                                            "focal": [14, 140, 65], "af": 1})
        lv.last_frame -= 10  # stale frames: no values
        self.assertIsNone(lv.live_values())

    def test_truncated_is_safe(self):
        self.assertEqual(liveview.parse_extension(entry(5, 1)[:6]), {5: []})


if __name__ == "__main__":
    unittest.main()
