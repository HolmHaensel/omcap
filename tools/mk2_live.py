"""First live-view test on an E-M1 Mark II over USB.

Switches the body into PC control (d052 = 1), sets a live view size, then pulls JPEG frames through
0x9484 and measures the frame rate. Frames are written to probe_out/ so they can be looked at.
At the end d052 goes back to 2 (camera control), so the body is left as it was found.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from omcap import ptp  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "probe_out")


def main():
    os.makedirs(OUT, exist_ok=True)
    t = ptp.UsbTransport()
    cam = ptp.PtpCamera(t)
    cam.open()

    before = cam.prop_desc(ptp.DPC_CONTROL_MODE)["value"]
    print("d052 before        : %s (1 = PC control, 2 = camera)" % before)
    t0 = time.monotonic()
    ok = cam.pc_mode(True)
    print("pc_mode(True)      : %s in %.2f s" % (ok, time.monotonic() - t0))
    print("d052 after         : %s" % cam.prop_desc(ptp.DPC_CONTROL_MODE)["value"])

    lv = cam.prop_desc(ptp.DPC_LV_SIZE)
    print("d06d type/enum     : %s %s" % (lv["type"], ["%dx%d" % (v >> 16, v & 0xFFFF) if v else "off"
                                                     for v in lv.get("enum", [])]))
    size = (800 << 16) | 600
    cam.set_prop(ptp.DPC_LV_SIZE, size, lv["type"])
    print("live view size set : 800x600 -> now %s" % cam.prop_desc(ptp.DPC_LV_SIZE)["value"])
    time.sleep(0.3)

    frames, sizes, saved, t0 = 0, [], 0, time.monotonic()
    marks = []
    while time.monotonic() - t0 < 5.0:
        f = cam.liveview_frame(wait=0.5)
        if not f:
            print("no frame: %s" % getattr(cam, "lv_reason", "?"))
            break
        frames += 1
        sizes.append(len(f))
        marks.append(time.monotonic())
        if saved < 3 and f[:2] == b"\xff\xd8":
            p = os.path.join(OUT, "mk2_lv_%d.jpg" % saved)
            with open(p, "wb") as fh:
                fh.write(f)
            saved += 1
    dt = (marks[-1] - marks[0]) if len(marks) > 1 else 0.0
    print("\nframes             : %d in %.2f s -> %.1f fps" % (frames, dt, (frames - 1) / dt if dt else 0))
    if sizes:
        print("jpeg size          : min %d  max %d  avg %d bytes" % (min(sizes), max(sizes), sum(sizes) // len(sizes)))
    print("saved              : %d frame(s) in %s" % (saved, os.path.abspath(OUT)))

    for p in sorted(os.listdir(OUT)):
        if p.startswith("mk2_lv_") and p.endswith(".jpg"):
            print("  %s  %d bytes" % (p, os.path.getsize(os.path.join(OUT, p))))

    cam.set_prop(ptp.DPC_LV_SIZE, 0, lv["type"])  # live view off
    cam.pc_mode(False)
    print("d052 restored      : %s" % cam.prop_desc(ptp.DPC_CONTROL_MODE)["value"])
    cam.close()
    return 0 if frames else 2


if __name__ == "__main__":
    sys.exit(main())
