# Standalone viewer and capture software for the Intel Play QX3/QX5 USB Microscope on 64-bit Windows 10/11

[![Windows 10/11](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D6?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/rinum)

## Overview

This project lets the discontinued 1999 Intel Play QX3 USB microscope work on modern 64-bit Windows 10 and Windows 11. The original Intel software and driver were 32-bit only; this viewer talks to the camera in user mode over WinUSB, with live preview, stage lights, snapshots, and video recording.

## Quick Start

### What you need

- Windows 10 or Windows 11 (64-bit)
- The Intel Play QX3 microscope and its USB cable
- [Python 3.10 or newer](https://www.python.org/downloads/) (check **Add python.exe to PATH** during setup)

### 1. Install Python (one time)

1. Download Python from [python.org/downloads](https://www.python.org/downloads/).
2. Run the installer.
3. Check **Add python.exe to PATH**.
4. Click **Install Now**.

### 2. Install the USB driver (one time)

The old Intel driver cannot be used on 64-bit Windows. This step binds Microsoft **WinUSB** to the microscope.

1. Plug in the microscope.
2. Double-click **`install-driver.bat`**.
3. Click **Yes** on the Windows administrator prompt.
4. Wait until it says WinUSB is ready.

If Windows still asks whether to install a driver, choose **Install anyway**. The script only opens Zadig if automatic install cannot finish.

### 3. Run the viewer

1. Double-click **`run.bat`**.
2. The first launch installs the Python packages, then opens the viewer.
3. Later launches skip ahead and open the viewer directly.

If the window says the microscope was not found, finish the driver step and unplug/replug the USB cable.

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
3. Plug the microscope in, then run **`install-driver.bat`** as administrator.
4. In **Device Manager**, look for the device. After WinUSB it often appears under **Universal Serial Bus devices**.
5. Unplug, wait 5 seconds, plug back in, then run **`run.bat`** again.

### Windows will not install the driver / unsigned driver warning

- Click **Yes** when `install-driver.bat` asks for administrator permission.
- If a Windows driver warning appears, choose **Install anyway**.
- You do **not** need Test Signing.
- Do not install the original 1999 `stvqx3` kernel driver on 64-bit Windows.

### Python was not found

Install Python from [python.org](https://www.python.org/downloads/) and tick **Add python.exe to PATH**. Close and reopen `run.bat` after installing.

### `pip` / package install failed

- Connect to the internet and run `run.bat` again.
- From a Command Prompt in this folder: `python -m pip install -r requirements.txt`

### Live video is black, frozen, or very slow

1. Turn **Top** or **Bottom** lighting on.
2. Raise **Gain** and **Exp**.
3. Unplug other busy USB devices.
4. After a resolution change, wait for **Please wait...** to clear.
5. Unplug the microscope, plug it in again, and restart `run.bat`.

### Lights do not turn on

Power comes from USB. Use a direct port on the computer. Toggle **Top** / **Bottom** after the live image has started.

## Repository layout

```text
├── README.md
├── LICENSE
├── requirements.txt
├── run.bat                 Double-click to start
├── install-driver.bat      Double-click once to install WinUSB
├── src/qx3_gui.py
└── drivers/qx3_winusb.inf
```

## Disclaimer

This is an independent open-source revival project. It is not affiliated with, endorsed by, or supported by Intel Corporation, Mattel, or Digital Blue. Intel Play, QX3, and QX5 are used only to identify the hardware this software talks to. Use at your own risk.
