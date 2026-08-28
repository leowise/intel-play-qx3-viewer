# src/qx5_gui.py
#!/usr/bin/env python3
"""QX5 Microscope - GUI Driver.

Live view, LED control, image adjustment, timed snapshot sequences, and
a library of past sequences with movie playback.
"""

import os
import sys
import time
import winsound

import tkinter as tk
from tkinter import messagebox

import usb.core
import usb.util
from PIL import Image, ImageTk

sys.path.insert(0, os.path.dirname(__file__))
from usb_transport import IsoPump, get_libusb_backend  # noqa: E402
from qx5_driver import (  # noqa: E402
    VID,
    PID,
    FrameDecodeError,
    Mars97113,
    split_frames,
    decode_frame,
)
from qx5_capture import CaptureSession, FrameSample  # noqa: E402
from qx5_library import list_sessions  # noqa: E402

WIDTH, HEIGHT = 320, 240
DISPLAY_SCALE = 2
SHUTTER_FREQ_HZ = 1500
SHUTTER_DURATION_MS = 80
MEDIA_ROOT = "media"
STREAM_STALE_AFTER_S = 3.0


class LibraryWindow(tk.Toplevel):
    def __init__(self, master, media_root=MEDIA_ROOT):
        super().__init__(master)
        self.title("Capture Library")
        self.media_root = media_root
        self.sessions = []
        self._thumbnail_photo = None

        self.listbox = tk.Listbox(self, width=50, height=15)
        self.listbox.grid(row=0, column=0, columnspan=3, padx=8, pady=8)
        self.listbox.bind("<<ListboxSelect>>", self._on_selection_changed)

        self.thumbnail = tk.Label(self, text="Select a session", width=24, height=10)
        self.thumbnail.grid(row=0, column=3, padx=(0, 8), pady=8)

        tk.Button(self, text="Refresh", command=self.refresh).grid(row=1, column=0, padx=8, pady=(0, 8))
        tk.Button(self, text="Play", command=self._on_play).grid(row=1, column=1, padx=8, pady=(0, 8))
        tk.Button(self, text="Open Folder", command=self._on_open_folder).grid(row=1, column=2, padx=8, pady=(0, 8))

        self.refresh()

    def refresh(self):
        self.sessions = list_sessions(self.media_root)
        self.listbox.delete(0, tk.END)
        for s in self.sessions:
            duration = "?"
            if s.duration_s is not None:
                duration = f"{s.duration_s:.1f}s"
            state = "interrupted" if s.interrupted else "complete"
            if s.termination_reason:
                state += f": {s.termination_reason}"
            label = f"{s.name}  {s.frame_count} frames  {duration}  [{state}]"
            if s.video_render_failed:
                label += "  [frames only, render failed]"
            elif s.movie_path is None:
                label += "  [no video]"
            self.listbox.insert(tk.END, label)
        self._thumbnail_photo = None
        self.thumbnail.config(image="", text="Select a session")

    def _on_selection_changed(self, _event=None):
        session = self._selected_session()
        if session is None or session.thumbnail_path is None:
            self._thumbnail_photo = None
            self.thumbnail.config(image="", text="No thumbnail")
            return
        try:
            with Image.open(session.thumbnail_path) as image:
                image.thumbnail((160, 120))
                preview = image.copy()
            self._thumbnail_photo = ImageTk.PhotoImage(preview)
            self.thumbnail.config(image=self._thumbnail_photo, text="")
        except (OSError, ValueError):
            self._thumbnail_photo = None
            self.thumbnail.config(image="", text="Thumbnail unavailable")

    def _selected_session(self):
        selection = self.listbox.curselection()
        if not selection:
            return None
        return self.sessions[selection[0]]

    def _on_play(self):
        session = self._selected_session()
        if session is None or session.movie_path is None:
            return
        try:
            os.startfile(session.movie_path)
        except OSError as exc:
            messagebox.showerror("Playback unavailable", str(exc))
            self.refresh()

    def _on_open_folder(self):
        session = self._selected_session()
        if session is None:
            return
        try:
            os.startfile(session.path)
        except OSError as exc:
            messagebox.showerror("Folder unavailable", str(exc))


