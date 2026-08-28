#!/usr/bin/env python3
"""QX5 end-to-end frame test: init, stream, split frames by SOF marker,
patch on a synthetic JPEG header, decode, and save a few PNGs so we can
look at real captured images.
"""

import os
import sys
import time

import usb.core
import usb.util

sys.path.insert(0, os.path.dirname(__file__))
from usb_transport import IsoPump, get_libusb_backend  # noqa: E402
from qx5_driver import Mars97113, split_frames, decode_frame  # noqa: E402

VID = 0x093A
PID = 0x050F
OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else "."


def main():
    width, height = 320, 240
    backend = get_libusb_backend()
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
    if dev is None:
        print("Device not found.")
        sys.exit(1)

    dev.set_configuration()
    dev.set_interface_altsetting(interface=0, alternate_setting=8)

    cam = Mars97113(dev)
    cam.start(width=width, height=height)
    cam.set_illuminators(top=True, bottom=False)
    time.sleep(0.5)

    cfg = dev.get_active_configuration()
    intf = usb.util.find_descriptor(cfg, bInterfaceNumber=0, bAlternateSetting=8)
    ep81 = usb.util.find_descriptor(intf, bEndpointAddress=0x81)
    pkt_size = ep81.wMaxPacketSize & 0x07FF

    pump = IsoPump(dev, 0x81, pkt_size, packets=32, nurbs=8)
    pump.start()
    print("Capturing 3s of video...")
    time.sleep(3.0)
    data = pump.take()
    pump.stop()

    cam.set_illuminators(top=False, bottom=False)
    cam.stop()
    usb.util.dispose_resources(dev)

    print(f"Captured {len(data)} bytes")
    frames, boundaries = split_frames(data)
    print(f"Found {len(boundaries)} SOF markers -> {len(frames)} candidate frames")
    for i, f in enumerate(frames[:5]):
        print(f"  frame {i}: {len(f)} raw scan bytes")

    ok = 0
    os.makedirs(OUT_DIR, exist_ok=True)
    for i, f in enumerate(frames):
        try:
            img = decode_frame(f, width=width, height=height)
            if ok < 5:
                path = os.path.join(OUT_DIR, f"qx5_frame_{ok}.png")
                img.save(path)
                print(f"  decoded frame {i} -> {path}  size={img.size}")
            ok += 1
        except Exception as e:
            if i < 5:
                print(f"  frame {i} decode FAILED: {e}")

    print(f"\n{ok}/{len(frames)} frames decoded successfully")


if __name__ == "__main__":
    main()
