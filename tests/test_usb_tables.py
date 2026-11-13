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


class FromCameraDump(unittest.TestCase):
    """Values as libgphoto2 lists them for the E-M1 (maintainer's gphoto2 dump, 2026-11-13)."""

    def test_shutter_fractions_kept_and_named(self):
        dump = ["Composite", "65535/65533", "Bulb", "60", "32/10", "2", "13/10", "1", "10/13", "1/2", "10/25", "1/8000"]
        kept = [c for c in dump if usb_camera.SHUTTER_VALUE.fullmatch(c) and c not in usb_camera.LONG_LABELS]
        self.assertEqual(kept, ["60", "32/10", "2", "13/10", "1", "10/13", "1/2", "10/25", "1/8000"])
        self.assertEqual(usb_camera._shutter_names(kept),
                         {"60": '60"', "32/10": '3.2"', "2": '2"', "13/10": '1.3"', "1": '1"', "10/13": "1.3",
                          "1/2": "2", "10/25": "2.5", "1/8000": "8000"})

    def test_iso_by_value(self):
        self.assertEqual(usb_camera._iso_names(["Auto", "Low", "200"]), {"Auto": "AUTO", "Low": "LOW", "200": "200"})
        self.assertEqual(usb_camera._iso_names(["Low", "200"]), {"Low": "LOW", "200": "200"})

    def test_lens_limits(self):
        cam = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)
        cam._value = {"d07f": "35", "d080": "220"}.get
        self.assertEqual(cam._within_lens_limits(["1.0", "3.5", "5.6", "22", "25", "91"]), ["3.5", "5.6", "22"])
