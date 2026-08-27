import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PIL import Image

import qx5_capture
from qx5_capture import CaptureSession


def make_test_image(color=(255, 0, 0)):
    return Image.new("RGB", (4, 4), color)


class TestCaptureSessionValidation(unittest.TestCase):
    def test_requires_exactly_one_of_count_or_duration(self):
        with self.assertRaises(ValueError):
            CaptureSession("root", interval_s=1.0)
        with self.assertRaises(ValueError):
            CaptureSession("root", interval_s=1.0, count=1, duration_s=1.0)

    def test_rejects_non_positive_interval(self):
        with self.assertRaises(ValueError):
            CaptureSession("root", interval_s=0, count=1)


class TestCaptureSessionRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _wait_until_done(self, session, timeout=5.0):
        deadline = time.monotonic() + timeout
        while session.is_running and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(session.is_running, "session did not finish in time")

    def test_count_based_session_saves_exact_frame_count(self):
        session = CaptureSession(self.root, interval_s=0.01, count=3)
        session.start(lambda: make_test_image())
        self._wait_until_done(session)

        frame_files = sorted(
            f for f in os.listdir(session.session_dir) if f.startswith("frame_")
        )
        self.assertEqual(len(frame_files), 3)

        with open(os.path.join(session.session_dir, "session.json")) as f:
            meta = json.load(f)
        self.assertEqual(meta["frame_count"], 3)
        self.assertFalse(meta["interrupted"])

    def test_duration_based_session_saves_at_least_one_frame(self):
        session = CaptureSession(self.root, interval_s=0.02, duration_s=0.07)
        session.start(lambda: make_test_image())
        self._wait_until_done(session)

        with open(os.path.join(session.session_dir, "session.json")) as f:
            meta = json.load(f)
        self.assertGreaterEqual(meta["frame_count"], 2)
        self.assertLessEqual(meta["frame_count"], 6)

    def test_stop_marks_session_interrupted(self):
        session = CaptureSession(self.root, interval_s=0.02, count=1000)
        session.start(lambda: make_test_image())
        time.sleep(0.05)
        session.stop()

        with open(os.path.join(session.session_dir, "session.json")) as f:
            meta = json.load(f)
        self.assertTrue(meta["interrupted"])
        self.assertGreater(meta["frame_count"], 0)
        self.assertLess(meta["frame_count"], 1000)

    def test_none_frames_are_skipped_not_saved(self):
        calls = {"n": 0}

        def provider():
            calls["n"] += 1
            return None if calls["n"] == 1 else make_test_image()

        session = CaptureSession(self.root, interval_s=0.01, count=1)
        session.start(provider)
        self._wait_until_done(session)

        with open(os.path.join(session.session_dir, "session.json")) as f:
            meta = json.load(f)
        self.assertEqual(meta["frame_count"], 1)
        self.assertEqual(meta["skipped_ticks"], 1)

    def test_extra_metadata_is_merged_into_session_json(self):
        session = CaptureSession(self.root, interval_s=0.01, count=1)
        session.start(lambda: make_test_image(), extra_metadata={"led_top": True})
        self._wait_until_done(session)

        with open(os.path.join(session.session_dir, "session.json")) as f:
            meta = json.load(f)
        self.assertTrue(meta["led_top"])

    def test_video_render_failure_is_marked_when_opencv_unavailable(self):
        original = qx5_capture.HAS_OPENCV
        qx5_capture.HAS_OPENCV = False
        try:
            session = CaptureSession(self.root, interval_s=0.01, count=2)
            session.start(lambda: make_test_image())
            self._wait_until_done(session)
        finally:
            qx5_capture.HAS_OPENCV = original

        with open(os.path.join(session.session_dir, "session.json")) as f:
            meta = json.load(f)
        self.assertTrue(meta["video_render_failed"])
        self.assertIsNone(meta["movie_filename"])

    def test_video_is_rendered_when_opencv_available(self):
        if not qx5_capture.HAS_OPENCV:
            self.skipTest("opencv not installed in this environment")
        session = CaptureSession(self.root, interval_s=0.01, count=2)
        session.start(lambda: make_test_image())
        self._wait_until_done(session)

        with open(os.path.join(session.session_dir, "session.json")) as f:
            meta = json.load(f)
        self.assertFalse(meta["video_render_failed"])
        self.assertEqual(meta["movie_filename"], "movie.mp4")
        self.assertTrue(
            os.path.isfile(os.path.join(session.session_dir, "movie.mp4"))
        )


if __name__ == "__main__":
    unittest.main()
