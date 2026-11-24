"""Save to panel (REQ-F62): folder dialog endpoint, card flag in the state, page logic. No camera, no dialog."""
import json
import os
import re
import shutil
import subprocess
import threading
import unittest
from pathlib import Path
from email.message import Message
from unittest import mock

from omcap import server, usb_camera

from tests.web_path import HTML_PATH as HTML
HAVE_JS = shutil.which("osascript")


def handler(client, host="127.0.0.1:8765"):
    h = server.Handler.__new__(server.Handler)
    h.client_address = (client, 50000)
    h.headers = Message()
    h.headers["Host"] = host
    return h


def run(args, out="", err="", code=0):
    return mock.patch.object(server.subprocess, "run",
                             return_value=subprocess.CompletedProcess(args, code, out, err))


class Dialog(unittest.TestCase):
    def test_macos_uses_a_fixed_argument_list(self):
        with mock.patch.object(server.sys, "platform", "darwin"), run([], out="/Users/x/Pictures/\n") as r:
            self.assertEqual(server.pick_folder_dialog(), "/Users/x/Pictures/")  # validate_save_dir normalises
        cmd = r.call_args[0][0]
        self.assertEqual(cmd[:2], ["osascript", "-e"])
        self.assertIn('tell application "System Events" to activate', cmd)  # dialog comes to the front
        self.assertLess(cmd.index('tell application "System Events" to activate'),
                        next(i for i, a in enumerate(cmd) if "choose folder" in a))
        self.assertNotIn("shell", r.call_args[1])
        self.assertEqual(r.call_args[1]["encoding"], "utf-8")

    def test_osascript_error_other_than_cancel_is_reported(self):
        with mock.patch.object(server.sys, "platform", "darwin"), \
                run([], err="Not authorised to send Apple events to System Events. (-1743)", code=1):
            with self.assertRaises(ValueError) as e:
                server.pick_folder_dialog()
        self.assertIn("-1743", str(e.exception))

    def test_cancel_is_empty_not_an_error(self):
        with mock.patch.object(server.sys, "platform", "darwin"), \
                run([], err="execution error: User canceled. (-128)", code=1):
            self.assertEqual(server.pick_folder_dialog(), "")

    def test_failure_is_an_error(self):
        with mock.patch.object(server.sys, "platform", "darwin"), run([], err="boom", code=2):
            with self.assertRaises(ValueError):
                server.pick_folder_dialog()

    def test_linux_without_zenity(self):
        with mock.patch.object(server.sys, "platform", "linux"), mock.patch.object(server.shutil, "which", return_value=None):
            with self.assertRaises(ValueError) as e:
                server.pick_folder_dialog()
        self.assertIn("type the folder", str(e.exception))

    def test_linux_zenity(self):
        with mock.patch.object(server.sys, "platform", "linux"), \
                mock.patch.object(server.shutil, "which", return_value="/usr/bin/zenity"), run([], out="/home/a/pics\n") as r:
            self.assertEqual(server.pick_folder_dialog(), "/home/a/pics")
        self.assertEqual(r.call_args[0][0][:3], ["zenity", "--file-selection", "--directory"])

    def test_windows_powershell(self):
        with mock.patch.object(server.sys, "platform", "win32"), run([], out="C:\\Pics\\\r\n") as r:
            self.assertEqual(server.pick_folder_dialog(), "C:\\Pics\\")
        self.assertEqual(r.call_args[0][0][0], "powershell")
        self.assertIn("[Console]::OutputEncoding=[Text.Encoding]::UTF8;", r.call_args[0][0][-1])
        self.assertEqual(r.call_args[1]["encoding"], "utf-8")

    def test_second_dialog_is_refused(self):
        with mock.patch.object(server.sys, "platform", "darwin"):
            self.assertTrue(server._dialog_lock.acquire(blocking=False))
            try:
                with self.assertRaises(ValueError):
                    server.pick_folder_dialog()
            finally:
                server._dialog_lock.release()


