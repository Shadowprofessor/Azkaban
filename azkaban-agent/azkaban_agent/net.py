"""Egress guard — the ONLY module in azkaban_agent that opens outbound connections.

Runtime policy:
  * loopback only: 127.0.0.1, ::1, and "localhost" (verified to resolve to loopback);
  * the NVIDIA NIM host, only when cfg.nim_enabled (opt-in; sends aggregated metadata);
  * setup downloads (fetch-geo) only with allow_setup=True, to a fixed host list, carrying
    no user data.
Anything else raises EgressDenied before a socket is opened.

Not covered (by design): mitmproxy forwarding the operator's OWN traffic to its original
destination — that is the user's traffic, not data the agent originates.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import requests

LOOPBACK_NAMES = {"localhost"}
# Public reference data fetched only by explicit setup/training commands (never at runtime,
# never with user data): GeoIP DB, tracker blocklists, top-site lists, WhoTracks.me stats.
SETUP_HOSTS = {
    "download.db-ip.com",
    "easylist.to",
    "filters.adtidy.org",
    "raw.githubusercontent.com",
    "pgl.yoyo.org",
    "tranco-list.eu",
    "s3-us-west-1.amazonaws.com",
    "s3.amazonaws.com",
    "staticcdn.duckduckgo.com",
    "reports.exodus-privacy.eu.org",
}


class EgressDenied(PermissionError):
    pass


def _is_loopback_ip(host: str) -> bool:
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def is_loopback_host(host: str) -> bool:
    host = (host or "").lower().strip("[]")
    if _is_loopback_ip(host):
        return True
    if host in LOOPBACK_NAMES:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            return False
        return bool(infos) and all(_is_loopback_ip(i[4][0]) for i in infos)
    return False


def check_url(url: str, cfg=None, *, allow_setup: bool = False) -> str:
    """Returns the host if the URL may be contacted, else raises EgressDenied."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if p.scheme not in ("http", "https", "ws", "wss") or not host:
        raise EgressDenied(f"egress denied: unsupported URL {url!r}")
    if is_loopback_host(host):
        return host
    if cfg is not None and getattr(cfg, "nim_enabled", False):
        nim_host = (urlparse(cfg.nim_url).hostname or "").lower()
        if host == nim_host and p.scheme == "https":
            return host
    if allow_setup and host in SETUP_HOSTS and p.scheme == "https":
        return host
    raise EgressDenied(f"egress denied: {host} is not loopback"
                       + ("" if allow_setup else " (setup downloads need allow_setup=True)"))


def http_get(url: str, *, cfg=None, allow_setup: bool = False, **kw) -> requests.Response:
    check_url(url, cfg, allow_setup=allow_setup)
    return requests.get(url, allow_redirects=False, **kw)


def http_post(url: str, *, cfg=None, **kw) -> requests.Response:
    check_url(url, cfg)
    return requests.post(url, allow_redirects=False, **kw)


def local_ws_url(port: int) -> str:
    url = f"ws://127.0.0.1:{int(port)}"
    check_url(url)
    return url
