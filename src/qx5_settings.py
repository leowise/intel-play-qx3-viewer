"""Persistent user settings for the QX5 viewer."""

import json
import os


DEFAULT_SETTINGS = {
    "led_top": False,
    "led_bottom": False,
    "brightness": 15,
    "saturation": 200,
    "sharpness": 1,
    "gamma": 1,
}

_INTEGER_RANGES = {
    "brightness": (0, 30),
    "saturation": (0, 255),
    "sharpness": (0, 2),
    "gamma": (0, 3),
}


def _valid_settings(data):
    if not isinstance(data, dict):
        return dict(DEFAULT_SETTINGS)

    settings = dict(DEFAULT_SETTINGS)
    for key in ("led_top", "led_bottom"):
        if type(data.get(key)) is bool:
            settings[key] = data[key]

    for key, (minimum, maximum) in _INTEGER_RANGES.items():
        value = data.get(key)
        if type(value) is int and minimum <= value <= maximum:
            settings[key] = value

    # The hardware and UI model the illuminators as mutually exclusive.
    if settings["led_top"] and settings["led_bottom"]:
        settings["led_bottom"] = False
    return settings


def load_settings(path):
    """Load settings, returning defaults for missing or malformed files."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_SETTINGS)
    return _valid_settings(data)


def save_settings(path, settings):
    """Atomically save validated settings to *path*."""
    payload = _valid_settings(settings)
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)
