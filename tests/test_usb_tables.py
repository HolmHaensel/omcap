"""USB Super Control Panel values mapped on the camera (2026-11-13)."""
import unittest

from omcap import usb_camera


class Tables(unittest.TestCase):
    def test_aspect(self):
        self.assertEqual(usb_camera._aspect_names(["262147", "1048585", "196610", "65537"]),
                         {"262147": "4:3", "1048585": "16:9", "196610": "3:2", "65537": "1:1"})

    def test_only_mapped_values_named(self):
        names = usb_camera._table_names("d003")(["2", "32770", "1", "32769", "99"])
        self.assertEqual(names, {"2": "S-AF", "32770": "C-AF", "1": "MF", "32769": "S-AF+MF"})

    def test_confirmed_values(self):
        t = usb_camera.USB_TABLES
        self.assertEqual((t["d004"]["2"], t["d00d"]["290"], t["d01a"]["32772"], t["d005"]["2"]),
                         ("Center weighted", "LN+RAW", "Face & L. Eye Priority On", "Flash Off"))


if __name__ == "__main__":
    unittest.main()
