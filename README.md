# Digital Blue QX5 Scope

Windows viewer and timed-capture software for the Digital Blue QX5 USB
microscope. The application talks to the camera in user mode through WinUSB
and supports live preview, illuminator control, snapshots, timed capture, and
a capture library.

## Quick start

Requirements:

- Windows 10 or Windows 11, 64-bit
- A Digital Blue QX5 microscope and USB cable
- Python 3.10 or newer

1. Install Python and ensure `python.exe` is available on `PATH`.
2. Plug in the microscope.
3. Run `install-driver-qx5.bat` as administrator once to bind WinUSB.
4. Double-click `run.bat` or `run-qx5.bat`.

The launcher uses the repository `.venv`, creates it when needed, and installs
the dependencies from `requirements.txt`. For development, the recommended
test command is:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Viewer controls

- **Top light / Bottom light**: select the QX5 illuminator. The controls are
  mutually exclusive until simultaneous operation is confirmed on hardware.
- **Brightness, Saturation, Sharpness, Gamma**: adjust the camera image.
- **Snapshot**: save the latest native 320x240 frame under `media/`.
- **Timed Capture**: save a count-based or duration-based sequence.
- **Library**: browse saved sessions, inspect thumbnails, play available
  movies, or open the session folder.

The stream indicator distinguishes waiting for frames, live data, stale data,
bad decoded frames, and transport errors. A capture never treats an old frame
as a new observation.

## Capture sessions

Each run is stored under `media/<timestamp>/` and contains:

- `frame_*.jpg` still images
- `session.json` with settings, timing, frame counts, termination reason, and
  error details when applicable
- `movie.mp4` when OpenCV rendering succeeds

Still frames and `session.json` remain the authoritative record if video
rendering fails. Interrupted or incomplete sessions remain discoverable when
metadata can be written.

## Hardware and protocol

The QX5 enumerates as USB `093A:050F` and uses a PixArt / Mars-Semi MR97113
JPEG webcam ASIC. Commands are written to bulk-OUT endpoint `0x04`; image data
arrives as raw JPEG scan data over an isochronous endpoint. The viewer adds the
required JPEG header before decoding each complete frame.

The protocol implementation is based on the Linux kernel's
[`gspca_mars`](https://github.com/torvalds/linux/blob/master/drivers/media/usb/gspca/mars.c)
driver.

## Troubleshooting

### The camera is not found

1. Confirm the microscope is connected.
2. Run `install-driver-qx5.bat` as administrator.
3. Check Device Manager for USB device `093A:050F` using WinUSB.
4. Try a direct USB port instead of a hub, then restart `run.bat`.

### The image is black, frozen, or stale

Turn on one illuminator and watch the stream indicator. If the indicator
reports a stream error or stale frame, unplug and reconnect the microscope and
restart the viewer.

### Python or dependency setup fails

Confirm that Python is available with:

```powershell
python --version
```

Then remove and recreate `.venv` only if it is incomplete, and run the launcher
again. The `.venv` directory is local development state and is ignored by Git.

## Repository layout

```text
├── README.md
├── LICENSE
├── requirements.txt
├── run.bat                 Default QX5 launcher
├── run-qx5.bat             Explicit QX5 launcher
├── install-driver-qx5.bat  WinUSB installer
├── drivers/qx5_winusb.inf
├── src/qx5_driver.py       MR97113 protocol and frame decoding
├── src/qx5_capture.py      GUI-agnostic capture scheduler
├── src/qx5_library.py      Session reader
├── src/qx5_gui.py          Tkinter viewer
└── tests/                  Unit and GUI-library tests
```

## Current limitations

- There is no standalone executable package yet; the supported path is the
  Python launcher.
- The sensor's gain/exposure controls are still represented by the fixed
  initialization values.
- Illuminators are modeled as on/off controls, with one light selected at a
  time.

This is an independent open-source revival project and is not affiliated with
Digital Blue or Mattel. Use at your own risk.
