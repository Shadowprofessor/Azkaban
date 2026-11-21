"""Seconds since the operator's last keyboard/mouse input (local machine)."""
from __future__ import annotations

import subprocess
import sys
import time

IDLE_BEACON_S = 60.0


def _windows() -> float | None:
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
        return None
    tick = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    return ((tick - lii.dwTime) & 0xFFFFFFFF) / 1000.0


def _macos() -> float | None:
    out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True, timeout=2).stdout
    for line in out.splitlines():
        if "HIDIdleTime" in line:
            return int(line.split("=")[-1].strip()) / 1e9
    return None


def _linux() -> float | None:
    out = subprocess.run(["xprintidle"], capture_output=True, text=True, timeout=2).stdout.strip()
    return int(out) / 1000.0 if out.isdigit() else None


class IdleDetector:
    def __init__(self):
        self._fn = {"win32": _windows, "darwin": _macos}.get(sys.platform, _linux)
        self._cache = (0.0, 0.0)
        self.available = self.seconds() is not None

    def seconds(self) -> float | None:
        now = time.monotonic()
        if now - self._cache[0] < 0.5:
            return self._cache[1]
        try:
            v = self._fn()
        except Exception:
            v = None
        if v is not None:
            self._cache = (now, v)
        return v
