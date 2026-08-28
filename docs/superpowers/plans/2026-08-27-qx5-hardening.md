# QX5 Viewer Hardening and Productization Plan

**Status:** Proposed follow-up plan

**Goal:** Move the QX5 viewer from a hardware-validated prototype to a
dependable single-user Windows application for live viewing and unattended
timed capture.

## Scope

This plan addresses the operational and design gaps found during the initial
repository review. It preserves the current high-level separation:

- `qx5_driver.py` remains the Mars97113 protocol layer.
- Capture scheduling remains GUI-agnostic.
- Session folders, still frames, and `session.json` remain the durable record.
- The GUI remains a replaceable shell rather than becoming the owner of
  capture or persistence rules.

True LED dimming and a broad cross-platform rewrite stay out of scope unless a
later decision changes that boundary.

## Priority order

### P0 — Correctness and lifecycle safety

These changes come first because they affect whether unattended capture can be
trusted.

#### 1. Define a fresh-frame contract

- Introduce an explicit frame sample containing the decoded image, a monotonic
  sequence number, and capture/arrival time.
- Make the capture worker reject a sample it has already saved.
- Add a maximum frame age and a consecutive-miss policy.
- Distinguish `no frame yet`, `stale frame`, and `stream/device failure`.
- Ensure a count-based capture cannot run forever after a disconnect.
- Record the termination reason in `session.json`, for example:
  `completed`, `user_stopped`, `device_lost`, `no_fresh_frames`, or `error`.

**Acceptance criteria:** unplugging the microscope during a count-based run
finishes the session, never duplicates the last frame indefinitely, preserves
all valid frames, and records an interrupted outcome with a useful reason.

#### 2. Make session persistence failure-tolerant

- Validate positive `count`, positive `duration_s`, and positive `video_fps` in
  `CaptureSession`, not only in the GUI.
- Make session directory names collision-proof by adding sub-second precision
  or a short unique suffix.
- Prevent caller-supplied metadata from overwriting core outcome fields.
- Wrap frame acquisition, image saving, video rendering, and metadata writing
  in explicit error paths.
- Always attempt to write `session.json`, including an error field when a
  stage fails.
- Prefer atomic metadata replacement so the library never reads a partially
  written JSON file.

**Acceptance criteria:** disk/write/render failures leave a discoverable
session whenever possible, with the frames and failure reason preserved.

#### 3. Decouple shutdown from long video rendering

- Change `stop()` to request cancellation and expose completion status rather
  than blocking the Tkinter event handler for up to 30 seconds.
- Keep the UI in a stopping/finalizing state until the worker really exits.
- Do not close the USB pump or dispose the device while capture code can still
  access the current frame.
- Define bounded close behavior for an actually stuck worker and report that
  condition clearly.

**Acceptance criteria:** stopping or closing the app keeps the window
responsive, never reports `Idle` before finalization is complete, and does not
race USB teardown.

### P1 — Hardware boundary and diagnosability

#### 4. Extract shared USB transport code

- Keep `IsoPump` and libusb DLL discovery in a small shared hardware module.
- Keep the protocol module independent of the GUI.
- Remove the machine-specific hard-coded DLL fallback.
- Report missing DLL/backend, interface, endpoint, and alt-setting failures as
  actionable errors.
- Centralize cleanup for partially completed device initialization.

**Acceptance criteria:** QX5 starts through its own GUI and shared transport
module, backend discovery works on another Windows account, and every failed
setup path releases resources.

#### 5. Replace silent runtime failures with useful status

- Replace broad silent decode suppression with rate-limited diagnostics and a
  visible stream state.
- Track last received byte/frame time and show `Live`, `Waiting`, `Stale`, or
  `Disconnected`.
- Treat invalid JPEG reconstruction as a dropped frame, not a valid capture.
- Add tests for malformed, truncated, and empty scan data.

**Acceptance criteria:** a user can tell whether the camera is disconnected,
stalled, or merely producing bad frames; bad data cannot silently become a
  saved scientific observation.

#### 6. Resolve illuminator semantics

- Confirm experimentally whether both QX5 illuminators can be enabled.
- If only one is supported, make the controls mutually exclusive and keep the
  UI state synchronized with the command sent.
- If both are supported, model the command explicitly and add protocol tests.

**Acceptance criteria:** the UI never claims a light is on when the driver has
silently selected another light.

### P1 — Product usability

#### 7. Make QX5 the first-class launch path

- Add a QX5 launcher that installs/checks dependencies and starts
  `qx5_gui.py`.
- Make `run.bat` the default QX5 launcher, with `run-qx5.bat` retained as the
  explicit name.
- Update the QX5 installer handoff to point to the viewer, not only the probe.
- Keep the repository `.venv` launcher as the supported entry point and
  document its setup and usage.

**Acceptance criteria:** a new QX5 user can follow one documented path from
driver installation to live view without knowing the internal Python command.

#### 8. Finish the capture library surface

- Display thumbnail, timestamp, duration, frame count, interruption state, and
  video availability.
- Keep malformed or incomplete session folders skippable and visible through a
  diagnostic indication where practical.
- Add safe handling for missing/deleted movie files.

**Acceptance criteria:** the library communicates what happened in a session
without requiring the user to open Explorer or inspect JSON manually.

### P2 — Repository and maintenance quality

#### 9. Align documentation and repository identity

- Treat this repository as QX5-only.
- Align the repository name, README title, launcher names, and packaging docs.
- Remove or clearly label stale historical plan checkboxes.
- Avoid duplicated driver-install definitions where the embedded INF and the
  checked-in INF can drift.

#### 10. Expand automated verification

Add tests for:

- fresh-frame and stale-frame behavior;
- device-loss termination;
- session directory collisions;
- persistence failures and metadata precedence;
- worker shutdown/finalization state;
- malformed JPEG scans;
- USB setup failure cleanup using fakes;
- mutually exclusive illuminator behavior;
- launcher/package smoke checks where feasible.

Keep real-hardware checks as a separate manual acceptance suite because the
protocol and isochronous transport cannot be fully validated by unit tests.

## Suggested session sequence

1. Establish a working Windows Python test command and capture the current
   baseline.
2. Implement the fresh-frame contract and disconnect-safe capture behavior.
3. Harden session persistence and asynchronous finalization.
4. Extract shared USB transport and improve setup/teardown diagnostics.
5. Resolve LED behavior and improve stream/error status.
6. Add QX5 launch/package paths and update the README.
7. Finish the library UI and run the full hardware acceptance pass.

## Definition of done

- A count-based capture terminates safely when the microscope is unplugged.
- No stale frame can be mistaken for a newly captured frame.
- Every completed or interrupted run has durable, truthful metadata.
- Stop/close does not freeze the GUI during video rendering.
- QX5 uses only its own GUI and shared transport module.
- Driver/backend/setup failures are actionable and cleaned up.
- QX5 has a documented first-class launcher path.
- Unit tests cover the failure paths above, and the hardware smoke suite passes
  on the target Windows machine.

## Open decisions before implementation

- Are both QX5 illuminators supported simultaneously?
- Should capture stop immediately on a stale stream, or allow a configurable
  grace period for temporary USB starvation?

## Resolved decisions

- The intended deliverable is the repository `.venv` launcher. Standalone
  executable packaging is out of scope for this personal tool.
