# Standalone viewer and capture software for the Intel Play QX3 USB Microscope on 64-bit Windows 10/11

[![Windows 10/11](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D6?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/rinum)
[![Download](https://img.shields.io/github/v/release/Rinum/intel-play-qx3-viewer?label=Download%20.exe)](https://github.com/Rinum/intel-play-qx3-viewer/releases/download/v1.0.0/IntelPlay-QX3.exe)

## Overview

This project lets the discontinued 1999 Intel Play QX3 USB microscope work on modern 64-bit Windows 10 and Windows 11. The original Intel software and driver were 32-bit only; this viewer talks to the camera in user mode over WinUSB, with live preview, stage lights, snapshots, and video recording.

The usual way to run it is a **single `.exe`**. It can install the USB driver (one administrator prompt) and start the viewer. Python is not required on the PC that runs the `.exe`.

**[Download IntelPlay-QX3.exe](https://github.com/Rinum/intel-play-qx3-viewer/releases/download/v1.0.0/IntelPlay-QX3.exe)** (v1.0.0)

<table align="center">
  <tr>
    <td align="center">
      <img
        src="https://github.com/user-attachments/assets/2a15f046-c4be-4d97-962e-e0ae55bc9ed7"
        alt="QX3 snapshot at 10x"
        width="220"
      />
    </td>
    <td align="center">
      <img
        src="https://github.com/user-attachments/assets/e4703560-de0c-46f7-9010-aeb8f01598e5"
        alt="QX3 snapshot at 60x"
        width="220"
      />
    </td>
    <td align="center">
      <img
        src="https://github.com/user-attachments/assets/e1b6eb7d-fd9c-4719-b312-5957984e17ee"
        alt="QX3 snapshot at 200x"
        width="220"
      />
    </td>
  </tr>
  <tr>
    <td align="center"><strong>10×</strong></td>
    <td align="center"><strong>60×</strong></td>
    <td align="center"><strong>200×</strong></td>
  </tr>
</table>

## Quick Start

### Option A — standalone `.exe` (recommended)

No Python install. One file does driver setup and the viewer.

1. Download **[IntelPlay-QX3.exe](https://github.com/Rinum/intel-play-qx3-viewer/releases/download/v1.0.0/IntelPlay-QX3.exe)** (or build it locally with **`build.bat`**).
2. Plug in the microscope.
3. Double-click **`IntelPlay-QX3.exe`**.
4. The first time, Windows may ask for administrator permission so WinUSB can be installed. Click **Yes**.
5. The viewer opens. Later launches skip the driver step.

If Windows shows an unsigned-driver warning, choose **Install anyway**.

### Option B — from this folder (Python)

Use this if you are developing, or you do not have the `.exe`.

- Windows 10 or Windows 11 (64-bit)
- The Intel Play QX3 microscope and its USB cable
- [Python 3.10 or newer](https://www.python.org/downloads/) (check **Add python.exe to PATH** during setup)

1. Install Python from [python.org/downloads](https://www.python.org/downloads/) with **Add python.exe to PATH** checked.
2. Plug in the microscope.
3. Double-click **`install-driver.bat`**, then **Yes** on the administrator prompt.
4. Double-click **`run.bat`**. The first launch installs Python packages, then opens the viewer.

## Using the viewer

| Control | What it does |
| --- | --- |
| **Resolution** | Capture size. `704x576 (Full CIF interpolated)` uses the whole sensor and upscales it. `512x384 (Intel Play interpolated)` matches the original Intel software. |
| **Top / Bottom** | Stage lights (see below). |
| **Gain / Exp** | Sensor gain and exposure. |
| **Bright / Cont / Sat** | Colour adjustments. |
| **Snapshot** | Save a still image (PNG or JPEG). |
| **Record** | Start/stop AVI recording. |

Changing resolution shows **Please wait...** until the first full frame at the new size arrives.

## Stage lighting

The QX3 has two illuminators:

- **Top** — upper / reflected light (for opaque objects)
- **Bottom** — transmitted light through the stage (for slides)

Use the **Top** and **Bottom** checkboxes on the right. Both can be on at once. If a light does not change, unplug the microscope, plug it back in, and click the checkbox again.

## Troubleshooting

### The viewer says the microscope was not found

1. Confirm it is plugged in (the USB cable powers the camera).
2. Try another USB port on the PC itself, not a hub.
3. Plug the microscope in, then run **`IntelPlay-QX3.exe`** again (or **`install-driver.bat`** if you use the Python folder).
4. In **Device Manager**, look for the device. After WinUSB it often appears under **Universal Serial Bus devices**.
5. Unplug, wait 5 seconds, plug back in, then start the viewer again.

### Windows will not install the driver / unsigned driver warning

- Click **Yes** when Windows asks for administrator permission.
- If a Windows driver warning appears, choose **Install anyway**.
- You do **not** need Test Signing.
- Do not install the original 1999 `stvqx3` kernel driver on 64-bit Windows.

### Python was not found

If you are using **`IntelPlay-QX3.exe`**, Python is not required. If you are using **`run.bat`**, install Python from [python.org](https://www.python.org/downloads/) and tick **Add python.exe to PATH**.

### `pip` / package install failed

Only applies to **`run.bat`**. Connect to the internet and run it again, or: `python -m pip install -r requirements.txt`

### Live video is black, frozen, or very slow

1. Turn **Top** or **Bottom** lighting on.
2. Raise **Gain** and **Exp**.
3. Unplug other busy USB devices.
4. After a resolution change, wait for **Please wait...** to clear.
5. Unplug the microscope, plug it in again, and restart the viewer.

### Lights do not turn on

Power comes from USB. Use a direct port on the computer. Toggle **Top** / **Bottom** after the live image has started.

## Building the `.exe` (developers)

From this folder, double-click **`build.bat`**. The result is **`dist\IntelPlay-QX3.exe`** (often 70+ MB because OpenCV is bundled). That file is self-contained: driver install plus viewer. You can attach it to a GitHub Release; it is not committed to git.

> **Note:** `build.bat`, `qx3.spec`, `src/qx3_launch.py`, and `src/winusb_install.py` are referenced above and in the layout below as the intended `.exe`-packaging path, but are not yet present in this checkout - only `src/qx3_gui.py` plus the two `.bat` launchers exist today. The "Option A - standalone .exe" quick start and the release download link describe the target design, not the current working tree.

## Repository layout

```text
├── README.md
├── LICENSE
├── requirements.txt
├── IntelPlay-QX3.exe       After build.bat: dist\IntelPlay-QX3.exe
├── run.bat                 Python launcher (optional)
├── install-driver.bat      Python-folder WinUSB installer (optional)
├── build.bat               Build the standalone .exe
├── qx3.spec
├── src/qx3_launch.py       .exe entry (driver + viewer)
├── src/qx3_gui.py
├── src/winusb_install.py
└── drivers/qx3_winusb.inf
```

## QX5 support (in progress)

The repo folder is named `QX5Scope`, but everything above is written specifically for the original **QX3** (Intel/CPiA chip, USB `0813:0001`). The QX5 - Digital Blue's successor microscope - is **different hardware** and is not yet supported by `qx3_gui.py`. This section tracks that separate, in-progress effort.

### Hardware identified

The QX5 enumerates as **USB `093A:050F`** ("1.3M PC-CAM" - that string is just its USB product-string descriptor), a **PixArt / Mars-Semi MR97113** JPEG webcam ASIC, `bDeviceClass 0xFF` (vendor-specific - Windows has no built-in driver for it, so it needs the same WinUSB-binding approach as the QX3).

This chip is documented and has a full open-source Linux driver: [`drivers/media/usb/gspca/mars.c`](https://github.com/torvalds/linux/blob/master/drivers/media/usb/gspca/mars.c) (gspca_mars, by Michel Xhaard / Jean-Francois Moine). That driver is the authoritative protocol reference for everything below - no blind reverse-engineering was needed.

### Protocol summary (from gspca_mars)

- All commands are byte sequences written to **bulk-OUT endpoint `0x04`** (no vendor control transfers, unlike the QX3's CPiA protocol).
- Init = a handful of MR97113 register writes (frame size, gamma, frame-buffer size, brightness/saturation, sharpness), then 32 `mi_w` writes (`[0x1f, 0x00, addr, value]`) to program the image sensor, then `[0x00, 0x4d]` to enable isochronous streaming.
- Lights: `[0x22, byte]` - `0x76` = top on, `0x7a` = bottom on, `0x7e` = both off. (Only one-at-a-time is modeled in the Linux driver; whether both LEDs can be on simultaneously, e.g. via `0x72`, hasn't been tested yet.)
- Video is **JPEG**, not raw YUV like the QX3. The camera streams raw JPEG *scan* data only (no SOI/DQT/DHT/SOF0/SOS) framed by a sync marker (`FF FF 00 FF 96 6[4-7]`); a synthetic JPEG header + quant/Huffman tables (ported from gspca's `jpeg.h`) must be prepended to each frame before any normal JPEG decoder can read it.

### Status as of 2026-08-27

Validated end-to-end against real hardware:

- WinUSB binds cleanly to `093A:050F` (`drivers/qx5_winusb.inf`, `install-driver-qx5.bat`).
- `src/qx5_probe.py` - descriptor dump, confirms pyusb/libusb sees the device (1 config, 1 interface, 9 alt settings scaling the isochronous packet size, plus bulk command/response and interrupt endpoints).
- `src/qx5_bringup.py` - ported command layer (`Mars97113` class); sending the init sequence and the "top light on" command visibly lights the physical LED.
- `src/qx5_frame_test.py` + `src/qx5_jpeg_header.py` - full capture-to-image pipeline: captures an isochronous stream, splits it into frames on the SOF marker, patches on a reconstructed JPEG header, and decodes with PIL. **86/86 captured frames decoded as valid, uncorrupted JPEGs at the correct 320x240 size**, with real image content (visible texture/lettering under the lens at 10x).

Known gap: images are currently underexposed (the sensor's default gain/exposure, baked into the fixed `mi_data` init block from `mars.c`, is conservative for typical ambient/LED lighting). This is a tuning problem, not a protocol problem.

### Next steps

- Build `src/qx5_gui.py` (sibling to `qx3_gui.py`, reusing the existing `IsoPump` class) with live preview, lights, brightness/saturation/sharpness/gamma controls, and snapshot/record - the QX3 viewer's GUI shell can be adapted directly.
- Tune exposure/gain so the live image isn't dim (may require sensor-specific register work beyond what `mars.c` exposes as a control, since the Linux driver doesn't model exposure as a user-facing knob either).
- Confirm whether both illuminators can be lit simultaneously.
- An original QX5 install disk exists but only has a 32-bit driver, so it can't run on this 64-bit host directly; a 32-bit VM with USB passthrough plus USBPcap could capture authentic traffic later if anything above needs cross-checking, but wasn't needed for the work done so far.

## Disclaimer

This is an independent open-source revival project. It is not affiliated with, endorsed by, or supported by Intel Corporation, Mattel, or Digital Blue. Intel Play, QX3, and QX5 are used only to identify the hardware this software talks to. Use at your own risk.
