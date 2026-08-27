#!/usr/bin/env python3
"""Standalone descriptor probe for the Digital Blue QX5 ("1.3M PC-CAM", USB 093A:050F).

Confirms pyusb/libusb can find and open the device, then dumps its
configuration/interface/endpoint descriptors. No protocol assumptions -
just enumeration, so it is safe to run against unknown hardware.
"""

import os
import sys

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


def main():
    dll = find_libusb_dll()
    if not dll:
        print("ERROR: could not locate libusb-1.0.dll from the 'libusb' package.")
        sys.exit(1)
    print(f"Using libusb DLL: {dll}")

    backend = usb_libusb1.get_backend(find_library=lambda x: dll)
    if backend is None:
        print("ERROR: libusb1 backend failed to load.")
        sys.exit(1)

    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
    if dev is None:
        print(f"Device {VID:04x}:{PID:04x} not found. Is it plugged in and bound to WinUSB?")
        sys.exit(1)

    print(f"Found device {VID:04x}:{PID:04x}")
    print(f"  bcdUSB          : {dev.bcdUSB:#06x}")
    print(f"  bDeviceClass    : {dev.bDeviceClass:#04x}")
    print(f"  bDeviceSubClass : {dev.bDeviceSubClass:#04x}")
    print(f"  bDeviceProtocol : {dev.bDeviceProtocol:#04x}")
    print(f"  bNumConfigurations: {dev.bNumConfigurations}")

    try:
        manufacturer = usb.util.get_string(dev, dev.iManufacturer) if dev.iManufacturer else None
        product = usb.util.get_string(dev, dev.iProduct) if dev.iProduct else None
        serial = usb.util.get_string(dev, dev.iSerialNumber) if dev.iSerialNumber else None
        print(f"  iManufacturer   : {manufacturer!r}")
        print(f"  iProduct        : {product!r}")
        print(f"  iSerialNumber   : {serial!r}")
    except Exception as e:
        print(f"  (string descriptors unavailable: {e})")

    for cfg in dev:
        print(f"\nConfiguration {cfg.bConfigurationValue}: "
              f"bNumInterfaces={cfg.bNumInterfaces} "
              f"bMaxPower={cfg.bMaxPower * 2}mA "
              f"self_powered={usb.util.SelfPowered(cfg.bmAttributes) if hasattr(usb.util, 'SelfPowered') else '?'}")
        for intf in cfg:
            print(f"  Interface {intf.bInterfaceNumber} alt {intf.bAlternateSetting}: "
                  f"class={intf.bInterfaceClass:#04x} "
                  f"subclass={intf.bInterfaceSubClass:#04x} "
                  f"protocol={intf.bInterfaceProtocol:#04x} "
                  f"numEndpoints={intf.bNumEndpoints}")
            for ep in intf:
                addr = ep.bEndpointAddress
                direction = "IN" if usb.util.endpoint_direction(addr) == usb.util.ENDPOINT_IN else "OUT"
                xfer_type = usb.util.endpoint_type(ep.bmAttributes)
                xfer_names = {
                    usb.util.ENDPOINT_TYPE_CTRL: "control",
                    usb.util.ENDPOINT_TYPE_ISO: "isochronous",
                    usb.util.ENDPOINT_TYPE_BULK: "bulk",
                    usb.util.ENDPOINT_TYPE_INTR: "interrupt",
                }
                pkt = ep.wMaxPacketSize & 0x07FF
                print(f"    EP {addr:#04x} {direction:3s} {xfer_names.get(xfer_type, '?'):11s} "
                      f"wMaxPacketSize={pkt} bInterval={ep.bInterval}")

    print("\nDone. No claims/transfers were attempted - this is descriptor enumeration only.")


if __name__ == "__main__":
    main()
