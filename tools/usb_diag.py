"""Diagnose why libusb cannot open the Olympus body (Windows driver binding check).

Uses the project's own ctypes libusb binding, so it needs no extra package. Lists every device from the
Olympus vendor, then tries open + claim interface 0 on each and prints libusb's own error name.
Nothing is sent to the camera.
"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from omcap import ptp  # noqa: E402


class Desc(ctypes.Structure):
    _fields_ = [("bLength", ctypes.c_uint8), ("bDescriptorType", ctypes.c_uint8),
                ("bcdUSB", ctypes.c_uint16), ("bDeviceClass", ctypes.c_uint8),
                ("bDeviceSubClass", ctypes.c_uint8), ("bDeviceProtocol", ctypes.c_uint8),
                ("bMaxPacketSize0", ctypes.c_uint8), ("idVendor", ctypes.c_uint16),
                ("idProduct", ctypes.c_uint16), ("bcdDevice", ctypes.c_uint16),
                ("iManufacturer", ctypes.c_uint8), ("iProduct", ctypes.c_uint8),
                ("iSerialNumber", ctypes.c_uint8), ("bNumConfigurations", ctypes.c_uint8)]


def main():
    lib = ptp._libusb()
    vp, cint = ctypes.c_void_p, ctypes.c_int
    lib.libusb_error_name.restype = ctypes.c_char_p
    lib.libusb_error_name.argtypes = [cint]
    lib.libusb_get_device_list.restype = ctypes.c_ssize_t
    lib.libusb_get_device_list.argtypes = [vp, ctypes.POINTER(ctypes.POINTER(vp))]
    lib.libusb_get_device_descriptor.argtypes = [vp, ctypes.POINTER(Desc)]
    lib.libusb_open.argtypes = [vp, ctypes.POINTER(vp)]
    lib.libusb_claim_interface.argtypes = [vp, cint]
    lib.libusb_release_interface.argtypes = [vp, cint]
    lib.libusb_close.argtypes = [vp]
    lib.libusb_free_device_list.argtypes = [ctypes.POINTER(vp), cint]

    def err(n):
        try:
            return lib.libusb_error_name(n).decode()
        except Exception:
            return str(n)

    ctx = ctypes.c_void_p()
    lib.libusb_init(ctypes.byref(ctx))
    lst = ctypes.POINTER(vp)()
    n = lib.libusb_get_device_list(ctx, ctypes.byref(lst))
    print("libusb device list: %d device(s)" % n)
    found = []
    for i in range(max(n, 0)):
        d = Desc()
        if lib.libusb_get_device_descriptor(lst[i], ctypes.byref(d)) != 0:
            continue
        if d.idVendor != ptp.OLYMPUS_VID:
            continue
        found.append((i, d))
        print("  %04x:%04x  bcdDevice %04x  class %d/%d/%d  in KNOWN_PIDS=%s"
              % (d.idVendor, d.idProduct, d.bcdDevice, d.bDeviceClass, d.bDeviceSubClass,
                 d.bDeviceProtocol, d.idProduct in ptp.KNOWN_PIDS))

    if not found:
        print("no Olympus device on the bus — unplugged, camera off, or a mode that drops the link")

    for i, d in found:
        print("\n--- open %04x:%04x ---" % (d.idVendor, d.idProduct))
        h = ctypes.c_void_p()
        r = lib.libusb_open(lst[i], ctypes.byref(h))
        if r != 0:
            print("  libusb_open: %s  <-- no WinUSB for this device id (Windows MTP/PTP driver still bound)"
                  % err(r))
            continue
        print("  libusb_open: ok")
        r = lib.libusb_claim_interface(h, 0)
        print("  claim interface 0: %s" % ("ok" if r == 0 else err(r) + "  <-- another driver holds it"))
        if r == 0:
            lib.libusb_release_interface(h, 0)
        lib.libusb_close(h)

    lib.libusb_free_device_list(lst, 1)
    lib.libusb_exit(ctx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