class Endpoint(unittest.TestCase):
    def test_local_request_gets_the_folder(self):
        with mock.patch.object(server, "pick_folder_dialog", return_value="/Users/x/Pictures") as d:
            self.assertEqual(handler("127.0.0.1")._action("/api/pickfolder", {}), {"dir": "/Users/x/Pictures"})
        d.assert_called_once()

    def test_cancel_returns_empty(self):
        with mock.patch.object(server, "pick_folder_dialog", return_value=""):
            self.assertEqual(handler("::1")._action("/api/pickfolder", {}), {"dir": ""})

    def test_phone_never_opens_a_dialog(self):
        with mock.patch.object(server, "pick_folder_dialog") as d:
            with self.assertRaises(server.Forbidden):
                handler("192.168.178.50", host="192.168.178.39:8765")._action("/api/pickfolder", {})
        d.assert_not_called()

    def test_no_dialog_possible_is_an_error_answer(self):
        h = handler("127.0.0.1")
        h.path, sent = "/api/pickfolder", []
        h._body = lambda: {}
        h._send = lambda obj, *a, **k: sent.append((obj, k.get("code")))
        h._lan_ok = lambda: True
        with mock.patch.object(server, "allowed_hosts", {"127.0.0.1:8765"}), \
                mock.patch.object(server, "pick_folder_dialog", side_effect=ValueError("No folder dialog")):
            h.do_POST()
        self.assertEqual(sent, [({"error": "No folder dialog"}, 502)])

    def test_phone_gets_403_through_post(self):
        h = handler("192.168.178.50", host="192.168.178.39:8765")
        h.path, sent = "/api/pickfolder", []
        h._body = lambda: {}
        h._send = lambda obj, *a, **k: sent.append(k.get("code"))
        h._trusted = lambda: True  # a phone with a valid key is trusted for the camera, not for dialogs
        with mock.patch.object(server, "pick_folder_dialog") as d:
            h.do_POST()
        d.assert_not_called()
        self.assertEqual(sent, [403])


    def test_real_permission_error_elsewhere_stays_502(self):
        h = handler("127.0.0.1")
        h.path, sent = "/api/savecfg", []
        h._body = lambda: {}
        h._send = lambda obj, *a, **k: sent.append(k.get("code"))
        h._trusted = lambda: True
        with mock.patch.object(server, "set_save_cfg", side_effect=PermissionError("EACCES")):
            h.do_POST()
        self.assertEqual(sent, [502])


class CardFlag(unittest.TestCase):
    def setUp(self):
        class Live:
            running, age = False, 0
        self.saved = (server.cam, server.conn_type, server.live)
        server.live = Live()

        def restore():
            server.cam, server.conn_type, server.live = self.saved
        self.addCleanup(restore)

    def usb(self, card_state):
        c = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)
        c.stage, c.lvqty = 0, "0320x0240"
        c.card, c._card_state = None, mock.Mock(return_value=card_state)
        return c

    def test_state_per_card_situation(self):
        server.conn_type = "usb"
        for flag in (True, False, None):
            server.cam = self.usb(flag)
            server.cam.refresh_card()
            self.assertIs(server.public_state()["card"], flag)

    def test_state_does_not_read_the_camera(self):
        server.conn_type, server.cam = "usb", self.usb(False)
        server.cam.refresh_card()
        for _ in range(3):
            server.public_state()
        server.cam._card_state.assert_called_once()  # only the refresh asked

    def test_wifi_has_no_card_flag(self):
        server.conn_type = "wifi"
        server.cam = mock.Mock(card=False, stage=0, lvqty="0320x0240")  # even a stray attribute must not leak
        self.assertIsNone(server.public_state()["card"])

    def test_card_state_codes(self):
        c = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)
        c._call = lambda f, *a: f(*a)
        c._c = mock.Mock(get_storageinfo=mock.Mock(side_effect=Exception("PTP 0x2013 StoreNotAvailable")))
        self.assertIs(c._card_state(), False)
        c._c = mock.Mock(get_storageinfo=mock.Mock(side_effect=Exception("timeout")))
        self.assertIsNone(c._card_state())

    def test_free_space_read_corrects_a_stale_no_card(self):
        # USB test 2026-11-22: 0x2013 right after the connect left "no card" although a card was in
        c = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)
        c._call = lambda f, *a: f(*a)
        c.card = False
        with mock.patch.object(usb_camera, "free_kbytes", return_value=7579488):
            c._c = mock.Mock()
            self.assertEqual(c.free_bytes(), 7579488 * 1024)
        self.assertIs(c.card, True)
        c._c = mock.Mock(get_storageinfo=mock.Mock(side_effect=Exception("PTP 0x2013")))
        with self.assertRaises(Exception):
            c.free_bytes()
        self.assertIs(c.card, False)
        c.card = True
        c._c = mock.Mock(get_storageinfo=mock.Mock(side_effect=Exception("timeout")))
        with self.assertRaises(Exception):
            c.free_bytes()
        self.assertIs(c.card, True)  # unknown errors keep the flag

    def test_refresh_after_each_shot(self):
        server.conn_type = "usb"
        server.cam = mock.Mock(shoot=mock.Mock(return_value=[]), take_direct_files=mock.Mock(return_value=[]))
        with mock.patch.object(server, "invalidate_device"):
            server.shot(None)
        server.cam.refresh_card.assert_called_once()

    def test_refresh_after_held_release_and_time_exposure_stop(self):
        server.conn_type = "usb"
        server.cam = mock.Mock(stage=0, take_new_files=mock.Mock(return_value=[]),
                               take_direct_files=mock.Mock(return_value=[]))
        server._state_backup = dict(server.state)
        self.addCleanup(lambda: server.state.update(server._state_backup))
        server.state["transfer"] = "sd"
        server.Handler.__new__(server.Handler)._shutter(0)
        server.cam.refresh_card.assert_called_once()
        server.cam.reset_mock()
        h = handler("127.0.0.1")
        h._action("/api/take", {"action": "stop"})
        server.cam.refresh_card.assert_called_once()

    def test_pre_release_read_is_reused_not_repeated(self):
        c = self.usb(False)
        c.on_direct_file, c._c = mock.Mock(), mock.Mock(omd_direct_info=1)
        c._stacking_on = lambda: False
        c._save_leftover = lambda: None
        c._pre_release()
        self.assertIs(c.card, False)
        c.refresh_card()  # after the shot: reuses the read of the release
        c._card_state.assert_called_once()
        c.refresh_card()  # the next one reads again
        self.assertEqual(c._card_state.call_count, 2)


