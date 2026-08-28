# QX5 GUI: Design Spec

Date: 2026-08-27

## Purpose

Build `src/qx5_gui.py`, a live-view + timed-capture + library viewer for the
QX5 microscope (Mars97113/gspca_mars protocol, already validated end-to-end
against real hardware — see `qx5_bringup.py`, `qx5_frame_test.py`,
`qx5_jpeg_header.py`). This is the primary daily-use app: the main use case
is unattended timed snapshot sequences of a saltwater aquarium (sand-grain
scale wildlife), later replayed as a composed video. Live view, LED control,
and image adjustment exist to set up a good sequence, not as the end goal.

This follows the original microscope software's core workflow (live view →
timed sequence → library → play back "the movie"). This build is an
independent reimplementation, not a port of the original binary.

## Stack decision

**tkinter**. Considered PySide6/Qt for nicer widgets
and native video playback, but rejected: none of the required features
(LED control, timed capture, library, movie playback) actually need Qt once
playback is delegated to the OS's default video player (see Library below).
tkinter needs zero new dependencies and uses the shared `IsoPump` transport
plus PIL/`ImageTk` for frame delivery.
The actual future-proofing is architectural, not toolkit-based: the capture
scheduler and library are separate, GUI-agnostic modules a future rewrite
 (Qt or another shell) could reuse without change.

## Components

### `src/qx5_driver.py` (new — extracted from `qx5_bringup.py`)

Protocol only, no GUI or threading knowledge:

- `Mars97113` command class: init/start/stop, `mi_w` sensor writes,
  `set_illuminators(top, bottom)` (on/off only — the ported protocol from
  `gspca_mars` has no LED dimming register; image brightness/gamma controls
  are used instead to compensate for lighting, both for the underexposure
  gap noted during bring-up and as the practical substitute for LED
  intensity control),
  `set_brightness`, `set_colors` (saturation), `set_gamma`, `set_sharpness`.
- VID/PID constants (`0x093A`/`0x050F`), `MI_DATA` default sensor register
  block.
- `qx5_bringup.py` and `qx5_frame_test.py` get updated to import from here
  instead of defining `Mars97113` inline, so there's one source of truth.

### `src/qx5_capture.py` (new)

Timed-sequence scheduler, no GUI or hardware knowledge:

- `CaptureSession(root_dir, interval_s, count=None, duration_s=None)` —
  exactly one of `count`/`duration_s` is required.
- `.run(frame_provider)` — background-thread loop: every `interval_s`,
  calls `frame_provider()` (returns the current decoded PIL frame),
  saves it as a numbered JPEG into a timestamped session folder under
  `root_dir`, until the count/duration is reached or `.stop()` is called.
- On completion (or stop): writes `session.json` (interval, requested vs.
  actual frame count, start/end timestamps, LED state, image settings used,
  `"interrupted": true/false`), then renders `movie.mp4` from the saved
  frames via `cv2.VideoWriter`. If OpenCV isn't available or encoding
  fails, the session JSON is still written and marked
  `"video_render_failed": true` — frames on disk are never lost or blocked
  on the video step.
- Testable without hardware: `frame_provider` is just a callable, so tests
  pass a fake one and a `tmp_path` root.

### `src/qx5_library.py` (new)

Filesystem/JSON only, no GUI:

- `list_sessions(root_dir)` — scans `root_dir` for session folders
  containing `session.json`, returns metadata (name, timestamp, frame
  count, duration, `movie.mp4` path if present) plus a thumbnail path
  (first saved frame).
- No caching/indexing beyond a directory scan — session counts here are
  small enough (personal hobby use) that this stays simple.

### `src/qx5_gui.py` (new)

The tkinter shell:

- Live view: shared `IsoPump` feeds isochronous data, split on
  the SOF marker, header-patched (`qx5_jpeg_header.py`), decoded with PIL,
  blitted to a `Canvas` via `ImageTk` on the existing polling-loop pattern.
- Controls: Top/Bottom LED checkboxes (on/off), Brightness/Contrast*/
  Saturation/Sharpness/Gamma sliders (*contrast only if the protocol
  actually exposes it — confirm against `Mars97113`; drop the slider if not).
- Snapshot button: saves the currently displayed frame as PNG, plays a
  shutter sound via `winsound` (stdlib, no new dependency).
- Timed Capture panel: interval field (seconds, 1s–hours range per your
  original use case), a duration-or-count field, Start/Stop. Wraps
  `qx5_capture.CaptureSession`, feeding it the live decoded frame as the
  `frame_provider`.
- Library window (`Toplevel`): lists sessions from `qx5_library`, each row
  shows thumbnail + timestamp + frame count/duration. "Play" hands
  `movie.mp4` to the OS default player via `os.startfile()` — no embedded
  video widget needed. "Open Folder" opens the session dir in Explorer.

## Data storage

Sessions save under `media/` at the project root (e.g.
`media/2026-08-27_14-30-00/frame_0001.jpg`, `.../session.json`,
`.../movie.mp4`). `media/` is added to a new `.gitignore` (repo currently
has none) — captures are personal data, not project source.

## Error handling

- Device disconnects mid-sequence → scheduler stops cleanly, keeps
  captured frames, still attempts the MP4 render, marks
  `"interrupted": true` in `session.json` rather than discarding the
  session.
- MP4 render failure → frames stay on disk; session is marked
  `"video_render_failed": true`; Library shows "frames only, render
  failed" instead of a Play button, rather than crashing.

## Testing

- `qx5_capture.py`: unit tests with a fake `frame_provider` and `tmp_path`
  — verify frame count, `session.json` contents, interrupted-session
  handling, MP4-render-failure handling.
- `qx5_library.py`: unit tests against a `tmp_path` with hand-built session
  folders — verify metadata parsing, thumbnail resolution, missing-video
  handling.
- `qx5_driver.py` / `qx5_gui.py`: manual verification against real
  hardware (same approach as the existing bring-up scripts) — no hardware
  mocking attempted.

## Out of scope for this build

- True LED dimming is not pursued — the ported protocol has no PWM
  register for it; image brightness/gamma is the intended substitute
  (per user decision).
- No packaged `.exe` build for `qx5_gui.py` in this pass.
