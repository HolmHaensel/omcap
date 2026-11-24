"""Read-only USB enumeration of Olympus bodies via libusb (works before WinUSB is bound).

Lists descriptors only: VID/PID, class, interfaces, endpoints. Nothing is opened,
claimed or written, so it is safe with any driver in place.

Run:  .venv\\Scripts\\python.exe tools\\usb_enum.py
"""
import ctypes
import sys
from typing import Any

import libusb_package  # shipped in the venv by libusb-package

OLYMPUS_VID = 0x07B4


class DevDesc(ctypes.Structure):
    _fields_ = [("bLength", ctypes.c_uint8), ("bDescriptorType", ctypes.c_uint8),
                ("bcdUSB", ctypes.c_uint16), ("bDeviceClass", ctypes.c_uint8),
                ("bDeviceSubClass", ctypes.c_uint8), ("bDeviceProtocol", ctypes.c_uint8),
                ("bMaxPacketSize0", ctypes.c_uint8), ("idVendor", ctypes.c_uint16),
                ("idProduct", ctypes.c_uint16), ("bcdDevice", ctypes.c_uint16),
                ("iManufacturer", ctypes.c_uint8), ("iProduct", ctypes.c_uint8),
                ("iSerialNumber", ctypes.c_uint8), ("bNumConfigurations", ctypes.c_uint8)]


class EndpointDesc(ctypes.Structure):
    _fields_ = [("bLength", ctypes.c_uint8), ("bDescriptorType", ctypes.c_uint8),
                ("bEndpointAddress", ctypes.c_uint8), ("bmAttributes", ctypes.c_uint8),
                ("wMaxPacketSize", ctypes.c_uint16), ("bInterval", ctypes.c_uint8),
                ("bRefresh", ctypes.c_uint8), ("bSynchAddress", ctypes.c_uint8),
                ("extra", ctypes.c_void_p), ("extra_length", ctypes.c_int)]


class InterfaceDesc(ctypes.Structure):
    pass


InterfaceDesc._fields_ = [("bLength", ctypes.c_uint8), ("bDescriptorType", ctypes.c_uint8),
                          ("bInterfaceNumber", ctypes.c_uint8), ("bAlternateSetting", ctypes.c_uint8),
                          ("bNumEndpoints", ctypes.c_uint8), ("bInterfaceClass", ctypes.c_uint8),
                          ("bInterfaceSubClass", ctypes.c_uint8), ("bInterfaceProtocol", ctypes.c_uint8),
                          ("iInterface", ctypes.c_uint8), ("endpoint", ctypes.POINTER(EndpointDesc)),
                          ("extra", ctypes.c_void_p), ("extra_length", ctypes.c_int)]


class Interface(ctypes.Structure):
    _fields_ = [("altsetting", ctypes.POINTER(InterfaceDesc)), ("num_altsetting", ctypes.c_int)]


class Config(ctypes.Structure):
    """struct libusb_config_descriptor: the descriptor itself, then interface[] and extra bytes."""
    _fields_ = [("bLength", ctypes.c_uint8), ("bDescriptorType", ctypes.c_uint8),
                ("wTotalLength", ctypes.c_uint16), ("bNumInterfaces", ctypes.c_uint8),
                ("bConfigurationValue", ctypes.c_uint8), ("iConfiguration", ctypes.c_uint8),
                ("bmAttributes", ctypes.c_uint8), ("MaxPower", ctypes.c_uint8),
                ("interface", ctypes.POINTER(Interface)), ("extra", ctypes.c_void_p),
                ("extra_length", ctypes.c_int)]


CLASSES = {0: "per-interface", 6: "still-image (PTP)", 8: "mass storage"}
PTP_PROTOCOL = {1: "PIMA 15740 (PTP)"}
ATTR = {0: "control", 1: "isochronous", 2: "bulk", 3: "interrupt"}


def main():
    lib: Any = ctypes.CDLL(libusb_package.get_library_path())
    vp, cu8 = ctypes.c_void_p, ctypes.c_ubyte
    lib.libusb_init.argtypes = [ctypes.POINTER(vp)]
    lib.libusb_get_device_list.restype = ctypes.c_ssize_t
    lib.libusb_get_device_list.argtypes = [vp, ctypes.POINTER(ctypes.POINTER(vp))]
    lib.libusb_get_device_descriptor.argtypes = [vp, ctypes.POINTER(DevDesc)]
    lib.libusb_get_config_descriptor.restype = ctypes.c_int
    lib.libusb_get_config_descriptor.argtypes = [vp, cu8, ctypes.POINTER(ctypes.POINTER(Config))]
    lib.libusb_get_string_descriptor_ascii.argtypes = [vp, cu8, ctypes.POINTER(cu8), ctypes.c_int]
    lib.libusb_free_device_list.argtypes = [ctypes.POINTER(vp), ctypes.c_int]

    ctx = vp()
    lib.libusb_init(ctypes.byref(ctx))
    lst = ctypes.POINTER(vp)()
    n = lib.libusb_get_device_list(ctx, ctypes.byref(lst))
    found = 0
    for i in range(n):
        dd = DevDesc()
        if lib.libusb_get_device_descriptor(lst[i], ctypes.byref(dd)) != 0 or dd.idVendor != OLYMPUS_VID:
            continue
        found += 1
        # no string descriptors: those need an open handle (a driver), descriptors do not
        print("\n%04x:%04x  usb %x  configs=%d"
              % (dd.idVendor, dd.idProduct, dd.bcdUSB, dd.bNumConfigurations))
        print("  device class %d (%s) subclass %d protocol %d"
              % (dd.bDeviceClass, CLASSES.get(dd.bDeviceClass, "vendor specific"),
                 dd.bDeviceSubClass, dd.bDeviceProtocol))
        for c in range(dd.bNumConfigurations):
            cfg = ctypes.POINTER(Config)()
            if lib.libusb_get_config_descriptor(lst[i], c, ctypes.byref(cfg)) != 0:
                continue
            cd = cfg.contents
            print("  config %d: %d interface(s), %d mA"
                  % (cd.bConfigurationValue, cd.bNumInterfaces, cd.MaxPower * 2))
            for j in range(cd.bNumInterfaces):
                itf = cfg.contents.interface[j]
                for a in range(itf.num_altsetting):
                    d = itf.altsetting[a]
                    print("    iface %d alt %d: class %d (%s) sub %d proto %d %s"
                          % (d.bInterfaceNumber, d.bAlternateSetting, d.bInterfaceClass,
                             CLASSES.get(d.bInterfaceClass, "?"), d.bInterfaceSubClass,
                             d.bInterfaceProtocol, PTP_PROTOCOL.get(d.bInterfaceProtocol, "")))
                    for e in range(d.bNumEndpoints):
                        ep = d.endpoint[e]
                        print("      ep 0x%02x %s %s maxpacket %d interval %d"
                              % (ep.bEndpointAddress, "IN " if ep.bEndpointAddress & 0x80 else "OUT",
                                 ATTR.get(ep.bmAttributes & 3, "?"), ep.wMaxPacketSize, ep.bInterval))
    if not found:
        print("no Olympus device on the bus")
    lib.libusb_free_device_list(lst, 1)
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
