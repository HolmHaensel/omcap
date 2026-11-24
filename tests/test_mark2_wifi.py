"""E-M1 Mark II over Wi-Fi: the property table only answers in REC mode, and the card error sentinel.

Both were found on the body on 2026-11-24 (tools/mk2/wifi-results.md); the camera answers 520/1001 for
`get_camprop` while it is in playback, and 0xFFFFFFFF for `get_unusedcapacity` before the card is mounted.
"""
import unittest
from unittest import mock

from omcap.camera import Camera, CameraError, parse_capacity

PROPS_XML = (b'<?xml version="1.0"?><desclist><desc><propname>takemode</propname>'
             b'<attribute>getset</attribute><value>P</value><enum>P A S M</enum></desc></desclist>')


def camera(allow_write):
    return Camera(host="127.0.0.1", timeout=0.1, allow_write=allow_write)


class PropsOnlyInRecMode(unittest.TestCase):
    def test_read_only_says_how_to_get_the_settings(self):
        cam = camera(False)
        with mock.patch.object(cam, "get", side_effect=CameraError("get_camprop.cgi: 520", 520)):
            with self.assertRaises(CameraError) as ctx:
                cam.props()
        self.assertIn("shooting mode", str(ctx.exception))
        self.assertEqual(ctx.exception.code, 520)

    def test_switches_to_rec_and_reads_again_when_writing_is_allowed(self):
        cam = camera(True)
        replies = [CameraError("get_camprop.cgi: 520", 520), PROPS_XML]

        def get(cgi, **query):
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

        with mock.patch.object(cam, "get", side_effect=get), mock.patch.object(cam, "set_mode") as set_mode:
            props = cam.props()
        set_mode.assert_called_once_with("rec", None)
        self.assertEqual(props["takemode"], {"value": "P", "writable": True, "enum": ["P", "A", "S", "M"]})

    def test_does_not_switch_mode_while_the_shutter_is_pressed(self):
        cam = camera(True)
        cam.stage = 1  # half press held: a mode switch would drop it
        with mock.patch.object(cam, "get", side_effect=CameraError("get_camprop.cgi: 520", 520)), \
                mock.patch.object(cam, "set_mode") as set_mode:
            with self.assertRaises(CameraError):
                cam.props()
        set_mode.assert_not_called()

    def test_other_errors_are_not_retried(self):
        cam = camera(True)
        with mock.patch.object(cam, "get", side_effect=CameraError("get_camprop.cgi: 404", 404)), \
                mock.patch.object(cam, "set_mode") as set_mode:
            with self.assertRaises(CameraError):
                cam.props()
        set_mode.assert_not_called()


class CardCapacity(unittest.TestCase):
    def test_error_sentinel_is_not_a_capacity(self):
        self.assertIsNone(parse_capacity("<unusedcapacity>4294967295</unusedcapacity>"))
        self.assertIsNone(parse_capacity("18446744073709551615"))

    def test_real_values_still_work(self):
        self.assertEqual(parse_capacity("<unusedcapacity>7000</unusedcapacity>"), 7000)
        self.assertEqual(parse_capacity("0"), 0)  # a full card is an answer, not an error


if __name__ == "__main__":
    unittest.main()
