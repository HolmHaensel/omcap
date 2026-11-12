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
        self.assertTrue(card["mounted"] and card["not_full"] and card["writing"])
        self.assertEqual(liveview.decode_entry(5, e[5]), 1234)
        lvl = liveview.decode_entry(107, e[107])
        self.assertEqual((lvl["roll"], lvl["pitch"], lvl["reliable_roll"], lvl["reliable_pitch"]), (-10, 25, True, True))
        self.assertEqual(liveview.decode_entry(108, e[108]), {"x": 100, "y": 50, "w": 40, "h": 30})
        self.assertEqual(liveview.decode_entry(2, e[2])["result"], 1)
        self.assertIsNone(liveview.decode_entry(999, e[999]))  # unknown IDs stay raw

    def test_truncated_is_safe(self):
        self.assertEqual(liveview.parse_extension(entry(5, 1)[:6]), {5: []})


if __name__ == "__main__":
    unittest.main()
