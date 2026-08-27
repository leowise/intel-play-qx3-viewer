import json
import os
import sys
import tempfile
import tkinter as tk
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from qx5_gui import LibraryWindow


def _write_session(root, name, frame_count=1, movie=False):
    session_dir = os.path.join(root, name)
    os.makedirs(session_dir, exist_ok=True)
    with open(os.path.join(session_dir, "session.json"), "w") as f:
        json.dump({
            "started_at": f"{name.replace('_', 'T', 1)}",
            "frame_count": frame_count,
            "interrupted": False,
            "video_render_failed": not movie,
            "movie_filename": "movie.mp4" if movie else None,
        }, f)
    for i in range(frame_count):
        with open(os.path.join(session_dir, f"frame_{i + 1:06d}.jpg"), "wb") as f:
            f.write(b"\xff\xd8fake")
    if movie:
        with open(os.path.join(session_dir, "movie.mp4"), "wb") as f:
            f.write(b"fake-mp4")


class TestLibraryWindow(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as e:
            self.skipTest(f"no display available for tkinter: {e}")
        self._tmp = tempfile.TemporaryDirectory()
        self.media_root = self._tmp.name

    def tearDown(self):
        self.root.destroy()
        self._tmp.cleanup()

    def test_refresh_populates_sessions_from_media_root(self):
        _write_session(self.media_root, "2026-08-27_10-00-00", frame_count=3, movie=True)
        _write_session(self.media_root, "2026-08-27_11-00-00", frame_count=1, movie=False)

        win = LibraryWindow(self.root, media_root=self.media_root)
        win.refresh()

        self.assertEqual(len(win.sessions), 2)
        self.assertEqual(win.sessions[0].name, "2026-08-27_11-00-00")
        self.assertEqual(win.sessions[1].name, "2026-08-27_10-00-00")
        self.assertEqual(win.listbox.size(), 2)
        win.destroy()

    def test_refresh_on_empty_media_root(self):
        win = LibraryWindow(self.root, media_root=self.media_root)
        win.refresh()
        self.assertEqual(win.sessions, [])
        self.assertEqual(win.listbox.size(), 0)
        win.destroy()


if __name__ == "__main__":
    unittest.main()
