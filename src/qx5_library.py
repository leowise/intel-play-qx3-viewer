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
    duration_s: Optional[float]
    frame_count: int
    interrupted: bool
    termination_reason: Optional[str]
    error: Optional[str]
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
            p for p in os.listdir(session_dir)
            if p.startswith("frame_") and os.path.isfile(os.path.join(session_dir, p))
        )
        thumbnail_path = (
            os.path.join(session_dir, frame_files[0]) if frame_files else None
        )

        movie_filename = meta.get("movie_filename")
        movie_path = None
        if movie_filename:
            candidate = os.path.abspath(os.path.join(session_dir, str(movie_filename)))
            session_root = os.path.abspath(session_dir)
            try:
                is_in_session = os.path.commonpath([session_root, candidate]) == session_root
            except ValueError:
                is_in_session = False
            if is_in_session and os.path.isfile(candidate):
                movie_path = candidate

        started_at = meta.get("started_at")
        ended_at = meta.get("ended_at")
        duration_s = meta.get("duration_s")
        if not isinstance(duration_s, (int, float)):
            duration_s = None
            try:
                from datetime import datetime
                duration_s = (datetime.fromisoformat(ended_at)
                              - datetime.fromisoformat(started_at)).total_seconds()
            except (TypeError, ValueError):
                pass
        try:
            frame_count = int(meta.get("frame_count", 0))
        except (TypeError, ValueError):
            frame_count = 0

        sessions.append(Session(
            name=name,
            path=session_dir,
            started_at=started_at,
            ended_at=ended_at,
            interval_s=meta.get("interval_s"),
            duration_s=duration_s,
            frame_count=frame_count,
            interrupted=bool(meta.get("interrupted", False)),
            termination_reason=meta.get("termination_reason"),
            error=meta.get("error"),
            video_render_failed=meta.get("video_render_failed", False),
            thumbnail_path=thumbnail_path,
            movie_path=movie_path,
        ))
    return sessions
