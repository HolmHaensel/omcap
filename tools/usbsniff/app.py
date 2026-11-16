"""Hook backend helpers: build the dylib, make a re-signed copy of a program, run it with the hook.

The installed program is never changed: `prepare` copies the bundle into a new folder and signs the
copy ad hoc without the hardened runtime, so macOS lets DYLD_INSERT_LIBRARIES load the hook.
Child processes started with NSTask (like OM Capture's OlyCCHelper) inherit the environment.
"""
import os
import plistlib
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(REPO, "out", "usbsniff")
DYLIB = os.path.join(WORK, "usbsniff_hook.dylib")
RECORDINGS = os.path.join(REPO, "out", "research", "usbsniff")
DEFAULT_APP = "/Applications/OM Capture.app"


def build():
    os.makedirs(WORK, exist_ok=True)
    src = os.path.join(HERE, "hook", "usbsniff_hook.m")
    subprocess.run(["clang", "-arch", "arm64", "-arch", "x86_64", "-dynamiclib", "-fobjc-arc", "-O1", "-Wall",
                    "-framework", "Foundation", "-framework", "ImageCaptureCore", src, "-o", DYLIB], check=True)
    print("built", DYLIB)


def copy_path(app):
    return os.path.join(WORK, "apps", os.path.basename(app.rstrip("/")))


def prepare(app=DEFAULT_APP):
    dst = copy_path(app)
    if os.path.exists(dst):
        print("copy exists:", dst, "(delete it yourself to make a fresh one)")
        return dst
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    subprocess.run(["ditto", app, dst], check=True)
    subprocess.run(["xattr", "-dr", "com.apple.quarantine", dst], check=False)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", dst], check=True)
    print("re-signed copy:", dst)
    return dst


def _executable(bundle):
    with open(os.path.join(bundle, "Contents", "Info.plist"), "rb") as f:
        return os.path.join(bundle, "Contents", "MacOS", plistlib.load(f)["CFBundleExecutable"])


def _busy_warnings(app):
    """The camera can only be held by one program; say what might be holding it."""
    if subprocess.run(["pgrep", "-f", app.rstrip("/") + "/"], capture_output=True).returncode == 0:
        print("warning: %s is running – quit it first" % app)
    if subprocess.run(["lsof", "-nPi", ":8765", "-sTCP:LISTEN"], capture_output=True).stdout:
        print("warning: E-M1 Capture (port 8765) is running – stop it, only one program may hold the camera")
    if subprocess.run(["pgrep", "-f", "usb_props.py"], capture_output=True).returncode == 0:
        print("warning: tools/usb_props.py is running – stop it")


def run(name, app=DEFAULT_APP, max_bytes=4096, restart_ptpcamerad=False):
    """Start the re-signed copy with the hook; waits until the program quits. Returns the log path.

    restart_ptpcamerad: stop macOS's camera service first (it starts again on demand). Seen
    2026-11-16: a ptpcamerad left over from another program's session stopped passing on the camera's
    answers, and OM Capture (original and copy) hung while connecting. Only with the user's OK."""
    if not os.path.exists(DYLIB):
        build()
    bundle = copy_path(app)
    if not os.path.exists(bundle):
        sys.exit("no copy yet – run: usbsniff hook prepare")
    if not name or os.sep in name or name.startswith("."):
        sys.exit("NAME must be a plain file name")
    os.makedirs(RECORDINGS, exist_ok=True)
    log = os.path.join(RECORDINGS, name + ".jsonl")
    if os.path.exists(log):
        sys.exit("recording exists: %s (pick another name)" % log)
    _busy_warnings(app)
    if restart_ptpcamerad:
        subprocess.run(["killall", "-9", "ptpcamerad"], capture_output=True)
    env = dict(os.environ, DYLD_INSERT_LIBRARIES=DYLIB, USBSNIFF_LOG=log, USBSNIFF_MAX=str(max_bytes))
    print("recording to", log, "– do ONE action in the program, then quit it")
    subprocess.run([_executable(bundle)], env=env)
    return log