class Page(unittest.TestCase):
    def setUp(self):
        self.h = Path(HTML).read_text(encoding="utf-8")

    def test_markup_and_text(self):
        for frag in ('id="svDir"', 'id="trCopy"', 'data-i18n="hsl.autoHint"'):
            self.assertIn(frag, self.h)
        for key in ("transfer.copy", "save.pickTitle"):
            self.assertRegex(self.h, r'"%s": "' % re.escape(key))

    def test_button_only_on_the_local_page(self):
        # user 2026-11-23: on the computer a click into the folder field opens the dialog; no Choose/Apply buttons
        self.assertIn("if(isLocalPage()){", self.h)
        self.assertIn("$('#svDir').onchange=svSave;", self.h)
        self.assertIn("dir:dirValue()", self.h)  # the server gets the full path, the field shows a short one

    def test_switch_sends_the_choice(self):
        self.assertIn("{target:$('#trCopy').checked?'both':'sd'}", self.h)


def page_js(scenario):
    h = Path(HTML).read_text(encoding="utf-8")
    code = h[h.index("function transferView("):h.index("// Every change applies at once")]
    stubs = """
var isUsb=true,els={},document={activeElement:null},tr=function(k){return k},
  Q=function(s){return els[s]||(els[s]={checked:false,hidden:false})};
['#trCopy','#trCopyLbl','#trNoCardNote'].forEach(Q);
"""
    out = subprocess.run(["osascript", "-l", "JavaScript", "-e",
                          stubs + code.replace("$(", "Q(") + scenario],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip())


@unittest.skipUnless(HAVE_JS, "needs the JavaScript engine of macOS (osascript)")
class PageLogic(unittest.TestCase):
    def view(self, usb, card, pref):
        return page_js("isUsb=%s; var st={card:%s,transfer:'%s'}; applyTransferView(st);"
                       "JSON.stringify({checked:els['#trCopy'].checked,hiddenSwitch:els['#trCopyLbl'].hidden,"
                       "block:trNoCard,note:els['#trNoCardNote'].hidden})"
                       % (str(usb).lower(), json.dumps(card), pref))

    def test_usb_without_card(self):
        r = self.view(True, False, "both")  # no switch, only the note; the saved choice stays
        self.assertEqual((r["hiddenSwitch"], r["note"], r["block"], r["checked"]), (True, False, True, True))

    def test_usb_with_card_keeps_the_choice(self):
        r = self.view(True, True, "sd")
        self.assertEqual((r["hiddenSwitch"], r["note"], r["block"], r["checked"]), (False, True, False, False))
        self.assertTrue(self.view(True, True, "both")["checked"])

    def test_unknown_card_state_is_like_a_card(self):
        r = self.view(True, None, "both")
        self.assertEqual((r["hiddenSwitch"], r["note"], r["checked"]), (False, True, True))

    def test_wifi_never_changes(self):
        r = self.view(False, False, "sd")  # a stray flag over Wi-Fi is ignored
        self.assertEqual((r["hiddenSwitch"], r["note"], r["checked"]), (False, True, False))


@unittest.skipUnless(HAVE_JS, "needs the JavaScript engine of macOS (osascript)")
class ShortPath(unittest.TestCase):
    def sp(self, p):
        h = Path(HTML).read_text(encoding="utf-8")
        code = h[h.index("function shortPath("):h.index("// show the end of the path")]
        out = subprocess.run(["osascript", "-l", "JavaScript", "-e",
                              code + "JSON.stringify(shortPath(%s))" % json.dumps(p)],
                             capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout.strip())

    def test_cases(self):
        self.assertEqual(self.sp("/Users/x"), "~")
        self.assertEqual(self.sp("/Users/x/Pictures/omcap"), "~/Pictures/omcap")
        self.assertEqual(self.sp("/Users/x/a/b/c"), "~/a/b/c")
        self.assertEqual(self.sp("/Users/x/Library/CloudStorage/Drive/Personal/PROJ/captures"),
                         "~/Library/…/PROJ/captures")
        self.assertEqual(self.sp("/Volumes/Disk/a/b/c/d"), "/Volumes/…/c/d")
        self.assertEqual(self.sp("/tmp/x"), "/tmp/x")


