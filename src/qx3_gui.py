#!/usr/bin/env python3
"""
Intel Play QX3 Microscope - GUI Driver

Uses the same CPiA streaming approach as the Linux gspca_cpia1 driver:
YUV420, a few uncompressed keyframes, then hardware compression so USB 1.1
can carry the original 320x240 capture at a usable frame rate.
"""

import os
import sys
import time
import threading
import traceback
from datetime import datetime
from ctypes import (
    POINTER, Structure, c_ubyte, c_void_p, c_int, c_long, byref, cast, string_at
)

import numpy as np
import usb.core
import usb.util
import usb.backend.libusb1 as usb_libusb1
import tkinter as tk
from tkinter import messagebox, filedialog

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

MAGIC_0 = 0x19
MAGIC_1 = 0x68
MAGIC = bytes([0x19, 0x68])
EOL = 0xFD
VID = 0x0813
PID = 0x0001

# Intel Play captured a centred 320x240 ROI and interpolated to 512x384.
QX3_NATIVE_ROI = (2, 42, 6, 66)

LIBUSB_TRANSFER_COMPLETED = 0
LIBUSB_TRANSFER_ERROR = 1
LIBUSB_TRANSFER_TIMED_OUT = 2
LIBUSB_TRANSFER_CANCELLED = 3
LIBUSB_SUCCESS = 0


class _Timeval(Structure):
    _fields_ = [("tv_sec", c_long), ("tv_usec", c_long)]


