#!/usr/bin/env python3
"""QX5 (093A:050F) exploratory probe, take 2: use the same raw-libusb
isochronous pump (pyusb's high-level iso_read() mis-derives packet size across
alt settings), just to see whether the camera streams
data with no vendor commands sent at all.
"""

import os
import sys
import time

import usb.core
import usb.util

sys.path.insert(0, os.path.dirname(__file__))
from usb_transport import IsoPump, get_libusb_backend  # noqa: E402

VID = 0x093A
PID = 0x050F


def hexdump(data, n=48):
    b = bytes(data[:n])
    return " ".join(f"{x:02x}" for x in b) + (" ..." if len(data) > n else "")


def main():
    backend = get_libusb_backend()
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
    if dev is None:
        print("Device not found.")
        sys.exit(1)

    dev.set_configuration()

    for alt in (4, 8):
        print(f"\n=== alt setting {alt} ===")
        dev.set_interface_altsetting(interface=0, alternate_setting=alt)
        cfg = dev.get_active_configuration()
        intf = usb.util.find_descriptor(cfg, bInterfaceNumber=0, bAlternateSetting=alt)
        ep81 = usb.util.find_descriptor(intf, bEndpointAddress=0x81)
        pkt_size = ep81.wMaxPacketSize & 0x07FF
        print(f"  packet size: {pkt_size}")

        pump = IsoPump(dev, 0x81, pkt_size, packets=32, nurbs=8)
        pump.start()
        time.sleep(1.5)
        data = pump.take()
        pump.stop()

        print(f"  collected {len(data)} bytes over 1.5s")
        if data:
            print(f"  first bytes: {hexdump(data)}")
        else:
            print("  (nothing - no data flowing without an init command)")

        dev.set_interface_altsetting(interface=0, alternate_setting=0)

    usb.util.dispose_resources(dev)
    print("\nDone.")


if __name__ == "__main__":
    main()
