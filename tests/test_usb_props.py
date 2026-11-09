"""USB value listener: read and compare the summary (no camera)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import usb_props  # noqa: E402

SAMPLE = """Properties des Geräts:
Batterie Ladezustand      (5001 ro u8 ): Range [1 - 100, step 1] value: 80% (80)
  Seriennummer: XYZ1234567
[Unknown Property]        (d00c rw u16): Enumeration [33024,33025,33027,33026] value: 33024
[Unknown Property]        (d405 ro [u8 ]): a[71680] 0,0,1,0
[Unknown Property]        (d406 rw str): 'Windows/6.0'
"""


class Parse(unittest.TestCase):
    def test_fields_and_no_serial(self):
        p = usb_props.parse_summary(SAMPLE)
        self.assertEqual(set(p), {"5001", "d00c", "d405", "d406"})
        self.assertEqual(p["d00c"]["value"], "33024")
        self.assertEqual(p["d405"]["value"], "(array)")
        self.assertNotIn("XYZ1234567", str(p))

    def test_diff(self):
        a = usb_props.parse_summary(SAMPLE)
        b = usb_props.parse_summary(SAMPLE.replace("value: 33024", "value: 33025"))
        rows = usb_props.diff(a, b)
        self.assertEqual([(r[0], r[2], r[3]) for r in rows], [("d00c", "33024", "33025")])


if __name__ == "__main__":
    unittest.main()
