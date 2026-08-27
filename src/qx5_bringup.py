#!/usr/bin/env python3
"""QX5 (Mars-Semi MR97113, 093a:050f) bring-up test.

Ports the init sequence from Linux's gspca_mars driver
(drivers/media/usb/gspca/mars.c) to pyusb, sends it, turns on the top
light, and checks whether the isochronous endpoint starts producing bytes.
No JPEG decoding yet - just confirms the command layer actually works
against real hardware.
"""

import os
import sys
import time

import usb.core
import usb.util
import usb.backend.libusb1 as usb_libusb1

sys.path.insert(0, os.path.dirname(__file__))
from qx3_gui import IsoPump, find_libusb_dll  # noqa: E402

VID = 0x093A
PID = 0x050F

# mi_data from mars.c - default MI sensor register values
MI_DATA = bytes([
    0x48, 0x22, 0x01, 0x47, 0x10, 0x00, 0x00, 0x00,
    0x00, 0x01, 0x30, 0x01, 0x30, 0x01, 0x30, 0x01,
    0x30, 0x00, 0x04, 0x00, 0x06, 0x01, 0xe2, 0x02,
    0x82, 0x00, 0x20, 0x17, 0x80, 0x08, 0x0c, 0x00,
])


class Mars97113:
    def __init__(self, dev):
        self.dev = dev

    def reg_w(self, data):
        self.dev.write(0x04, bytes(data), timeout=500)

    def mi_w(self, addr, value):
        self.reg_w([0x1f, 0x00, addr, value])

    def set_brightness(self, val):
        self.reg_w([0x61, val])

    def set_colors(self, saturation):
        self.reg_w([0x5f, (saturation << 3) & 0xFF, ((saturation >> 2) & 0xf8) | 0x04])

    def set_gamma(self, val):
        self.reg_w([0x06, (val * 0x40) & 0xFF])

    def set_sharpness(self, val):
        self.reg_w([0x67, (val * 4 + 3) & 0xFF])

    def set_illuminators(self, top=False, bottom=False):
        if top:
            b = 0x76
        elif bottom:
            b = 0x7a
        else:
            b = 0x7e
        self.reg_w([0x22, b])

    def start(self, width=320, height=240, gamma=1, saturation=200, brightness=15, sharpness=1):
        self.reg_w([0x01, 0x01])

        self.reg_w([
            0x00,
            0x0c | 0x01,
            0x01,
            width // 8,
            height // 8,
            0x30,
            0x02,
            (gamma * 0x40) & 0xFF,
            0x01,
            0x52,
            0x18,
        ])

        self.reg_w([0x23, 0x09])
        self.reg_w([0x3c, 50])

        self.reg_w([
            0x5e,
            0x00,
            (saturation << 3) & 0xFF,
            ((saturation >> 2) & 0xf8) | 0x04,
            brightness,
            0x00,
        ])

        self.reg_w([0x67, (sharpness * 4 + 3) & 0xFF, 0x14])
        self.reg_w([0x69, 0x2f, 0x28, 0x42])
        self.reg_w([0x63, 0x07])

        for i in range(len(MI_DATA)):
            self.mi_w(i + 1, MI_DATA[i])

        self.reg_w([0x00, 0x4d])

    def stop(self):
        self.reg_w([0x01, 0x00])


def hexdump(data, n=64):
    b = bytes(data[:n])
    return " ".join(f"{x:02x}" for x in b) + (" ..." if len(data) > n else "")


def main():
    dll = find_libusb_dll()
    backend = usb_libusb1.get_backend(find_library=lambda x: dll)
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
    if dev is None:
        print("Device not found.")
        sys.exit(1)

    dev.set_configuration()
    dev.set_interface_altsetting(interface=0, alternate_setting=8)

    cam = Mars97113(dev)

    print("=== Sending init sequence (320x240) ===")
    try:
        cam.start(width=320, height=240)
        print("  init sequence sent OK")
    except usb.core.USBError as e:
        print(f"  init FAILED: {e}")
        sys.exit(1)

    print("\n=== Turning top light ON ===")
    try:
        cam.set_illuminators(top=True, bottom=False)
        print("  command sent - check the microscope now")
    except usb.core.USBError as e:
        print(f"  light command FAILED: {e}")

    time.sleep(1.0)

    print("\n=== Listening on iso 0x81 for ~3s ===")
    cfg = dev.get_active_configuration()
    intf = usb.util.find_descriptor(cfg, bInterfaceNumber=0, bAlternateSetting=8)
    ep81 = usb.util.find_descriptor(intf, bEndpointAddress=0x81)
    pkt_size = ep81.wMaxPacketSize & 0x07FF

    pump = IsoPump(dev, 0x81, pkt_size, packets=32, nurbs=8)
    pump.start()
    time.sleep(3.0)
    data = pump.take()
    pump.stop()

    print(f"  collected {len(data)} bytes")
    if data:
        print(f"  first bytes: {hexdump(data)}")
        marker = bytes([0xff, 0xff, 0x00, 0xff, 0x96])
        idx = data.find(marker)
        print(f"  SOF marker (ff ff 00 ff 96) found at offset: {idx}")
    else:
        print("  no data - streaming did not start")

    print("\n=== Turning lights OFF ===")
    cam.set_illuminators(top=False, bottom=False)
    cam.stop()

    usb.util.dispose_resources(dev)
    print("\nDone.")


if __name__ == "__main__":
    main()
