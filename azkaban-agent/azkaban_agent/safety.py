"""Hard boundary: this tool only ever inspects the operator's own device.

Enforced in code: loopback-only binds and an explicit ownership flag.
"""
from __future__ import annotations

import ipaddress

LOOPBACK = "127.0.0.1"


class BoundaryViolation(SystemExit):
    pass


def require_loopback(host: str, what: str) -> str:
    try:
        ok = ipaddress.ip_address(host) == ipaddress.ip_address(LOOPBACK)
    except ValueError:
        ok = False
    if not ok:
        raise BoundaryViolation(
            f"[azkaban] refusing to start: {what} must bind to {LOOPBACK} only (got {host!r}). "
            "Azkaban inspects your own device; it never listens on a network interface."
        )
    return LOOPBACK


def require_ownership(flag: bool) -> None:
    if not flag:
        raise BoundaryViolation(
            "[azkaban] refusing to start: pass --i-own-this-device to confirm you are "
            "capturing ONLY a device and network you own. Intercepting third-party "
            "traffic is illegal in most jurisdictions."
        )
