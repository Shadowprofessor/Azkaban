"""'Pull the cable' proof: replaying the demo opens ZERO non-loopback connections.

Every outbound path must resolve its target via getaddrinfo (asyncio's Proactor loop
connects with ConnectEx and bypasses socket.connect on Windows), so the guard sits there,
plus socket.connect / connect_ex for synchronous paths. Any non-loopback target is recorded
and refused.
"""
import ipaddress
import socket

import pytest

from azkaban_agent.config import Config
from azkaban_agent.net import EgressDenied, check_url, http_get, http_post

from replay_harness import run_demo

_real_getaddrinfo = socket.getaddrinfo
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _loopback(host) -> bool:
    if host in (None, "", "localhost"):
        return True
    try:
        return ipaddress.ip_address(str(host).strip("[]")).is_loopback
    except ValueError:
        return False


@pytest.fixture
def cable_pulled(monkeypatch):
    attempts: list[str] = []

    def getaddrinfo(host, *a, **k):
        if not _loopback(host):
            attempts.append(f"resolve {host}")
            raise socket.gaierror(f"cable pulled: {host}")
        return _real_getaddrinfo(host, *a, **k)

    def connect(self, address):
        if isinstance(address, tuple) and not _loopback(address[0]):
            attempts.append(f"connect {address}")
            raise ConnectionRefusedError(f"cable pulled: {address}")
        return _real_connect(self, address)

    def connect_ex(self, address):
        if isinstance(address, tuple) and not _loopback(address[0]):
            attempts.append(f"connect_ex {address}")
            return 111
        return _real_connect_ex(self, address)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    return attempts


def test_guard_itself_catches_external_connections(cable_pulled):
    with pytest.raises(OSError):
        socket.create_connection(("example.com", 443), timeout=1)
    assert cable_pulled, "the monkeypatch must observe external attempts"


def test_demo_replay_opens_zero_external_sockets(cable_pulled):
    res = run_demo()
    agent = res["agent"]
    assert agent.flow_count == 39   # 34 demo flows + 5 unblocked ones replayed after Patronus apply
    assert res["received"], "the WebSocket client must have received messages over loopback"
    assert res["evidence"], "evidence export must have run"
    assert cable_pulled == [], f"non-loopback egress attempted: {cable_pulled}"


def test_net_policy():
    cfg = Config(nim_url="https://integrate.api.nvidia.com/v1/chat/completions")
    assert check_url("http://127.0.0.1:11434/api/tags") == "127.0.0.1"
    assert check_url("ws://[::1]:8787") == "::1"
    for bad in ("https://example.com", "http://10.0.0.5:11434", "ftp://127.0.0.1", "http://127.0.0.1.evil.com/"):
        with pytest.raises(EgressDenied):
            check_url(bad, cfg)
    with pytest.raises(EgressDenied):           # NIM off by default
        http_post(cfg.nim_url, cfg=cfg, json={})
    with pytest.raises(EgressDenied):           # setup host needs the explicit flag
        http_get("https://download.db-ip.com/free/x.mmdb.gz")
    assert check_url("https://download.db-ip.com/free/x.mmdb.gz", allow_setup=True)
    cfg.nim_enabled = True
    assert check_url(cfg.nim_url, cfg)          # only when opted in
    with pytest.raises(EgressDenied):
        check_url(cfg.nim_url.replace("https", "http"), cfg)