class CardSettle(unittest.TestCase):
    def cam(self, states):
        c = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)
        c.CARD_SETTLE = (0, 0, 0)
        c._card_state = mock.Mock(side_effect=states)
        return c

    def test_card_that_is_not_ready_yet_counts_as_card(self):
        # USB test 2026-11-22: after a card change the camera answered 0x2013 although the card was in
        c = self.cam([False, False, True])
        self.assertIs(c._card_state_settled(), True)

    def test_no_card_after_all_tries(self):
        c = self.cam([False] * 4)
        self.assertIs(c._card_state_settled(), False)
        self.assertEqual(c._card_state.call_count, 4)

    def test_card_present_reads_once(self):
        c = self.cam([True])
        self.assertIs(c._card_state_settled(), True)
        c._card_state.assert_called_once()


class CardReviewFixes(unittest.TestCase):
    def test_settle_runs_after_the_lock(self):
        c = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)
        c._lock = threading.Lock()
        seen = []
        c._card_state_settled = lambda: seen.append(c._lock.locked()) or True

        def reopen_locked(reason):
            c._card_due = True
            return True
        c._reopen_locked = reopen_locked
        self.assertTrue(c.reopen("test"))
        self.assertEqual(seen, [False])  # read without holding the camera lock
        self.assertIs(c.card, True)

    def test_failed_release_clears_the_card_read(self):
        c = usb_camera.UsbCamera.__new__(usb_camera.UsbCamera)
        c._card_read = True
        c._shoot = mock.Mock(side_effect=usb_camera.CameraError("x"))
        with self.assertRaises(usb_camera.CameraError):
            c.shoot()
        self.assertIs(c._card_read, False)

    @unittest.skipUnless(HAVE_JS, "needs the JavaScript engine of macOS (osascript)")
    def test_no_card_hides_focus_stacking_and_rec(self):
        h = Path(HTML).read_text(encoding="utf-8")
        show = re.search(r"focusstacking:\{show:(.*?)\}, //", h).group(1)
        in_mode = re.search(r"const inMode=[^\n]*", h).group(0)
        code = ("%s\nvar show=%s,out=[];[['M',false],['M',true],['ART',false]].forEach(function(c){"
                "trNoCard=c[1];out.push(show({takemode:{value:c[0]}}))});JSON.stringify(out)" % (in_mode, show))
        out = subprocess.run(["osascript", "-l", "JavaScript", "-e", "var trNoCard;" + code],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout.strip()), [True, False, False])  # no card: no focus stacking
        self.assertIn("$('#movStart').hidden=rec||trNoCard;", h)



class LocalOnly(unittest.TestCase):
    """Audit 2026-11-22: a phone over --lan must not quit the app or open programs on the computer."""

    def test_quit_and_open_refused_from_the_lan(self):
        for path, body in (("/api/quit", {}), ("/api/open", {"name": "P1.ORF"})):
            with mock.patch.object(server, "disconnect") as d, mock.patch.object(server.subprocess, "run") as r:
                with self.assertRaises(server.Forbidden):
                    handler("192.168.1.20")._action(path, body)
                d.assert_not_called()
                r.assert_not_called()



@unittest.skipUnless(HAVE_JS, "needs the JavaScript engine of macOS (osascript)")
class PhoneHidesLocalActions(unittest.TestCase):
    def test_quit_and_workspace_hidden_off_the_computer(self):
        h = Path(HTML).read_text(encoding="utf-8")
        local = re.search(r"function isLocalPage\(\)[^\n]*", h).group(0)
        quit_line = re.search(r"document\.querySelectorAll\('\.quitBtn'\)\.forEach\(b=>b\.hidden=[^\n]*", h).group(0)
        ws = re.search(r"\$\('#vWs'\)\.hidden=([^;]*);", h).group(1)
        out = []
        for host in ("127.0.0.1", "localhost", "192.168.1.20"):
            code = ("var location={hostname:'%s'},btn={hidden:null},document={querySelectorAll:function(){return [btn]}};"
                    "%s\n%s\nvar s={om_workspace:true};JSON.stringify([btn.hidden,%s])" % (host, local, quit_line, ws))
            r = subprocess.run(["osascript", "-l", "JavaScript", "-e", code], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            out.append(json.loads(r.stdout.strip()))
        self.assertEqual(out, [[False, False], [False, False], [True, True]])  # the phone sees neither


if __name__ == "__main__":
    unittest.main()
