"""Process attribution: local socket port -> PID -> app name (psutil)."""
from __future__ import annotations

import threading
import time

import psutil


class ProcessResolver:
    """Resolves the process that owns a loopback client socket.

    The proxy sees a client connection from 127.0.0.1:<port>. The process that
    owns the socket whose *local* port is <port> is the app making the request.
    """

    def __init__(self, ttl: float = 0.5):
        self._ttl = ttl
        self._lock = threading.Lock()
        self._table: dict[int, int] = {}
        self._stamp = 0.0
        self._names: dict[int, str] = {}

    def _refresh(self) -> None:
        table: dict[int, int] = {}
        try:
            for c in psutil.net_connections(kind="tcp"):
                if c.laddr and c.pid:
                    table[c.laddr.port] = c.pid
        except (psutil.AccessDenied, OSError):
            pass
        self._table = table
        self._stamp = time.monotonic()

    def _name(self, pid: int) -> str:
        if pid not in self._names:
            try:
                n = psutil.Process(pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                n = f"pid:{pid}"
            self._names[pid] = n.removesuffix(".exe")
        return self._names[pid]

    def lookup_pid(self, local_port: int) -> tuple[str, int | None]:
        """(app name, pid) for the process owning a loopback client socket."""
        with self._lock:
            if time.monotonic() - self._stamp > self._ttl or local_port not in self._table:
                self._refresh()
            pid = self._table.get(local_port)
        if pid is None:
            return "unknown", None
        name = self._name(pid)
        return ("android-device" if name == "adb" else name), pid

    def lookup(self, local_port: int) -> str:
        with self._lock:
            if time.monotonic() - self._stamp > self._ttl or local_port not in self._table:
                self._refresh()
            pid = self._table.get(local_port)
        if pid is None:
            return "unknown"
        name = self._name(pid)
        # Phone traffic tunnelled over USB via `adb reverse` arrives from adb.
        return "android-device" if name == "adb" else name
