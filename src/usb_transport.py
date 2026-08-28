"""Windows/libusb transport helpers for the QX5 viewer.

Protocol modules should own device commands; this module only manages the
raw isochronous transport and locates the libusb runtime bundled by the
``libusb`` Python package.
"""

import os
import threading
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_int,
    c_long,
    c_ubyte,
    c_void_p,
    cast,
    string_at,
)

import usb.backend.libusb1 as usb_libusb1
import usb.core


LIBUSB_TRANSFER_COMPLETED = 0
LIBUSB_TRANSFER_ERROR = 1
LIBUSB_TRANSFER_TIMED_OUT = 2
LIBUSB_TRANSFER_CANCELLED = 3
LIBUSB_SUCCESS = 0


class _Timeval(Structure):
    _fields_ = [("tv_sec", c_long), ("tv_usec", c_long)]


class IsoPump:
    """Keep several isochronous URBs in flight and pack only real payload."""

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
        self._error = None
        self._cb = usb_libusb1._libusb_transfer_cb_fn_p(self._on_complete)

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_error(self):
        with self._lock:
            return self._error

    def _record_error(self, error):
        with self._lock:
            if self._error is None:
                self._error = str(error)
        self._alive = False

    def start(self):
        if self._alive:
            return
        with self._lock:
            self._error = None
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
                self._record_error("iso submit failed: %s" % err)
                raise usb.core.USBError("iso submit failed: %s" % err)
            self._in_flight += 1
        self._thread = threading.Thread(target=self._event_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Cancel URBs and wait until the event thread has fully stopped."""
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
            try:
                if has_timeout:
                    result = lib.libusb_handle_events_timeout(ctx, byref(tv))
                else:
                    result = lib.libusb_handle_events(ctx)
                if self._alive and result not in (None, LIBUSB_SUCCESS):
                    self._record_error("libusb event loop failed: %s" % result)
            except Exception as exc:
                self._record_error("libusb event loop failed: %s" % exc)
                break

    def _on_complete(self, xfer_p):
        resubmitted = False
        try:
            xfer = xfer_p.contents
            if xfer.status == LIBUSB_TRANSFER_ERROR:
                self._record_error("isochronous transfer reported an error")
            if self._alive and xfer.status in (
                LIBUSB_TRANSFER_COMPLETED,
                LIBUSB_TRANSFER_TIMED_OUT,
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
                resubmitted = err == LIBUSB_SUCCESS
                if not resubmitted:
                    self._record_error("iso transfer resubmit failed: %s" % err)
        except Exception as exc:
            self._record_error("iso transfer callback failed: %s" % exc)
            resubmitted = False
        if not resubmitted:
            self._in_flight = max(0, self._in_flight - 1)


def find_libusb_dll():
    """Return the bundled 64-bit libusb DLL, or ``None`` if unavailable."""
    try:
        import libusb
    except ImportError:
        return None

    pkg_dir = os.path.dirname(libusb.__file__)
    candidates = []
    for root, _dirs, files in os.walk(pkg_dir):
        for filename in files:
            if filename.lower() == "libusb-1.0.dll":
                candidates.append(os.path.join(root, filename))

    for candidate in candidates:
        if "x86_64" in os.path.dirname(candidate).lower():
            return candidate
    return None


def get_libusb_backend():
    """Load the libusb backend with a clear error when the runtime is absent."""
    dll = find_libusb_dll()
    if dll is None:
        raise RuntimeError(
            "libusb-1.0.dll was not found; install the requirements first"
        )
    backend = usb_libusb1.get_backend(find_library=lambda _name: dll)
    if backend is None:
        raise RuntimeError(f"could not load libusb backend from {dll}")
    return backend
