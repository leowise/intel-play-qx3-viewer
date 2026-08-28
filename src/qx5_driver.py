# src/qx5_driver.py
"""QX5 (Mars-Semi MR97113, 093a:050f) USB protocol.

Ported from Linux's gspca_mars driver
(drivers/media/usb/gspca/mars.c) - the authoritative reference for this
chip's command set. Every command is a byte sequence written to bulk-OUT
endpoint 0x04.
"""

import io

from PIL import Image

from qx5_jpeg_header import make_header

VID = 0x093A
PID = 0x050F

MARKER = bytes([0xff, 0xff, 0x00, 0xff, 0x96])
MIN_RAW_SCAN_BYTES = 64
BRIGHTNESS_MAX = 30
SHARPNESS_MAX = 2

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

    @staticmethod
    def _encode_brightness(value):
        if not isinstance(value, int) or not 0 <= value <= BRIGHTNESS_MAX:
            raise ValueError(f"brightness must be an integer from 0 to {BRIGHTNESS_MAX}")
        # The camera's register direction is opposite to the user-facing
        # brightness scale: a lower UI value produces a brighter image.
        return BRIGHTNESS_MAX - value

    def set_brightness(self, val):
        self.reg_w([0x61, self._encode_brightness(val)])

    def set_colors(self, saturation):
        self.reg_w([0x5f, (saturation << 3) & 0xFF, ((saturation >> 2) & 0xf8) | 0x04])

    def set_gamma(self, val):
        self.reg_w([0x06, (val * 0x40) & 0xFF])

    def set_sharpness(self, val):
        self.reg_w([0x67, self._encode_sharpness(val)])

    @staticmethod
    def _encode_sharpness(value):
        if not isinstance(value, int) or not 0 <= value <= SHARPNESS_MAX:
            raise ValueError(f"sharpness must be an integer from 0 to {SHARPNESS_MAX}")
        return value * 4 + 3

    def set_illuminators(self, top=False, bottom=False):
        if top and bottom:
            raise ValueError("QX5 illuminators are modeled as mutually exclusive")
        if top:
            b = 0x76
        elif bottom:
            b = 0x7a
        else:
            b = 0x7e
        self.reg_w([0x22, b])

    def start(self, width=320, height=240, gamma=1, saturation=200, brightness=15, sharpness=1):
        brightness_register = self._encode_brightness(brightness)
        sharpness_register = self._encode_sharpness(sharpness)
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
            brightness_register,
            0x00,
        ])

        self.reg_w([0x67, sharpness_register, 0x14])
        self.reg_w([0x69, 0x2f, 0x28, 0x42])
        self.reg_w([0x63, 0x07])

        for i in range(len(MI_DATA)):
            self.mi_w(i + 1, MI_DATA[i])

        self.reg_w([0x00, 0x4d])

    def stop(self):
        self.reg_w([0x01, 0x00])


class FrameDecodeError(ValueError):
    """Raised when a raw QX5 scan cannot be trusted as a complete frame."""


def split_frames(buf):
    """Split a raw isochronous byte stream into complete raw JPEG-scan
    frames plus the sync-marker boundaries found.

    Each frame is framed by a 16-byte sync header: MARKER (5 bytes) +
    a type byte in (0x64..0x67) + 10 filler bytes. A frame's payload
    runs from one boundary+16 to the next boundary; the segment after
    the last boundary is not a complete frame yet.
    """
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


def decode_frame(raw_scan, width=320, height=240, quality=50, samples_y=0x21):
    """Patch a synthetic JPEG header onto raw MR97113 scan data and decode."""
    if not isinstance(raw_scan, (bytes, bytearray, memoryview)):
        raise TypeError("raw_scan must be bytes-like")
    if width <= 0 or height <= 0:
        raise ValueError("frame dimensions must be positive")

    raw_scan = bytes(raw_scan)
    if len(raw_scan) < MIN_RAW_SCAN_BYTES:
        raise FrameDecodeError("raw JPEG scan is too short")

    header = make_header(height, width, quality=quality, samples_y=samples_y)
    jpg_bytes = header + raw_scan + b"\xff\xd9"
    try:
        with Image.open(io.BytesIO(jpg_bytes)) as img:
            if img.size != (width, height):
                raise FrameDecodeError(
                    f"decoded frame size {img.size} does not match {(width, height)}"
                )
            img.verify()
        with Image.open(io.BytesIO(jpg_bytes)) as img:
            img.load()
            return img.convert("RGB")
    except FrameDecodeError:
        raise
    except (OSError, SyntaxError) as exc:
        raise FrameDecodeError(f"invalid JPEG scan: {exc}") from exc
