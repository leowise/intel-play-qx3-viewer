import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from qx5_driver import (
    FrameDecodeError,
    Mars97113,
    split_frames,
    decode_frame,
    MARKER,
)


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
    def test_empty_or_short_scan_is_rejected(self):
        with self.assertRaises(FrameDecodeError):
            decode_frame(b"not a jpeg at all", width=320, height=240)

        with self.assertRaises(FrameDecodeError):
            decode_frame(b"\x00" * 63, width=320, height=240)

    def test_wrong_input_type_raises(self):
        with self.assertRaises(TypeError):
            decode_frame(None, width=320, height=240)


class TestMars97113(unittest.TestCase):
    def test_brightness_uses_user_facing_direction(self):
        class FakeDevice:
            def __init__(self):
                self.writes = []

            def write(self, _endpoint, data, timeout=None):
                self.writes.append((bytes(data), timeout))

        device = FakeDevice()
        camera = Mars97113(device)
        camera.set_brightness(0)
        camera.set_brightness(30)

        self.assertEqual(device.writes, [
            (b"\x61\x1e", 500),
            (b"\x61\x00", 500),
        ])

    def test_brightness_rejects_values_outside_hardware_range(self):
        class FakeDevice:
            def write(self, *_args, **_kwargs):
                raise AssertionError("invalid brightness should not be sent")

        camera = Mars97113(FakeDevice())
        with self.assertRaises(ValueError):
            camera.set_brightness(31)

    def test_sharpness_uses_reference_range_and_encoding(self):
        class FakeDevice:
            def __init__(self):
                self.writes = []

            def write(self, _endpoint, data, timeout=None):
                self.writes.append((bytes(data), timeout))

        device = FakeDevice()
        camera = Mars97113(device)
        camera.set_sharpness(0)
        camera.set_sharpness(1)
        camera.set_sharpness(2)

        self.assertEqual(device.writes, [
            (b"\x67\x03", 500),
            (b"\x67\x07", 500),
            (b"\x67\x0b", 500),
        ])

    def test_sharpness_rejects_values_outside_reference_range(self):
        class FakeDevice:
            def write(self, *_args, **_kwargs):
                raise AssertionError("invalid sharpness should not be sent")

        camera = Mars97113(FakeDevice())
        with self.assertRaises(ValueError):
            camera.set_sharpness(3)

    def test_illuminators_reject_ambiguous_both_on_state(self):
        class FakeDevice:
            def write(self, *_args, **_kwargs):
                raise AssertionError("ambiguous command should not be sent")

        with self.assertRaises(ValueError):
            Mars97113(FakeDevice()).set_illuminators(top=True, bottom=True)


if __name__ == "__main__":
    unittest.main()
