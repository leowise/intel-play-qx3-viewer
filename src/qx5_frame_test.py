#!/usr/bin/env python3
"""QX5 end-to-end frame test: init, stream, split frames by SOF marker,
patch on a synthetic JPEG header, decode, and save a few PNGs so we can
look at real captured images.
"""

import io
import os
import sys
import time

import usb.core
import usb.util
import usb.backend.libusb1 as usb_libusb1
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from qx3_gui import IsoPump, find_libusb_dll  # noqa: E402
from qx5_bringup import Mars97113  # noqa: E402
from qx5_jpeg_header import make_header  # noqa: E402

VID = 0x093A
PID = 0x050F
MARKER = bytes([0xff, 0xff, 0x00, 0xff, 0x96])
OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else "."


def split_frames(buf):
    boundaries = []
    i = 0
    n = len(buf)
    while i < n - 6:
        if buf[i:i + 5] == MARKER and buf[i + 5] in (0x64, 0x65, 0x66, 0x67):
            boundaries.append(i)
            i += 16
        else:
            i += 1
    frames = []
    for k in range(len(boundaries) - 1):
        start = boundaries[k] + 16
        end = boundaries[k + 1]
        if end > start:
            frames.append(bytes(buf[start:end]))
    return frames, boundaries


def main():
    width, height = 320, 240
    dll = find_libusb_dll()
    backend = usb_libusb1.get_backend(find_library=lambda x: dll)
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

    header = make_header(height, width, quality=50, samples_y=0x21)
    print(f"\nJPEG header: {len(header)} bytes")

    ok = 0
    os.makedirs(OUT_DIR, exist_ok=True)
    for i, f in enumerate(frames):
        jpg = header + f + b"\xff\xd9"
        try:
            img = Image.open(io.BytesIO(jpg))
            img.load()
            img = img.convert("RGB")
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
