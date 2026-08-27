# src/qx5_capture.py
"""Timed snapshot-sequence scheduler.

No GUI or hardware knowledge - frame_provider is any zero-argument
callable returning a PIL.Image (RGB) or None if no frame is currently
available (that tick is skipped, not treated as an error).
"""

import json
import os
import threading
import time
from datetime import datetime

try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False


class CaptureSession:
    def __init__(self, root_dir, interval_s, count=None, duration_s=None,
                 video_fps=2.0):
        if (count is None) == (duration_s is None):
            raise ValueError("exactly one of count or duration_s is required")
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")

        self.root_dir = root_dir
        self.interval_s = interval_s
        self.count = count
        self.duration_s = duration_s
        self.video_fps = video_fps

        self._thread = None
        self._stop_event = threading.Event()
        self._running = False
        self._extra_metadata = {}
        self._on_frame_saved = None
        self.session_dir = None
        self._frame_count = 0
        self._skipped = 0
        self._started_at = None
        self._interrupted = False

    @property
    def is_running(self):
        return self._running

    def start(self, frame_provider, extra_metadata=None, on_frame_saved=None):
        if self._running:
            raise RuntimeError("CaptureSession already running")
        self._stop_event.clear()
        self._frame_count = 0
        self._skipped = 0
        self._interrupted = False
        self._extra_metadata = dict(extra_metadata or {})
        self._on_frame_saved = on_frame_saved
        self._started_at = datetime.now()
        folder_name = self._started_at.strftime("%Y-%m-%d_%H-%M-%S")
        self.session_dir = os.path.join(self.root_dir, folder_name)
        os.makedirs(self.session_dir, exist_ok=True)
        self._running = True
        self._thread = threading.Thread(
            target=self._run, args=(frame_provider,), daemon=True
        )
        self._thread.start()

    def stop(self):
        if not self._running:
            return
        self._interrupted = True
        self._stop_event.set()
        self._thread.join(timeout=30)

    def _run(self, frame_provider):
        deadline = None
        if self.duration_s is not None:
            deadline = time.monotonic() + self.duration_s
        try:
            while True:
                if self._stop_event.is_set():
                    break
                if self.count is not None and self._frame_count >= self.count:
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    break

                frame = frame_provider()
                if frame is not None:
                    self._frame_count += 1
                    filename = f"frame_{self._frame_count:06d}.jpg"
                    frame.save(os.path.join(self.session_dir, filename), "JPEG")
                    if self._on_frame_saved is not None:
                        self._on_frame_saved()
                else:
                    self._skipped += 1

                if self._stop_event.wait(self.interval_s):
                    break
        finally:
            self._finalize()
            self._running = False

    def _finalize(self):
        ended_at = datetime.now()
        video_failed = False
        movie_filename = None
        if self._frame_count > 0:
            candidate = "movie.mp4"
            if self._render_video(candidate):
                movie_filename = candidate
            else:
                video_failed = True

        metadata = {
            "started_at": self._started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "interval_s": self.interval_s,
            "requested_count": self.count,
            "requested_duration_s": self.duration_s,
            "frame_count": self._frame_count,
            "skipped_ticks": self._skipped,
            "interrupted": self._interrupted,
            "video_render_failed": video_failed,
            "movie_filename": movie_filename,
        }
        metadata.update(self._extra_metadata)
        with open(os.path.join(self.session_dir, "session.json"), "w") as f:
            json.dump(metadata, f, indent=2)

    def _render_video(self, filename):
        if not HAS_OPENCV:
            return False
        frame_names = sorted(
            p for p in os.listdir(self.session_dir) if p.startswith("frame_")
        )
        if not frame_names:
            return False
        first = cv2.imread(os.path.join(self.session_dir, frame_names[0]))
        if first is None:
            return False
        h, w = first.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out_path = os.path.join(self.session_dir, filename)
        writer = cv2.VideoWriter(out_path, fourcc, self.video_fps, (w, h))
        if not writer.isOpened():
            return False
        try:
            for name in frame_names:
                img = cv2.imread(os.path.join(self.session_dir, name))
                if img is not None:
                    writer.write(img)
        finally:
            writer.release()
        return True
