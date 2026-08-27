# src/qx5_gui.py
#!/usr/bin/env python3
"""QX5 Microscope - GUI Driver.

Live view, LED control, image adjustment, timed snapshot sequences, and
a library of past sequences with movie playback.
"""

import os
import sys
import winsound

import tkinter as tk
from tkinter import messagebox

import usb.core
import usb.util
import usb.backend.libusb1 as usb_libusb1
from PIL import Image, ImageTk

sys.path.insert(0, os.path.dirname(__file__))
from qx3_gui import IsoPump, find_libusb_dll  # noqa: E402
from qx5_driver import VID, PID, Mars97113, split_frames, decode_frame  # noqa: E402

WIDTH, HEIGHT = 320, 240
DISPLAY_SCALE = 2
SHUTTER_FREQ_HZ = 1500
SHUTTER_DURATION_MS = 80


class QX5App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("QX5 Microscope Viewer")
        self.resizable(False, False)

        self.dev = None
        self.cam = None
        self.pump = None
        self._rx_buf = b""
        self._last_image = None
        self._photo = None

        self.led_top = tk.BooleanVar(value=False)
        self.led_bottom = tk.BooleanVar(value=False)
        self.brightness = tk.IntVar(value=15)
        self.saturation = tk.IntVar(value=200)
        self.sharpness = tk.IntVar(value=1)
        self.gamma = tk.IntVar(value=1)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if self._connect_device():
            self._pump_frames()
        # If no device was found, _connect_device already showed an error
        # dialog. The window stays open regardless - LED/slider handlers
        # guard on self.cam being None, and Library (Task 7) has no
        # hardware dependency at all, so it must stay usable either way.

    def _build_ui(self):
        self.canvas = tk.Canvas(
            self, width=WIDTH * DISPLAY_SCALE, height=HEIGHT * DISPLAY_SCALE, bg="black"
        )
        self.canvas.grid(row=0, column=0, rowspan=8, padx=8, pady=8)
        self._canvas_img_id = self.canvas.create_image(0, 0, anchor="nw")

        controls = tk.Frame(self)
        controls.grid(row=0, column=1, sticky="n", padx=8, pady=8)

        tk.Checkbutton(
            controls, text="Top light", variable=self.led_top,
            command=self._on_leds_changed,
        ).pack(anchor="w")
        tk.Checkbutton(
            controls, text="Bottom light", variable=self.led_bottom,
            command=self._on_leds_changed,
        ).pack(anchor="w")

        self._add_slider(controls, "Brightness", self.brightness, 0, 31, self._on_brightness_changed)
        self._add_slider(controls, "Saturation", self.saturation, 0, 255, self._on_saturation_changed)
        self._add_slider(controls, "Sharpness", self.sharpness, 0, 15, self._on_sharpness_changed)
        self._add_slider(controls, "Gamma", self.gamma, 0, 3, self._on_gamma_changed)

        tk.Button(controls, text="Snapshot", command=self._on_snapshot).pack(
            anchor="w", pady=(12, 0), fill="x"
        )

    def _add_slider(self, parent, label, var, lo, hi, on_change):
        tk.Label(parent, text=label).pack(anchor="w", pady=(8, 0))
        tk.Scale(
            parent, from_=lo, to=hi, orient="horizontal", variable=var,
            command=lambda _v: on_change(),
        ).pack(anchor="w", fill="x")

    def _connect_device(self):
        dll = find_libusb_dll()
        backend = usb_libusb1.get_backend(find_library=lambda x: dll)
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
        intf = usb.util.find_descriptor(cfg, bInterfaceNumber=0, bAlternateSetting=8)
        ep81 = usb.util.find_descriptor(intf, bEndpointAddress=0x81)
        pkt_size = ep81.wMaxPacketSize & 0x07FF

        self.pump = IsoPump(self.dev, 0x81, pkt_size, packets=32, nurbs=8)
        self.pump.start()
        return True

    def _pump_frames(self):
        if self.pump is None:
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
                self._last_image = img
                display_img = img.resize(
                    (WIDTH * DISPLAY_SCALE, HEIGHT * DISPLAY_SCALE), Image.NEAREST
                )
                self._photo = ImageTk.PhotoImage(display_img)
                self.canvas.itemconfig(self._canvas_img_id, image=self._photo)
            except Exception:
                pass
        self.after(80, self._pump_frames)

    def get_current_frame(self):
        """Return the most recently decoded live frame, or None."""
        return self._last_image

    def _on_leds_changed(self):
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
        if self._last_image is None:
            return
        os.makedirs("media", exist_ok=True)
        from datetime import datetime
        path = os.path.join("media", f"snapshot_{datetime.now():%Y-%m-%d_%H-%M-%S}.png")
        self._last_image.save(path)
        try:
            winsound.Beep(SHUTTER_FREQ_HZ, SHUTTER_DURATION_MS)
        except RuntimeError:
            pass

    def _on_close(self):
        if self.pump is not None:
            self.pump.stop()
        if self.cam is not None:
            self.cam.set_illuminators(top=False, bottom=False)
            self.cam.stop()
        if self.dev is not None:
            usb.util.dispose_resources(self.dev)
        self.destroy()


def main():
    app = QX5App()
    app.mainloop()


if __name__ == "__main__":
    main()