class IsoPump:
    """Keep several isochronous URBs in flight and pack only real payload.

    PyUSB's iso_read() treats the URB buffer as tightly packed using
    sum(actual_length). Empty 1ms packets then insert zeros and truncate
    later data, which produces a burst of good frames followed by silence.
    """

    def __init__(self, pyusb_dev, endpoint_addr, packet_size, packets=32, nurbs=8):
        self._dev = pyusb_dev
        self._ep = endpoint_addr
        self.packet_size = packet_size
        self.packets = packets
        self.nurbs = nurbs
        self._lock = threading.Lock()
        self._buf = bytearray()
        self._alive = False
        self._thread = None
        self._xfers = []
        self._raw_bufs = []
        self._bytes = 0
        self._in_flight = 0
        self._cb = usb_libusb1._libusb_transfer_cb_fn_p(self._on_complete)

    def start(self):
        if self._alive:
            return
        lib = self._dev.backend.lib
        self._dev._ctx.managed_open()
        handle = self._dev._ctx.handle.handle
        self._xfers = []
        self._raw_bufs = []
        buf_len = self.packet_size * self.packets
        for _ in range(self.nurbs):
            raw = (c_ubyte * buf_len)()
            xfer = lib.libusb_alloc_transfer(self.packets)
            if not xfer:
                raise RuntimeError("libusb_alloc_transfer failed")
            lib.libusb_fill_iso_transfer(
                xfer,
                handle,
                self._ep,
                cast(raw, POINTER(c_ubyte)),
                buf_len,
                self.packets,
                self._cb,
                None,
                0,
            )
            lib.libusb_set_iso_packet_lengths(xfer, self.packet_size)
            self._raw_bufs.append(raw)
            self._xfers.append(xfer)
        self._alive = True
        self._buf = bytearray()
        self._bytes = 0
        self._in_flight = 0
        for xfer in self._xfers:
            err = lib.libusb_submit_transfer(xfer)
            if err != LIBUSB_SUCCESS:
                self._alive = False
                raise usb.core.USBError("iso submit failed: %s" % err)
            self._in_flight += 1
        self._thread = threading.Thread(target=self._event_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Cancel URBs and wait until the event thread has fully stopped.

        Returns True if it is safe to close the libusb device handle.
        """
        self._alive = False
        if not self._xfers and self._thread is None:
            return True
        lib = self._dev.backend.lib
        for xfer in self._xfers:
            try:
                lib.libusb_cancel_transfer(xfer)
            except Exception:
                pass
        try:
            if hasattr(lib, "libusb_interrupt_event_handler"):
                lib.libusb_interrupt_event_handler.argtypes = [c_void_p]
                lib.libusb_interrupt_event_handler(self._dev.backend.ctx)
        except Exception:
            pass
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3)
        safe = self._thread is None or not self._thread.is_alive()
        if not safe:
            # Event thread still in libusb_handle_events; freeing or
            # closing the handle here causes an access violation on Windows.
            return False
        self._thread = None
        for xfer in self._xfers:
            try:
                lib.libusb_free_transfer(xfer)
            except Exception:
                pass
        self._xfers = []
        self._raw_bufs = []
        self._in_flight = 0
        return True

    def take(self):
        with self._lock:
            if not self._buf:
                return b""
            data = bytes(self._buf)
            self._buf.clear()
            return data

    def _event_loop(self):
        lib = self._dev.backend.lib
        ctx = self._dev.backend.ctx
        tv = _Timeval(0, 50000)
        has_timeout = hasattr(lib, "libusb_handle_events_timeout")
        if has_timeout:
            lib.libusb_handle_events_timeout.argtypes = [c_void_p, POINTER(_Timeval)]
            lib.libusb_handle_events_timeout.restype = c_int
        while self._alive or self._in_flight > 0:
            if has_timeout:
                lib.libusb_handle_events_timeout(ctx, byref(tv))
            else:
                lib.libusb_handle_events(ctx)

    def _on_complete(self, xfer_p):
        resubmitted = False
        try:
            xfer = xfer_p.contents
            if self._alive and xfer.status in (
                LIBUSB_TRANSFER_COMPLETED, LIBUSB_TRANSFER_TIMED_OUT, LIBUSB_TRANSFER_ERROR
            ):
                pkts = usb_libusb1._get_iso_packet_list(xfer)
                base = xfer.buffer
                if not isinstance(base, int):
                    base = cast(base, c_void_p).value
                if base:
                    chunks = []
                    pkt_sz = self.packet_size
                    for i in range(xfer.num_iso_packets):
                        pkt = pkts[i]
                        if pkt.status == 0 and pkt.actual_length > 0:
                            chunks.append(string_at(base + i * pkt_sz, pkt.actual_length))
                    if chunks:
                        data = b"".join(chunks)
                        with self._lock:
                            self._buf.extend(data)
                            self._bytes += len(data)
                            if len(self._buf) > 2000000:
                                del self._buf[: len(self._buf) - 1000000]
            if self._alive and xfer.status != LIBUSB_TRANSFER_CANCELLED:
                err = self._dev.backend.lib.libusb_submit_transfer(xfer_p)
                resubmitted = (err == LIBUSB_SUCCESS)
        except Exception:
            resubmitted = False
        if not resubmitted:
            self._in_flight = max(0, self._in_flight - 1)


def find_libusb_dll():
    import libusb
    pkg_dir = os.path.dirname(libusb.__file__)
    for root, dirs, files in os.walk(pkg_dir):
        for f in files:
            if f.lower() == 'libusb-1.0.dll' and 'x86_64' in root:
                return os.path.join(root, f)
    return r'C:\Users\m\AppData\Local\Programs\Python\Python313\Lib\site-packages\libusb\_platform\windows\x86_64\libusb-1.0.dll'


def _is_timeout(err):
    errno = getattr(err, 'errno', None)
    if errno in (110, 10060, 60, 10035):
        return True
    return 'timeout' in str(err).lower()


def _header_ok(data, i):
    if i + 29 > len(data):
        return False
    return (
        data[i] == MAGIC_0 and data[i + 1] == MAGIC_1
        and data[i + 16] in (0, 1)
        and data[i + 17] in (0, 1)
        and data[i + 18] in (0, 1)
        and data[i + 28] in (0, 1)
    )


def extract_frames(data):
    """Split a CPiA byte stream into complete frames plus leftover bytes.

    Only the next valid frame header ends a frame. 0xFF*4 appears in
    pixel data, so it is not used as an end marker.
    """
    frames = []
    i = 0
    n = len(data)
    while i + 64 <= n:
        j = data.find(MAGIC, i)
        if j < 0:
            return frames, bytes(data[max(i, n - 63):])
        if not _header_ok(data, j):
            i = j + 1
            continue
        next_h = None
        nxt = data.find(MAGIC, j + 64)
        while nxt != -1:
            if _header_ok(data, nxt):
                next_h = nxt
                break
            nxt = data.find(MAGIC, nxt + 1)
        if next_h is None:
            return frames, bytes(data[j:])
        frames.append(bytes(data[j:next_h]))
        i = next_h
    return frames, bytes(data[i:])


def yuv420_to_rgb(y, u, v):
    if HAS_OPENCV:
        h, w = y.shape
        i420 = np.empty((h + h // 2, w), dtype=np.uint8)
        i420[:h] = y
        i420[h:h + h // 4] = u.reshape(h // 4, w)
        i420[h + h // 4:] = v.reshape(h // 4, w)
        return cv2.cvtColor(i420, cv2.COLOR_YUV2RGB_I420)
    u2 = np.repeat(np.repeat(u, 2, axis=0), 2, axis=1)
    v2 = np.repeat(np.repeat(v, 2, axis=0), 2, axis=1)
    y16 = y.astype(np.int16)
    u16 = u2.astype(np.int16) - 128
    v16 = v2.astype(np.int16) - 128
    r = np.clip(y16 + ((359 * v16) >> 8), 0, 255).astype(np.uint8)
    g = np.clip(y16 - ((88 * u16 + 183 * v16) >> 8), 0, 255).astype(np.uint8)
    b = np.clip(y16 + ((454 * u16) >> 8), 0, 255).astype(np.uint8)
    return np.dstack((r, g, b))


def yuv422_to_rgb(y, u, v):
    if HAS_OPENCV:
        h, w = y.shape
        yuyv = np.empty((h, w, 2), dtype=np.uint8)
        yuyv[:, :, 0] = y
        yuyv[:, 0::2, 1] = u
        yuyv[:, 1::2, 1] = v
        return cv2.cvtColor(yuyv, cv2.COLOR_YUV2RGB_YUYV)
    u2 = np.repeat(u, 2, axis=1)
    v2 = np.repeat(v, 2, axis=1)
    y16 = y.astype(np.int16)
    u16 = u2.astype(np.int16) - 128
    v16 = v2.astype(np.int16) - 128
    r = np.clip(y16 + ((359 * v16) >> 8), 0, 255).astype(np.uint8)
    g = np.clip(y16 - ((88 * u16 + 183 * v16) >> 8), 0, 255).astype(np.uint8)
    b = np.clip(y16 + ((454 * u16) >> 8), 0, 255).astype(np.uint8)
    return np.dstack((r, g, b))


def interpolate_rgb(rgb, out_w, out_h):
    h, w = rgb.shape[:2]
    if w == out_w and h == out_h:
        return rgb
    if HAS_OPENCV:
        return cv2.resize(rgb, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
    if not HAS_PIL:
        return rgb
    return np.asarray(Image.fromarray(rgb).resize((out_w, out_h), Image.BILINEAR))


class CpiaDecoder:
    """CPiA YUV420/422 decoder, including skip-code compression."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.y = None
        self.u = None
        self.v = None
        self.width = 0
        self.height = 0
        self.subsample = None

    def decode(self, data):
        if len(data) < 64 or data[0] != MAGIC_0 or data[1] != MAGIC_1:
            return None
        subsample = data[17]
        compressed = data[28]
        col0, col1, row0, row1 = data[24], data[25], data[26], data[27]
        width = (col1 - col0) * 8
        height = (row1 - row0) * 4
        if width < 8 or height < 4 or width > 352 or height > 288:
            return None
        if (width & 1) or (subsample == 0 and (height & 1)):
            return None
        if subsample not in (0, 1):
            return None

        src = memoryview(data)[64:]
        size_changed = (
            self.y is None
            or self.y.shape != (height, width)
            or self.subsample != subsample
        )
        if size_changed:
            self.reset()
            if compressed:
                return None

        if subsample == 0:
            u_shape = (height // 2, width // 2)
        else:
            u_shape = (height, width // 2)

        if compressed:
            y = self.y.copy()
            u = self.u.copy()
            v = self.v.copy()
            if subsample == 0:
                ok = self._decode_compressed_420(src, y, u, v, width, height)
            else:
                ok = self._decode_compressed_422(src, y, u, v, width, height)
            if not ok:
                return None
        else:
            y = np.empty((height, width), dtype=np.uint8)
            u = np.empty(u_shape, dtype=np.uint8)
            v = np.empty(u_shape, dtype=np.uint8)
            if not self._decode_uncompressed(src, y, u, v, width, height, subsample):
                return None

        self.y, self.u, self.v = y, u, v
        self.width, self.height, self.subsample = width, height, subsample
        if subsample == 0:
            return yuv420_to_rgb(y, u, v)
        return yuv422_to_rgb(y, u, v)

    def _decode_uncompressed(self, src, y, u, v, width, height, subsample):
        pos = 0
        src_len = len(src)
        for row in range(height):
            if pos + 2 > src_len:
                return False
            line_len = src[pos] | (src[pos + 1] << 8)
            pos += 2
            if line_len < 1 or pos + line_len > src_len or src[pos + line_len - 1] != EOL:
                return False
            even = (row & 1) == 0
            if subsample == 0 and not even and line_len == width + 1:
                y[row] = np.frombuffer(src[pos:pos + width], dtype=np.uint8)
            else:
                if line_len != 2 * width + 1:
                    return False
                line = np.frombuffer(src[pos:pos + width * 2], dtype=np.uint8)
                y[row] = line[0::2]
                if subsample == 0:
                    u[row >> 1] = line[1::4]
                    v[row >> 1] = line[3::4]
                else:
                    u[row] = line[1::4]
                    v[row] = line[3::4]
            pos += line_len
        return True

    def _decode_compressed_420(self, src, y, u, v, width, height):
        pos = 0
        src_len = len(src)
        yf = y.ravel()
        uf = u.ravel()
        vf = v.ravel()
        uw = width >> 1
        for row in range(height):
            if pos + 2 > src_len:
                return False
            line_len = src[pos] | (src[pos + 1] << 8)
            pos += 2
            if line_len < 1 or pos + line_len > src_len or src[pos + line_len - 1] != EOL:
                return False
            line_end = pos + line_len - 1
            x = 0
            if row & 1:
                yp = row * width
                while pos < line_end and x < width:
                    b = src[pos]
                    if b & 1:
                        x += b >> 1
                        pos += 1
                    else:
                        yf[yp + x] = b
                        x += 1
                        pos += 1
            else:
                yp = row * width
                up = (row >> 1) * uw
                while pos < line_end and x < width:
                    b = src[pos]
                    if b & 1:
                        x += b >> 1
                        pos += 1
                    else:
                        if pos + 4 > line_end:
                            break
                        yf[yp + x] = src[pos]
                        uf[up + (x >> 1)] = src[pos + 1]
                        yf[yp + x + 1] = src[pos + 2]
                        vf[up + (x >> 1)] = src[pos + 3]
                        x += 2
                        pos += 4
            pos = line_end + 1
        return True

    def _decode_compressed_422(self, src, y, u, v, width, height):
        pos = 0
        src_len = len(src)
        yf = y.ravel()
        uf = u.ravel()
        vf = v.ravel()
        uw = width >> 1
        for row in range(height):
            if pos + 2 > src_len:
                return False
            line_len = src[pos] | (src[pos + 1] << 8)
            pos += 2
            if line_len < 1 or pos + line_len > src_len or src[pos + line_len - 1] != EOL:
                return False
            line_end = pos + line_len - 1
            x = 0
            yp = row * width
            up = row * uw
            while pos < line_end and x < width:
                b = src[pos]
                if b & 1:
                    x += b >> 1
                    pos += 1
                else:
                    if pos + 4 > line_end:
                        break
                    yf[yp + x] = src[pos]
                    uf[up + (x >> 1)] = src[pos + 1]
                    yf[yp + x + 1] = src[pos + 2]
                    vf[up + (x >> 1)] = src[pos + 3]
                    x += 2
                    pos += 4
            pos = line_end + 1
        return True


class QX3Camera:
    def __init__(self):
        self.dev = None
        self.ep_in = None
        self.packet_size = 448
        self.iso = None
        self._cmd_lock = threading.Lock()

    def find(self):
        import usb.backend.libusb1 as libusb1
        dll = find_libusb_dll()
        backend = libusb1.get_backend(find_library=lambda x: dll)
        self.dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
        return self.dev is not None

    def open(self):
        self.dev.set_configuration()
        try:
            self.dev.reset()
            time.sleep(0.5)
        except Exception:
            pass
        self.dev.set_configuration()
        best_alt, best_pkt, best_ep = 1, 0, None
        cfg = self.dev.get_active_configuration()
        for intf in cfg:
            if intf.bInterfaceNumber != 0:
                continue
            for ep in intf:
                if usb.util.endpoint_direction(ep.bEndpointAddress) != usb.util.ENDPOINT_IN:
                    continue
                pkt = ep.wMaxPacketSize & 0x07FF
                if pkt > best_pkt:
                    best_alt = intf.bAlternateSetting
                    best_pkt = pkt
                    best_ep = ep
        if best_ep is None:
            raise RuntimeError("No isochronous IN endpoint found")
        self.dev.set_interface_altsetting(interface=0, alternate_setting=best_alt)
        self.ep_in = best_ep
        self.packet_size = best_pkt or 448
        self.iso = IsoPump(self.dev, self.ep_in.bEndpointAddress, self.packet_size)

    def close(self):
        iso_safe = True
        if self.iso is not None:
            try:
                iso_safe = bool(self.iso.stop())
            except Exception:
                iso_safe = False
            if iso_safe:
                self.iso = None
        if self.dev and iso_safe:
            try:
                try:
                    self.dev.set_interface_altsetting(interface=0, alternate_setting=0)
                except Exception:
                    pass
                usb.util.dispose_resources(self.dev)
            except Exception:
                pass
            self.dev = None

    def command(self, cmd, a=0, b=0, c=0, d=0, data=None):
        with self._cmd_lock:
            if data:
                self.dev.ctrl_transfer(0x40, cmd, a | (b << 8), c | (d << 8), bytes(data), 2000)
            elif cmd & 0x8000:
                return self.dev.ctrl_transfer(0xC0, cmd, a | (b << 8), c | (d << 8), 8, 2000)
            else:
                self.dev.ctrl_transfer(0x40, cmd, a | (b << 8), c | (d << 8), None, 2000)

    def initialize(self, roi=QX3_NATIVE_ROI):
        col0, col1, row0, row1 = roi
        for attempt in range(3):
            try:
                self.command(0x4005)
                time.sleep(0.1)
                self.command(0x4004)
                time.sleep(0.1)
                self.command(0x40C3, 1, 0, 0, 0)
                self.command(0x40CA, 0, 0, 0, 0)
                self.command(0x40CB, 1, 15, 5, 0)
                self.command(0x40C8, 1, 0, 0, 0)
                self.command(0x40C9, col0, col1, row0, row1)
                self.command(0x40CC, 6, 6, 0, 0)
                self.command(0x4026, 0, 0, 0, 0)
                self.command(0x40CD, 0, 0, 0, 0, data=bytes([3, 11, 1, 3, 2, 5, 3, 2]))
                self.command(0x40A7, 1, 1, 0, 0)
                self.command(0x40A4, 4, 1, 1, 1, data=bytes([7, 0, 10, 0, 220, 214, 214, 230]))
                self.command(0x40A4, 0, 2, 0, 0, data=bytes([7, 0, 10, 0, 0, 0, 0, 0]))
                self.command(0x40A6, 2, 0, 0, 0)
                self.command(0x40A3, 50, 48, 50, 0)
                self.command(0x40A9, 0x18, 0x16, 0x24, 0x34)
                self.command(0x40AA, 0, 76, 146, 0)
                self.command(0x40AB, 20, 24, 26, 26)
                return
            except Exception:
                if attempt < 2:
                    time.sleep(0.5)
                    try:
                        self.dev.reset()
                        time.sleep(0.5)
                    except Exception:
                        pass
                else:
                    raise

    def set_roi(self, col_start, col_end, row_start, row_end):
        self.command(0x40C9, col_start, col_end, row_start, row_end)

    def set_compression(self, enabled):
        self.command(0x40CA, 1 if enabled else 0, 0, 0, 0)

    def set_lights(self, top=False, bottom=False):
        self.command(0x4022, 0x90, 0x8f, 0x50, 0)
        time.sleep(0.05)
        p1 = (0 if bottom else 1) << 1
        p2 = (0 if top else 1) << 3
        self.command(0x4024, 2, 0, p1 | p2 | 0xe0, 0)
        time.sleep(0.05)

    def set_exposure(self, gain=0, coarse_exp_lo=10):
        self.command(0x40A4, 4, 1, 1, 1, data=bytes([gain, 0, coarse_exp_lo, 0, 220, 214, 214, 230]))
        self.command(0x40A4, 0, 2, 0, 0, data=bytes([gain, 0, coarse_exp_lo, 0, 0, 0, 0, 0]))

    def set_brightness(self, brightness):
        self.command(0x40A3, brightness, 48, 50, 0)

    def set_contrast(self, contrast):
        self.command(0x40A3, 50, contrast, 50, 0)

    def set_saturation(self, saturation):
        self.command(0x40A3, 50, 48, saturation, 0)

    def start_stream(self):
        if self.iso is not None:
            self.iso.start()
        self.command(0x40C4, 0, 120, 0, 0)
        time.sleep(0.05)
        self.command(0x40C6, 0, 0, 0, 0)

    def stop_stream(self):
        if self.iso is not None:
            try:
                self.iso.stop()
            except Exception:
                pass
        try:
            self.command(0x40C7)
            self.command(0x40C5)
        except Exception:
            pass


class QX3GUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Intel Play QX3 Microscope")
        self.root.geometry("1040x760")
        self.root.minsize(850, 600)

        # (name, col_start, col_end, row_start, row_end, out_w, out_h)
        # 704x576 is 2x full CIF (4CIF). Intel Play used a 320x240 crop
        # interpolated to 512x384; this uses the whole sensor.
        self.resolution_presets = [
            ("704x576 (Full CIF interpolated)", 0, 44, 0, 72, 704, 576),
            ("512x384 (Intel Play interpolated)", 2, 42, 6, 66, 512, 384),
            ("320x240 (QX3 native)", 2, 42, 6, 66, 320, 240),
            ("352x288 (Full CIF)", 0, 44, 0, 72, 352, 288),
            ("304x252", 3, 41, 5, 68, 304, 252),
            ("256x216", 6, 38, 9, 63, 256, 216),
            ("160x144", 12, 32, 18, 54, 160, 144),
            ("64x72 (Fast)", 18, 26, 24, 42, 64, 72),
        ]
        self.current_resolution = self.resolution_presets[0]

        self.cam = QX3Camera()
        self.decoder = CpiaDecoder()
        self.current_image = None
        self.frame_count = 0
        self.recording = False
        self.video_writer = None
        self.streaming = False
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self._dec_lock = threading.Lock()
        self._buf_lock = threading.Lock()
        self._usb_buf = bytearray()
        self._new_frame_available = False
        self._first_frame = 6
        self._compression_on = False
        self._fps_count = 0
        self._fps_t0 = time.perf_counter()
        self._fps = 0.0
        self.decode_thread = None
        self._waiting_for_frame = False

        self._build_gui()
        self._connect_camera()

    def _build_gui(self):
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        content_frame = tk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True)

        video_frame = tk.LabelFrame(content_frame, text="Live Preview")
        video_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        self.wait_label = tk.Label(
            video_frame,
            text="",
            fg='#f5d76e',
            bg='black',
            font=('Segoe UI', 12, 'bold'),
        )
        self.video_label = tk.Label(video_frame, bg='black')
        self.video_label.pack(fill=tk.BOTH, expand=True)

        controls_frame = tk.Frame(content_frame, width=250)
        controls_frame.pack(side=tk.RIGHT, fill=tk.Y)
        controls_frame.pack_propagate(False)

        res_frame = tk.LabelFrame(controls_frame, text="Resolution")
        res_frame.pack(fill=tk.X, pady=(0, 5), padx=5)
        self.resolution_var = tk.StringVar(value=self.current_resolution[0])
        res_names = [r[0] for r in self.resolution_presets]
        tk.OptionMenu(res_frame, self.resolution_var, *res_names,
                      command=self._on_resolution_change).pack(fill=tk.X)

        lights_frame = tk.LabelFrame(controls_frame, text="Lights")
        lights_frame.pack(fill=tk.X, pady=(0, 5), padx=5)
        self.top_light_var = tk.BooleanVar(value=True)
        self.bottom_light_var = tk.BooleanVar(value=True)
        tk.Checkbutton(lights_frame, text="Top", variable=self.top_light_var, command=self._toggle_lights).pack(anchor=tk.W)
        tk.Checkbutton(lights_frame, text="Bottom", variable=self.bottom_light_var, command=self._toggle_lights).pack(anchor=tk.W)

        exp_frame = tk.LabelFrame(controls_frame, text="Exposure")
        exp_frame.pack(fill=tk.X, pady=(0, 5), padx=5)
        tk.Label(exp_frame, text="Gain:").pack(anchor=tk.W)
        self.gain_var = tk.IntVar(value=0)
        tk.Scale(exp_frame, from_=0, to=7, variable=self.gain_var, orient=tk.HORIZONTAL, command=lambda v: self._update_exposure()).pack(fill=tk.X)
        tk.Label(exp_frame, text="Exp:").pack(anchor=tk.W)
        self.coarse_var = tk.IntVar(value=10)
        tk.Scale(exp_frame, from_=1, to=100, variable=self.coarse_var, orient=tk.HORIZONTAL, command=lambda v: self._update_exposure()).pack(fill=tk.X)

        colour_frame = tk.LabelFrame(controls_frame, text="Colour")
        colour_frame.pack(fill=tk.X, pady=(0, 5), padx=5)
        tk.Label(colour_frame, text="Bright:").pack(anchor=tk.W)
        self.brightness_var = tk.IntVar(value=50)
        tk.Scale(colour_frame, from_=0, to=100, variable=self.brightness_var, orient=tk.HORIZONTAL, command=lambda v: self.cam.set_brightness(int(float(v)))).pack(fill=tk.X)
        tk.Label(colour_frame, text="Cont:").pack(anchor=tk.W)
        self.contrast_var = tk.IntVar(value=48)
        tk.Scale(colour_frame, from_=0, to=100, variable=self.contrast_var, orient=tk.HORIZONTAL, command=lambda v: self.cam.set_contrast(int(float(v)))).pack(fill=tk.X)
        tk.Label(colour_frame, text="Sat:").pack(anchor=tk.W)
        self.saturation_var = tk.IntVar(value=50)
        tk.Scale(colour_frame, from_=0, to=100, variable=self.saturation_var, orient=tk.HORIZONTAL, command=lambda v: self.cam.set_saturation(int(float(v)))).pack(fill=tk.X)

        capture_frame = tk.LabelFrame(controls_frame, text="Capture")
        capture_frame.pack(fill=tk.X, pady=(0, 5), padx=5)
        tk.Button(capture_frame, text="Snapshot", command=self._snapshot).pack(fill=tk.X, pady=1)
        self.record_btn = tk.Button(capture_frame, text="Record", command=self._toggle_record)
        self.record_btn.pack(fill=tk.X, pady=1)

        self.status_var = tk.StringVar(value="Ready")
        status_bar = tk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN)
        status_bar.pack(fill=tk.X, pady=(5, 0))

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _show_wait(self, text="Please wait..."):
        self._waiting_for_frame = True
        self.wait_label.configure(text=text)
        if not self.wait_label.winfo_manager():
            self.wait_label.pack(fill=tk.X, pady=(8, 2), before=self.video_label)

    def _hide_wait(self):
        self._waiting_for_frame = False
        self.wait_label.configure(text="")
        self.wait_label.pack_forget()

    def _connect_camera(self):
        if not self.cam.find():
            messagebox.showerror("Error", "QX3 microscope not found!")
            self.root.destroy()
            return
        try:
            self.cam.open()
            self.cam.initialize(roi=self.current_resolution[1:5])
            self._start_stream()
            self.cam.set_lights(top=True, bottom=True)
            self._show_wait()
            self.status_var.set("QX3 Microscope connected - Streaming")
            self._schedule_update()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to initialize camera:\n{e}")
            self.root.destroy()

    def _start_stream(self):
        self.streaming = True
        self.latest_frame = None
        self._new_frame_available = False
        self._usb_buf = bytearray()
        self._first_frame = 6
        self._compression_on = False
        self.decoder.reset()
        self._fps_count = 0
        self._fps_t0 = time.perf_counter()
        self._fps = 0.0
        self.decode_thread = threading.Thread(target=self._decode_loop, daemon=True)
        self.decode_thread.start()
        self.cam.start_stream()

    def _stop_stream(self):
        self.streaming = False
        if self.decode_thread is not None:
            self.decode_thread.join(timeout=2)
        self.cam.stop_stream()

    def _decode_loop(self):
        pending = bytearray()
        while self.streaming:
            chunk = b""
            if self.cam.iso is not None:
                chunk = self.cam.iso.take()
            if chunk:
                pending.extend(chunk)
            elif len(pending) < 80:
                time.sleep(0.001)
                continue

            frames, leftover = extract_frames(pending)
            pending = bytearray(leftover)
            if not frames:
                if not chunk:
                    time.sleep(0.001)
                if len(pending) > 1500000:
                    pending = pending[-65536:]
                continue

            enable_compression = False
            rgb = None
            with self._dec_lock:
                rgb = self.decoder.decode(frames[-1])
                if rgb is None:
                    continue
                _, col0, col1, row0, row1, out_w, out_h = self.current_resolution
                native_w = (col1 - col0) * 8
                native_h = (row1 - row0) * 4
                h, w = rgb.shape[:2]
                if w != native_w or h != native_h:
                    continue
                rgb = interpolate_rgb(rgb, out_w, out_h)
                if self._first_frame > 0:
                    self._first_frame -= 1
                    if self._first_frame == 0 and not self._compression_on:
                        self._compression_on = True
                        enable_compression = True

            if enable_compression:
                try:
                    self.cam.set_compression(True)
                except Exception:
                    self._compression_on = False
                    self._first_frame = 1

            if rgb is None:
                continue

            now = time.perf_counter()
            self._fps_count += 1
            elapsed = now - self._fps_t0
            if elapsed >= 0.5:
                self._fps = self._fps_count / elapsed
                self._fps_count = 0
                self._fps_t0 = now

            with self.frame_lock:
                self.latest_frame = rgb
                self._new_frame_available = True

    def _schedule_update(self):
        if not self.streaming:
            return
        with self.frame_lock:
            if self._new_frame_available and self.latest_frame is not None:
                self._new_frame_available = False
                rgb = self.latest_frame
                self._update_display(rgb)
        self.root.after(16, self._schedule_update)

    def _update_display(self, rgb):
        out_w, out_h = self.current_resolution[5], self.current_resolution[6]
        h, w = rgb.shape[:2]
        if w != out_w or h != out_h:
            return
        img = Image.fromarray(rgb)
        w, h = img.size
        max_w, max_h = 704, 576
        if w > max_w or h > max_h:
            scale = min(max_w / w, max_h / h)
            img = img.resize((int(w * scale), int(h * scale)), Image.BILINEAR)
        elif w < 256:
            scale = min(max_w / w, max_h / h, 3.0)
            img = img.resize((int(w * scale), int(h * scale)), Image.NEAREST)
        self.current_image = ImageTk.PhotoImage(img)
        self.video_label.configure(image=self.current_image)
        self.video_label.image = self.current_image
        if self._waiting_for_frame:
            self._hide_wait()
        self.frame_count += 1
        rec = "  REC" if self.recording else ""
        self.status_var.set(
            "%s  %dx%d  %.1f fps  (%d frames)%s" % (
                self.current_resolution[0], w, h, self._fps, self.frame_count, rec
            )
        )

    def _recording_loop(self):
        fps = 15
        frame_interval = 1.0 / fps
        rec_size = None
        while self.recording:
            loop_start = time.time()
            with self.frame_lock:
                rgb = self.latest_frame
            if rgb is not None and self.video_writer is not None:
                h, w = rgb.shape[:2]
                if rec_size is None:
                    rec_size = (w, h)
                if (w, h) == rec_size:
                    self.video_writer.write(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
            elapsed = time.time() - loop_start
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _on_resolution_change(self, selection):
        for preset in self.resolution_presets:
            if preset[0] == selection:
                name, col_start, col_end, row_start, row_end, out_w, out_h = preset
                self._show_wait()
                with self.frame_lock:
                    self.latest_frame = None
                    self._new_frame_available = False
                with self._dec_lock:
                    self.current_resolution = preset
                    try:
                        self.cam.set_compression(False)
                        self.cam.set_roi(col_start, col_end, row_start, row_end)
                    except Exception as e:
                        self._hide_wait()
                        self.status_var.set("Resolution change failed: %s" % e)
                        return
                    self.decoder.reset()
                    self._first_frame = 6
                    self._compression_on = False
                self.status_var.set("Please wait... %s (%dx%d)" % (name, out_w, out_h))
                break

    def _toggle_lights(self):
        top = self.top_light_var.get()
        bottom = self.bottom_light_var.get()
        self.cam.set_lights(top=top, bottom=bottom)
        self.status_var.set("Lights: top=%s, bottom=%s" % (
            "ON" if top else "OFF", "ON" if bottom else "OFF"))

    def _update_exposure(self):
        gain = self.gain_var.get()
        coarse = self.coarse_var.get()
        self.cam.set_exposure(gain=gain, coarse_exp_lo=coarse)

    def _snapshot(self):
        if self.current_image is None:
            messagebox.showwarning("Warning", "No frame available yet.")
            return
        filename = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG files", "*.png"), ("JPEG files", "*.jpg"), ("All files", "*.*")],
            initialfile="qx3_snapshot_%s.png" % datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        if filename:
            with self.frame_lock:
                rgb = self.latest_frame
            if rgb is not None:
                Image.fromarray(rgb).save(filename)
                self.status_var.set("Saved snapshot: %s" % filename)

    def _toggle_record(self):
        if not HAS_OPENCV:
            messagebox.showerror("Error", "OpenCV is required for video recording.")
            return
        if not self.recording:
            filename = filedialog.asksaveasfilename(
                defaultextension=".avi",
                filetypes=[("AVI files", "*.avi"), ("All files", "*.*")],
                initialfile="qx3_video_%s.avi" % datetime.now().strftime("%Y%m%d_%H%M%S")
            )
            if filename:
                with self.frame_lock:
                    rgb = self.latest_frame
                if rgb is not None:
                    h, w = rgb.shape[:2]
                else:
                    w, h = self.current_resolution[5], self.current_resolution[6]
                fourcc = cv2.VideoWriter_fourcc(*"XVID")
                self.video_writer = cv2.VideoWriter(filename, fourcc, 15.0, (w, h))
                self.recording = True
                self.record_thread = threading.Thread(target=self._recording_loop, daemon=True)
                self.record_thread.start()
                self.record_btn.configure(text="Stop")
                self.status_var.set("Recording to: %s" % filename)
        else:
            self.recording = False
            if hasattr(self, 'record_thread'):
                self.record_thread.join(timeout=2)
            if self.video_writer:
                self.video_writer.release()
                self.video_writer = None
            self.record_btn.configure(text="Record")
            self.status_var.set("Recording stopped")

    def _on_close(self):
        self.recording = False
        if hasattr(self, 'record_thread'):
            self.record_thread.join(timeout=2)
        if self.video_writer:
            self.video_writer.release()
        try:
            self._stop_stream()
        except Exception:
            self.streaming = False
        try:
            self.cam.close()
        except Exception:
            pass
        self.root.destroy()


def main():
    try:
        root = tk.Tk()
        QX3GUI(root)
        root.mainloop()
    except Exception:
        with open('qx3_error.log', 'w') as f:
            traceback.print_exc(file=f)


if __name__ == '__main__':
    main()