class QX5App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("QX5 Microscope Viewer")
        self.resizable(False, False)

        self.dev = None
        self.cam = None
        self.pump = None
        self._rx_buf = b""
        self._last_frame = None
        self._frame_sequence = 0
        self._bad_frame_count = 0
        self._photo = None
        self._capture_session = None
        self._closing = False

        self.led_top = tk.BooleanVar(value=False)
        self.led_bottom = tk.BooleanVar(value=False)
        self.brightness = tk.IntVar(value=15)
        self.saturation = tk.IntVar(value=200)
        self.sharpness = tk.IntVar(value=1)
        self.gamma = tk.IntVar(value=1)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Let Tk paint the window before USB setup. Device discovery and
        # initialization can block on a driver or camera, and doing that in
        # __init__ otherwise makes the application appear not to launch.
        self.after(100, self._start_device)
        # If no device was found, _connect_device already showed an error
        # dialog. The window stays open regardless - LED/slider handlers
        # guard on self.cam being None, and Library (Task 7) has no
        # hardware dependency at all, so it must stay usable either way.

    def _start_device(self):
        if self._closing:
            return
        if self._connect_device():
            self._pump_frames()

    def _build_ui(self):
        self.canvas = tk.Canvas(
            self, width=WIDTH * DISPLAY_SCALE, height=HEIGHT * DISPLAY_SCALE, bg="black"
        )
        self.canvas.grid(row=0, column=0, rowspan=8, padx=8, pady=8)
        self._canvas_img_id = self.canvas.create_image(0, 0, anchor="nw")

        controls = tk.Frame(self)
        controls.grid(row=0, column=1, sticky="n", padx=8, pady=8)

        self.stream_status = tk.Label(controls, text="Disconnected", anchor="w")
        self.stream_status.pack(anchor="w", pady=(0, 4), fill="x")

        tk.Checkbutton(
            controls, text="Top light", variable=self.led_top,
            command=lambda: self._on_led_changed("top"),
        ).pack(anchor="w")
        tk.Checkbutton(
            controls, text="Bottom light", variable=self.led_bottom,
            command=lambda: self._on_led_changed("bottom"),
        ).pack(anchor="w")

        self._add_slider(controls, "Brightness", self.brightness, 0, 30, self._on_brightness_changed)
        self._add_slider(controls, "Saturation", self.saturation, 0, 255, self._on_saturation_changed)
        self._add_slider(controls, "Sharpness", self.sharpness, 0, 15, self._on_sharpness_changed)
        self._add_slider(controls, "Gamma", self.gamma, 0, 3, self._on_gamma_changed)

        tk.Button(controls, text="Snapshot", command=self._on_snapshot).pack(
            anchor="w", pady=(12, 0), fill="x"
        )

        capture_frame = tk.LabelFrame(controls, text="Timed Capture")
        capture_frame.pack(anchor="w", pady=(12, 0), fill="x")

        tk.Label(capture_frame, text="Interval (seconds)").pack(anchor="w")
        self.capture_interval = tk.StringVar(value="5")
        tk.Entry(capture_frame, textvariable=self.capture_interval, width=10).pack(anchor="w")

        tk.Label(capture_frame, text="Duration (minutes, 0 = use count)").pack(anchor="w")
        self.capture_duration_min = tk.StringVar(value="0")
        tk.Entry(capture_frame, textvariable=self.capture_duration_min, width=10).pack(anchor="w")

        tk.Label(capture_frame, text="Frame count (used if duration = 0)").pack(anchor="w")
        self.capture_count = tk.StringVar(value="60")
        tk.Entry(capture_frame, textvariable=self.capture_count, width=10).pack(anchor="w")

        self.capture_status = tk.Label(capture_frame, text="Idle")
        self.capture_status.pack(anchor="w", pady=(4, 0))

        btn_row = tk.Frame(capture_frame)
        btn_row.pack(anchor="w", fill="x")
        self.start_capture_btn = tk.Button(btn_row, text="Start", command=self._on_start_capture)
        self.start_capture_btn.pack(side="left")
        self.stop_capture_btn = tk.Button(
            btn_row, text="Stop", command=self._on_stop_capture, state="disabled"
        )
        self.stop_capture_btn.pack(side="left")

        tk.Button(controls, text="Library...", command=self._open_library).pack(
            anchor="w", pady=(12, 0), fill="x"
        )

    def _add_slider(self, parent, label, var, lo, hi, on_change):
        tk.Label(parent, text=label).pack(anchor="w", pady=(8, 0))
        tk.Scale(
            parent, from_=lo, to=hi, orient="horizontal", variable=var,
            command=lambda _v: on_change(),
        ).pack(anchor="w", fill="x")

    def _connect_device(self):
        try:
            backend = get_libusb_backend()
            self.dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
            if self.dev is None:
                messagebox.showerror(
                    "QX5 not found",
                    "Could not find the QX5 microscope. Check the USB cable "
                    "and that the WinUSB driver is installed.",
                )
                return False

            self.dev.set_configuration()
            self.dev.set_interface_altsetting(interface=0, alternate_setting=8)
            self.cam = Mars97113(self.dev)
            self.cam.start(width=WIDTH, height=HEIGHT)

            cfg = self.dev.get_active_configuration()
            intf = usb.util.find_descriptor(
                cfg, bInterfaceNumber=0, bAlternateSetting=8
            )
            if intf is None:
                raise RuntimeError("QX5 streaming interface alt setting 8 not found")
            ep81 = usb.util.find_descriptor(intf, bEndpointAddress=0x81)
            if ep81 is None:
                raise RuntimeError("QX5 isochronous IN endpoint 0x81 not found")
            pkt_size = ep81.wMaxPacketSize & 0x07FF
            if pkt_size <= 0:
                raise RuntimeError("QX5 reported an invalid isochronous packet size")

            self.pump = IsoPump(self.dev, 0x81, pkt_size, packets=32, nurbs=8)
            self.pump.start()
            self._set_stream_status("Waiting for frames")
            return True
        except Exception as exc:
            self._cleanup_device()
            messagebox.showerror("QX5 connection failed", str(exc))
            return False

    def _cleanup_device(self):
        if self.pump is not None:
            try:
                self.pump.stop()
            except Exception:
                pass
            self.pump = None
        if self.cam is not None:
            try:
                self.cam.set_illuminators(top=False, bottom=False)
                self.cam.stop()
            except Exception:
                pass
            self.cam = None
        if self.dev is not None:
            try:
                usb.util.dispose_resources(self.dev)
            except Exception:
                pass
            self.dev = None

    def _pump_frames(self):
        if self.pump is None or self._closing:
            return
        data = self.pump.take()
        if data:
            self._rx_buf += data
        frames, boundaries = split_frames(self._rx_buf)
        if boundaries:
            self._rx_buf = self._rx_buf[boundaries[-1]:]
        if frames:
            try:
                img = decode_frame(frames[-1], width=WIDTH, height=HEIGHT)
                self._frame_sequence += 1
                self._last_frame = FrameSample(
                    image=img,
                    sequence=self._frame_sequence,
                    captured_at=time.monotonic(),
                )
                display_img = img.resize(
                    (WIDTH * DISPLAY_SCALE, HEIGHT * DISPLAY_SCALE), Image.NEAREST
                )
                self._photo = ImageTk.PhotoImage(display_img)
                self.canvas.itemconfig(self._canvas_img_id, image=self._photo)
                self._bad_frame_count = 0
                self._set_stream_status("Live")
            except FrameDecodeError as exc:
                self._bad_frame_count += 1
                self._set_stream_status(f"Bad frame ({self._bad_frame_count}): {exc}")
            except Exception as exc:
                self._set_stream_status(f"Display error: {exc}")
        elif self.pump.last_error:
            self._set_stream_status(f"Stream error: {self.pump.last_error}")
        elif self._last_frame is None:
            self._set_stream_status("Waiting for frames")
        elif time.monotonic() - self._last_frame.captured_at > STREAM_STALE_AFTER_S:
            self._set_stream_status("Stale frame")
        self.after(80, self._pump_frames)

    def _set_stream_status(self, text):
        self.stream_status.config(text=text)

    def get_current_frame(self):
        """Return the most recently decoded live FrameSample, or None."""
        return self._last_frame

    def _on_led_changed(self, source):
        if source == "top" and self.led_top.get():
            self.led_bottom.set(False)
        elif source == "bottom" and self.led_bottom.get():
            self.led_top.set(False)
        if self.cam is not None:
            self.cam.set_illuminators(top=self.led_top.get(), bottom=self.led_bottom.get())

    def _on_brightness_changed(self):
        if self.cam is not None:
            self.cam.set_brightness(self.brightness.get())

    def _on_saturation_changed(self):
        if self.cam is not None:
            self.cam.set_colors(self.saturation.get())

    def _on_sharpness_changed(self):
        if self.cam is not None:
            self.cam.set_sharpness(self.sharpness.get())

    def _on_gamma_changed(self):
        if self.cam is not None:
            self.cam.set_gamma(self.gamma.get())

    def _on_snapshot(self):
        if self._last_frame is None:
            return
        os.makedirs("media", exist_ok=True)
        from datetime import datetime
        path = os.path.join("media", f"snapshot_{datetime.now():%Y-%m-%d_%H-%M-%S}.png")
        self._last_frame.image.save(path)
        self._play_shutter_sound()

    def _play_shutter_sound(self):
        try:
            winsound.Beep(SHUTTER_FREQ_HZ, SHUTTER_DURATION_MS)
        except RuntimeError:
            pass

    def _on_start_capture(self):
        if self._capture_session is not None and self._capture_session.is_running:
            return
        try:
            interval_s = float(self.capture_interval.get())
        except ValueError:
            messagebox.showerror("Invalid interval", "Interval must be a number of seconds.")
            return

        duration_min = 0.0
        try:
            duration_min = float(self.capture_duration_min.get())
        except ValueError:
            messagebox.showerror("Invalid duration", "Duration must be a number of minutes.")
            return

        count = None
        duration_s = None
        if duration_min > 0:
            duration_s = duration_min * 60.0
        else:
            try:
                count = int(self.capture_count.get())
            except ValueError:
                messagebox.showerror("Invalid count", "Frame count must be a whole number.")
                return
            if count <= 0:
                messagebox.showerror("Invalid count", "Frame count must be positive.")
                return

        os.makedirs(MEDIA_ROOT, exist_ok=True)
        self._capture_session = CaptureSession(
            MEDIA_ROOT, interval_s=interval_s, count=count, duration_s=duration_s,
        )
        self._capture_session.start(
            self.get_current_frame,
            extra_metadata={
                "led_top": self.led_top.get(),
                "led_bottom": self.led_bottom.get(),
                "brightness": self.brightness.get(),
                "saturation": self.saturation.get(),
                "sharpness": self.sharpness.get(),
                "gamma": self.gamma.get(),
            },
            on_frame_saved=self._play_shutter_sound,
        )
        self.capture_status.config(text="Capturing...")
        self.start_capture_btn.config(state="disabled")
        self.stop_capture_btn.config(state="normal")
        self._poll_capture_status()

    def _on_stop_capture(self):
        if self._capture_session is not None:
            self._capture_session.stop(wait=False)
        self.capture_status.config(text="Finalizing...")
        self.start_capture_btn.config(state="disabled")
        self.stop_capture_btn.config(state="disabled")
        self._poll_capture_status()

    def _poll_capture_status(self):
        if self._capture_session is None:
            return
        if not self._capture_session.is_running:
            reason = self._capture_session.termination_reason
            status = "Complete" if reason == "completed" else f"Stopped: {reason}"
            self.capture_status.config(text=status)
            self.start_capture_btn.config(state="normal")
            self.stop_capture_btn.config(state="disabled")
            return
        self.after(500, self._poll_capture_status)

    def _open_library(self):
        LibraryWindow(self, media_root=MEDIA_ROOT)

    def _on_close(self):
        if self._closing:
            return
        if self._capture_session is not None and self._capture_session.is_running:
            self._closing = True
            self.capture_status.config(text="Finalizing before close...")
            self._capture_session.stop(wait=False)
            self.after(50, self._finish_close)
            return
        self._finish_close()

    def _finish_close(self):
        if self._capture_session is not None and self._capture_session.is_running:
            self.after(50, self._finish_close)
            return
        self._cleanup_device()
        self.destroy()


def main():
    app = QX5App()
    app.mainloop()


if __name__ == "__main__":
    main()
