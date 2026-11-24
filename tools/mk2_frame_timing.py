"""Frame timing detail for one live view size: per-frame bytes and gaps, to explain the fps."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from omcap import ptp  # noqa: E402


def run(cam, w, h, dtype, seconds=3.0):
    cam.set_prop(ptp.DPC_LV_SIZE, (w << 16) | h, dtype)
    time.sleep(0.4)
    marks, sizes = [], []
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        f = cam.liveview_frame(wait=0.5)
        if not f:
            break
        marks.append(time.monotonic())
        sizes.append(len(f))
    gaps = [round((marks[i + 1] - marks[i]) * 1000) for i in range(len(marks) - 1)]
    print("%4dx%-4d frames %3d  avg gap %5.1f ms  median %5.1f ms  bytes min/med/max %d/%d/%d"
          % (w, h, len(marks), sum(gaps) / len(gaps) if gaps else 0,
             sorted(gaps)[len(gaps) // 2] if gaps else 0,
             min(sizes), sorted(sizes)[len(sizes) // 2], max(sizes)))
    print("           first gaps (ms): %s" % gaps[:14])


def main():
    cam = ptp.PtpCamera(ptp.UsbTransport())
    cam.open()
    if cam.prop_desc(ptp.DPC_CONTROL_MODE)["value"] != 1:
        cam.pc_mode(True)
    dtype = cam.prop_desc(ptp.DPC_LV_SIZE)["type"]
    for w, h in [(800, 600), (1024, 768), (800, 600), (1280, 960)]:
        run(cam, w, h, dtype)
    cam.set_prop(ptp.DPC_LV_SIZE, 0, dtype)
    cam.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
