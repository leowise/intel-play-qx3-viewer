import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from qx5_driver import split_frames, decode_frame, MARKER


def _sync(type_byte):
    # 5-byte MARKER + 1 type byte + 10 filler bytes = 16-byte sync header,
    # matching split_frames' `i += 16` after a marker match.
    return MARKER + bytes([type_byte]) + b"\x00" * 10


class TestSplitFrames(unittest.TestCase):
    def test_two_frames_between_three_markers(self):
        buf = _sync(0x64) + b"PAYLOAD1" + _sync(0x65) + b"PAYLOAD2FOO" + _sync(0x66)
        frames, boundaries = split_frames(buf)
        self.assertEqual(len(boundaries), 3)
        self.assertEqual(frames, [b"PAYLOAD1", b"PAYLOAD2FOO"])

    def test_no_markers_returns_empty(self):
        frames, boundaries = split_frames(b"no markers here at all")
        self.assertEqual(frames, [])
        self.assertEqual(boundaries, [])

    def test_trailing_incomplete_frame_is_dropped(self):
        buf = _sync(0x64) + b"PAYLOAD1" + _sync(0x65) + b"DANGLING"
        frames, boundaries = split_frames(buf)
        # last boundary has no following marker yet, so it yields no frame
        self.assertEqual(frames, [b"PAYLOAD1"])
        self.assertEqual(len(boundaries), 2)


class TestDecodeFrame(unittest.TestCase):
    def test_garbage_data_still_decodes_to_requested_size(self):
        # libjpeg tolerates malformed/empty entropy data - it fills in
        # rather than raising, so decode_frame never throws on bad bytes.
        img = decode_frame(b"not a jpeg at all", width=320, height=240)
        self.assertEqual(img.size, (320, 240))
        self.assertEqual(img.mode, "RGB")

    def test_wrong_input_type_raises(self):
        with self.assertRaises(TypeError):
            decode_frame(None, width=320, height=240)


if __name__ == "__main__":
    unittest.main()
