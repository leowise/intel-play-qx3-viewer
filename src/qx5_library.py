# src/qx5_library.py
"""Read back timed-capture sessions written by qx5_capture.py.

Filesystem/JSON only - no GUI knowledge.
"""

import json
import os
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Session:
    name: str
    path: str
    started_at: Optional[str]
    ended_at: Optional[str]
    interval_s: Optional[float]
    frame_count: int
    interrupted: bool
    video_render_failed: bool
    thumbnail_path: Optional[str]
    movie_path: Optional[str]


def list_sessions(root_dir: str) -> List[Session]:
    if not os.path.isdir(root_dir):
        return []

    sessions = []
    for name in sorted(os.listdir(root_dir), reverse=True):
        session_dir = os.path.join(root_dir, name)
        meta_path = os.path.join(session_dir, "session.json")
        if not os.path.isdir(session_dir) or not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        frame_files = sorted(
            p for p in os.listdir(session_dir) if p.startswith("frame_")
        )
        thumbnail_path = (
            os.path.join(session_dir, frame_files[0]) if frame_files else None
        )

        movie_filename = meta.get("movie_filename")
        movie_path = None
        if movie_filename:
            candidate = os.path.join(session_dir, movie_filename)
            if os.path.isfile(candidate):
                movie_path = candidate

        sessions.append(Session(
            name=name,
            path=session_dir,
            started_at=meta.get("started_at"),
            ended_at=meta.get("ended_at"),
            interval_s=meta.get("interval_s"),
            frame_count=meta.get("frame_count", 0),
            interrupted=meta.get("interrupted", False),
            video_render_failed=meta.get("video_render_failed", False),
            thumbnail_path=thumbnail_path,
            movie_path=movie_path,
        ))
    return sessions
