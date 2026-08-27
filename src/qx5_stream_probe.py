#!/usr/bin/env python3
"""QX5 (093A:050F) exploratory probe: does the isochronous endpoint produce
data with no vendor commands sent at all, just by selecting an alt setting?

Also does a quick non-blocking peek at the interrupt and bulk-IN endpoints
in case the device announces itself unsolicited. Read-only exploration -
no vendor control transfers, no bulk-OUT writes.
"""

import os
import sys
import time

import usb.core
import usb.util
import usb.backend.libusb1 as usb_libusb1

VID = 0x093A
PID = 0x050F


def find_libusb_dll():
    import libusb
    pkg_dir = os.path.dirname(libusb.__file__)
    for root, dirs, files in os.walk(pkg_dir):
        for f in files:
            if f.lower() == "libusb-1.0.dll" and "x86_64" in root:
                return os.path.join(root, f)
    return None


def hexdump(data, n=32):
    b = bytes(data[:n])
    return " ".join(f"{x:02x}" for x in b) + (" ..." if len(data) > n else "")


def try_read(dev, ep_addr, size, timeout, label):
    try:
        data = dev.read(ep_addr, size, timeout=timeout)
        print(f"  [{label}] {len(data)} bytes: {hexdump(data)}")
        return True
    except usb.core.USBTimeoutError:
        print(f"  [{label}] timeout, no data")
    except usb.core.USBError as e:
        print(f"  [{label}] error: {e}")
    return False


def try_read_ep(ep, size, label):
    """Read via an explicit endpoint descriptor object (tracks the alt
    setting it was looked up from, unlike dev.read() which can pick a
    stale wMaxPacketSize from a different alt setting)."""
    try:
        data = ep.read(size, timeout=100)
        print(f"  [{label}] {len(data)} bytes: {hexdump(data)}")
        return True
    except usb.core.USBTimeoutError:
        print(f"  [{label}] timeout, no data")
    except usb.core.USBError as e:
        print(f"  [{label}] error: {e}")
    return False


def main():
    dll = find_libusb_dll()
    backend = usb_libusb1.get_backend(find_library=lambda x: dll)
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
    if dev is None:
        print("Device not found.")
        sys.exit(1)

    dev.set_configuration()

    print("=== Step 1: peek interrupt (0x85) and bulk-IN (0x82, 0x83) with alt 0, short timeout ===")
    dev.set_interface_altsetting(interface=0, alternate_setting=0)
    try_read(dev, 0x85, 1, 300, "interrupt 0x85")
    try_read(dev, 0x82, 64, 300, "bulk-in 0x82")
    try_read(dev, 0x83, 16, 300, "bulk-in 0x83")

    for alt in (4, 8):
        print(f"\n=== Step 2: select alt setting {alt}, listen on iso 0x81 for ~2s ===")
        try:
            dev.set_interface_altsetting(interface=0, alternate_setting=alt)
        except usb.core.USBError as e:
            print(f"  set_interface_altsetting({alt}) failed: {e}")
            continue

        cfg = dev.get_active_configuration()
        intf = usb.util.find_descriptor(cfg, bInterfaceNumber=0, bAlternateSetting=alt)
        ep81 = usb.util.find_descriptor(intf, bEndpointAddress=0x81)
        ep86 = usb.util.find_descriptor(intf, bEndpointAddress=0x86)
        pkt_size = ep81.wMaxPacketSize & 0x07FF
        print(f"  iso packet size at alt {alt}: {pkt_size}")

        got_any = False
        t0 = time.time()
        attempts = 0
        while time.time() - t0 < 2.0 and attempts < 40:
            attempts += 1
            if try_read_ep(ep81, pkt_size * 32, f"iso 0x81 (alt {alt})"):
                got_any = True
                break
        if not got_any:
            print(f"  no isochronous data at alt {alt} after {attempts} attempts")

        try_read_ep(ep86, (ep86.wMaxPacketSize & 0x07FF) * 8 or 16, "iso 0x86")

        dev.set_interface_altsetting(interface=0, alternate_setting=0)

    usb.util.dispose_resources(dev)
    print("\nDone.")


if __name__ == "__main__":
    main()
