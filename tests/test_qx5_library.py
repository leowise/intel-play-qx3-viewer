import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from qx5_library import list_sessions


def _write_session(root, name, meta, frame_names=(), movie=False):
    session_dir = os.path.join(root, name)
    os.makedirs(session_dir, exist_ok=True)
    with open(os.path.join(session_dir, "session.json"), "w") as f:
        json.dump(meta, f)
    for fn in frame_names:
        with open(os.path.join(session_dir, fn), "wb") as f:
            f.write(b"\xff\xd8fake-jpeg-bytes")
    if movie:
        with open(os.path.join(session_dir, "movie.mp4"), "wb") as f:
            f.write(b"fake-mp4-bytes")
    return session_dir


class TestListSessions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_root_returns_empty_list(self):
        self.assertEqual(list_sessions(self.root), [])

    def test_missing_root_returns_empty_list(self):
        self.assertEqual(list_sessions(os.path.join(self.root, "nope")), [])

    def test_directory_without_session_json_is_skipped(self):
        os.makedirs(os.path.join(self.root, "not-a-session"))
        self.assertEqual(list_sessions(self.root), [])

    def test_session_with_movie_is_reported(self):
        _write_session(
            self.root, "2026-08-27_10-00-00",
            {
                "started_at": "2026-08-27T10:00:00", "ended_at": "2026-08-27T10:05:00",
                "interval_s": 5.0, "frame_count": 2, "interrupted": False,
                "video_render_failed": False, "movie_filename": "movie.mp4",
            },
            frame_names=["frame_000001.jpg", "frame_000002.jpg"],
            movie=True,
        )
        sessions = list_sessions(self.root)
        self.assertEqual(len(sessions), 1)
        s = sessions[0]
        self.assertEqual(s.name, "2026-08-27_10-00-00")
        self.assertEqual(s.frame_count, 2)
        self.assertIsNotNone(s.thumbnail_path)
        self.assertTrue(s.thumbnail_path.endswith("frame_000001.jpg"))
        self.assertIsNotNone(s.movie_path)
        self.assertTrue(s.movie_path.endswith("movie.mp4"))

    def test_session_with_failed_video_has_no_movie_path(self):
        _write_session(
            self.root, "2026-08-27_11-00-00",
            {
                "started_at": "2026-08-27T11:00:00", "ended_at": "2026-08-27T11:05:00",
                "interval_s": 5.0, "frame_count": 1, "interrupted": False,
                "video_render_failed": True, "movie_filename": None,
            },
            frame_names=["frame_000001.jpg"],
            movie=False,
        )
        sessions = list_sessions(self.root)
        self.assertEqual(len(sessions), 1)
        self.assertIsNone(sessions[0].movie_path)
        self.assertTrue(sessions[0].video_render_failed)

    def test_sessions_sorted_newest_first(self):
        _write_session(self.root, "2026-08-27_09-00-00", {"frame_count": 0})
        _write_session(self.root, "2026-08-27_11-00-00", {"frame_count": 0})
        _write_session(self.root, "2026-08-27_10-00-00", {"frame_count": 0})
        names = [s.name for s in list_sessions(self.root)]
        self.assertEqual(names, [
            "2026-08-27_11-00-00", "2026-08-27_10-00-00", "2026-08-27_09-00-00",
        ])


if __name__ == "__main__":
    unittest.main()
