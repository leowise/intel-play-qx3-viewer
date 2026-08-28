# src/qx5_capture.py
"""Timed snapshot-sequence scheduler.

No GUI or hardware knowledge - frame_provider is any zero-argument callable
returning a FrameSample, or None if no frame is currently available. Image-only
providers remain supported as a compatibility path and are assigned a local
sequence number for each call.

Each session writes its metadata atomically so the library can ignore a
leftover temporary file after an interrupted process.
"""

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime

try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False


@dataclass(frozen=True)
class FrameSample:
    """A decoded frame together with its stream identity and arrival time.

    ``captured_at`` uses :func:`time.monotonic`, not wall-clock time.  That
    makes freshness checks safe across clock adjustments while keeping the
    sample independent of the GUI and USB implementation.
    """

    image: object
    sequence: int
    captured_at: float


class CaptureSession:
    def __init__(self, root_dir, interval_s, count=None, duration_s=None,
                 video_fps=2.0, max_frame_age_s=15.0,
                 max_consecutive_misses=3):
        if (count is None) == (duration_s is None):
            raise ValueError("exactly one of count or duration_s is required")
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")
        if count is not None and count <= 0:
            raise ValueError("count must be positive")
        if duration_s is not None and duration_s <= 0:
            raise ValueError("duration_s must be positive")
        if video_fps <= 0:
            raise ValueError("video_fps must be positive")
        if max_frame_age_s <= 0:
            raise ValueError("max_frame_age_s must be positive")
        if max_consecutive_misses <= 0:
            raise ValueError("max_consecutive_misses must be positive")

        self.root_dir = root_dir
        self.interval_s = interval_s
        self.count = count
        self.duration_s = duration_s
        self.video_fps = video_fps
        self.max_frame_age_s = max_frame_age_s
        self.max_consecutive_misses = max_consecutive_misses

        self._thread = None
        self._stop_event = threading.Event()
        self._running = False
        self._extra_metadata = {}
        self._on_frame_saved = None
        self.session_dir = None
        self._frame_count = 0
        self._skipped = 0
        self._consecutive_misses = 0
        self._last_sequence = None
        self._legacy_sequence = 0
        self._started_at = None
        self._interrupted = False
        self._termination_reason = None
        self._error = None
        self._error_stage = None
        self._video_render_error = None

    @property
    def is_running(self):
        return self._running

    @property
    def termination_reason(self):
        return self._termination_reason

    def start(self, frame_provider, extra_metadata=None, on_frame_saved=None):
        if self._running:
            raise RuntimeError("CaptureSession already running")
        self._stop_event.clear()
        self._frame_count = 0
        self._skipped = 0
        self._consecutive_misses = 0
        self._last_sequence = None
        self._legacy_sequence = 0
        self._interrupted = False
        self._termination_reason = None
        self._error = None
        self._error_stage = None
        self._video_render_error = None
        self._extra_metadata = dict(extra_metadata or {})
        self._on_frame_saved = on_frame_saved
        self._started_at = datetime.now()
        self.session_dir = self._create_session_dir()
        self._running = True
        self._thread = threading.Thread(
            target=self._run, args=(frame_provider,), daemon=True
        )
        self._thread.start()

    def stop(self, wait=True, timeout=30):
        """Request capture termination.

        By default this preserves the original synchronous behavior for
        callers that need the final session metadata immediately. GUI callers
        can pass ``wait=False`` and observe ``is_running`` until rendering and
        metadata finalization are complete.

        Returns ``True`` when the worker has finished, otherwise ``False``.
        """
        if not self._running:
            return True
        self._interrupted = True
        self._termination_reason = "user_stopped"
        self._stop_event.set()
        if wait:
            self._thread.join(timeout=timeout)
            return not self._thread.is_alive()
        return False

    def _create_session_dir(self):
        """Create a unique session directory without reusing old captures."""
        folder_base = self._started_at.strftime("%Y-%m-%d_%H-%M-%S-%f")
        for suffix in range(1000):
            folder_name = folder_base if suffix == 0 else f"{folder_base}-{suffix:03d}"
            session_dir = os.path.join(self.root_dir, folder_name)
            try:
                os.makedirs(session_dir)
            except FileExistsError:
                continue
            return session_dir
        raise RuntimeError("could not allocate a unique capture session directory")

    def _run(self, frame_provider):
        deadline = None
        if self.duration_s is not None:
            deadline = time.monotonic() + self.duration_s
        if self._termination_reason is None:
            self._termination_reason = "completed"
        try:
            while True:
                if self._stop_event.is_set():
                    break
                if self.count is not None and self._frame_count >= self.count:
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    break

                sample = self._get_fresh_sample(frame_provider)
                if sample is not None:
                    frame = sample.image
                    self._frame_count += 1
                    filename = f"frame_{self._frame_count:06d}.jpg"
                    frame.save(os.path.join(self.session_dir, filename), "JPEG")
                    if self._on_frame_saved is not None:
                        self._on_frame_saved()
                    self._consecutive_misses = 0
                else:
                    self._skipped += 1
                    self._consecutive_misses += 1
                    if self._consecutive_misses >= self.max_consecutive_misses:
                        self._interrupted = True
                        self._termination_reason = "no_fresh_frames"
                        break

                if self._stop_event.wait(self.interval_s):
                    break
        except Exception as exc:
            self._record_error("capture", exc)
        finally:
            self._finalize()
            self._running = False

    def _record_error(self, stage, exc):
        self._interrupted = True
        self._termination_reason = "error"
        self._error_stage = stage
        self._error = f"{type(exc).__name__}: {exc}"

    def _get_fresh_sample(self, frame_provider):
        sample = frame_provider()
        if sample is None:
            return None

        # Preserve the original image-only provider contract while callers
        # migrate to FrameSample. The GUI uses FrameSample, so stale-image
        # detection is still enforced on the production path.
        if not isinstance(sample, FrameSample):
            self._legacy_sequence += 1
            sample = FrameSample(sample, self._legacy_sequence, time.monotonic())

        if self._last_sequence is not None and sample.sequence <= self._last_sequence:
            return None
        if time.monotonic() - sample.captured_at > self.max_frame_age_s:
            return None

        self._last_sequence = sample.sequence
        return sample

    def _finalize(self):
        ended_at = datetime.now()
        video_failed = self._frame_count > 0
        movie_filename = None
        self._video_render_error = "render did not complete" if video_failed else None

        # Publish a truthful provisional result before the potentially long
        # video step. If the process is killed during rendering, the still
        # frames and an incomplete-session record remain discoverable.
        self._write_metadata_safely(self._build_metadata(
            ended_at, video_failed, movie_filename,
        ))

        if self._frame_count > 0:
            candidate = "movie.mp4"
            try:
                if self._render_video(candidate):
                    movie_filename = candidate
                    video_failed = False
                    self._video_render_error = None
            except Exception as exc:
                self._video_render_error = f"{type(exc).__name__}: {exc}"

        self._write_metadata_safely(self._build_metadata(
            ended_at, video_failed, movie_filename,
        ))

    def _build_metadata(self, ended_at, video_failed, movie_filename):
        metadata = {
            "started_at": self._started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "interval_s": self.interval_s,
            "max_frame_age_s": self.max_frame_age_s,
            "max_consecutive_misses": self.max_consecutive_misses,
            "requested_count": self.count,
            "requested_duration_s": self.duration_s,
            "duration_s": (ended_at - self._started_at).total_seconds(),
            "frame_count": self._frame_count,
            "skipped_ticks": self._skipped,
            "interrupted": self._interrupted,
            "termination_reason": self._termination_reason,
            "error_stage": self._error_stage,
            "error": self._error,
            "video_render_failed": video_failed,
            "video_render_error": self._video_render_error,
            "movie_filename": movie_filename,
        }
        reserved = set(metadata)
        metadata.update({
            key: value for key, value in self._extra_metadata.items()
            if key not in reserved
        })
        return metadata

    def _write_metadata_safely(self, metadata):
        try:
            self._write_metadata(metadata)
        except Exception as exc:
            # There may be no way to persist this error (for example, a full
            # disk), but do not let metadata failure kill the capture worker
            # before it has finished its cleanup path.
            self._record_error("metadata", exc)

    def _write_metadata(self, metadata):
        path = os.path.join(self.session_dir, "session.json")
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)

    def _render_video(self, filename):
        if not HAS_OPENCV:
            self._video_render_error = "OpenCV is not available"
            return False
        frame_names = sorted(
            p for p in os.listdir(self.session_dir) if p.startswith("frame_")
        )
        if not frame_names:
            self._video_render_error = "no frame files found"
            return False
        first = cv2.imread(os.path.join(self.session_dir, frame_names[0]))
        if first is None:
            self._video_render_error = "first frame could not be read"
            return False
        h, w = first.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out_path = os.path.join(self.session_dir, filename)
        writer = cv2.VideoWriter(out_path, fourcc, self.video_fps, (w, h))
        if not writer.isOpened():
            self._video_render_error = "video writer could not be opened"
            return False
        try:
            for name in frame_names:
                img = cv2.imread(os.path.join(self.session_dir, name))
                if img is None:
                    self._video_render_error = f"frame could not be read: {name}"
                    return False
                writer.write(img)
        finally:
            writer.release()
        return True
