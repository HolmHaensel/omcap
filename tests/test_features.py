"""USB/Wi-Fi parity of the feature flags in one table (the page shows a control only where its flag is set)."""
import unittest

from omcap import server, usb_camera

# feature: (USB, Wi-Fi). A new flag must be added here, with the reason why one connection lacks it.
PARITY = {
    "liveview": (True, True), "af_area": (True, True), "stages": (True, True), "scp": (True, True),
    "time_lapse": (True, True), "ae_bkt": (True, True), "movie": (True, True), "long": (True, True),
    "playback": (True, True), "transfer": (True, True), "star_af": (True, True),
    "af_modes": (True, False),
    "mf_drive": (True, False),     # PTP 0x9487, no Wi-Fi command
    "erase": (True, False),        # card erase over PTP only
    "loupe": (True, False),        # camera Zoom AF over PTP; Wi-Fi zooms on the screen (REQ-F55)
    "lvsize": (False, True),       # USB adds it per camera when libgphoto2 can set the size (test_usb_lvsize)
    "share_order": (False, True),  # Wi-Fi share order CGI
    "poweroff": (False, True),     # Wi-Fi turn-off CGI
    "focus_tone": (False, True),   # tone after Wi-Fi tap AF
}


class Parity(unittest.TestCase):
    def test_table_matches_both_connections(self):
        self.assertEqual(set(usb_camera.FEATURES), {f for f, (u, _) in PARITY.items() if u})
        self.assertEqual(set(server.WIFI_FEATURES), {f for f, (_, w) in PARITY.items() if w})


if __name__ == "__main__":
    unittest.main()
