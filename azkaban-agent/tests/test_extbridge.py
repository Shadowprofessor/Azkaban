"""Extension bridge: validation, routing, and the producer-only boundary."""
from __future__ import annotations

import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from azkaban_agent.extbridge import (ExtensionBridge, clean_detection,
                                     clean_site_score)
from azkaban_agent.wsserver import EXTENSION_ORIGIN, Hub, start_ws

EXT_ORIGIN = "chrome-extension://" + "a" * 32
PORT = 8791


def status() -> dict:
    return {"type": "status", "version": "0.1.0", "mode": "live",
            "engines": {"llm": True, "rag": True, "model": True, "geo": True}}


# ------------------------------------------------------------------ validation
def test_detection_requires_a_valid_host():
    assert clean_detection({"category": "advertising"}) is None
    assert clean_detection({"host": "not a host!"}) is None
    assert clean_detection({"host": "x" * 300}) is None
    assert clean_detection("string") is None
    assert clean_detection(None) is None


def test_detection_normalises_host_and_clamps_values():
    d = clean_detection({"host": "QuietPixel.IO.", "confidence": 7, "bytes": "512",
                         "severity": 10**9, "category": "advertising"})
    assert d["host"] == "quietpixel.io"
    assert d["confidence"] == 1.0          # clamped to 0..1
    assert d["bytes"] == 512               # coerced from a string
    assert d["severity"] == 100            # clamped to 0..100
    assert d["source"] == "extension"


def test_unknown_kinds_and_categories_fall_back():
    d = clean_detection({"host": "a.io", "kind": "../../etc/passwd", "category": "<script>"})
    assert d["kind"] == "unknown_tracker"
    assert d["category"] == "unknown"


def test_only_known_redacted_pii_types_survive():
    d = clean_detection({"host": "a.io", "pii": [
        {"type": "ssn", "redacted": "123-45-6789"},        # not a contract type
        {"type": "gps", "redacted": "13.0,77.6", "confidence": 0.8},
        "not a dict",
    ]})
    assert [h["type"] for h in d["pii"]] == ["gps"]


def test_pii_list_is_capped():
    d = clean_detection({"host": "a.io", "pii": [{"type": "adid", "redacted": "x"}] * 99})
    assert len(d["pii"]) <= 16


def test_site_score_keeps_only_the_host_of_a_url():
    # A full URL is browsing history; only the site may be recorded.
    s = clean_site_score({"url": "https://example.com:443/private/path?token=abc",
                          "score": 77, "grade": "B"})
    assert s["site"] == "example.com"
    assert "private" not in json.dumps(s)
    assert "token" not in json.dumps(s)


def test_site_score_rejects_junk_and_defaults_the_grade():
    assert clean_site_score({"score": 10}) is None
    assert clean_site_score("x") is None
    assert clean_site_score({"site": "a.io", "grade": "Z"})["grade"] == "F"
    assert clean_site_score({"site": "a.io", "score": 10**9})["score"] == 100


def test_extension_origin_pattern_is_strict():
    assert EXTENSION_ORIGIN.match("chrome-extension://" + "a" * 32)
    assert not EXTENSION_ORIGIN.match("chrome-extension://" + "a" * 31)
    assert not EXTENSION_ORIGIN.match("chrome-extension://" + "z" * 32)   # ids are a-p
    assert not EXTENSION_ORIGIN.match("https://evil.example")


# ------------------------------------------------------------------ live routing
@pytest.fixture
async def server():
    got: list[dict] = []
    scores: list[dict] = []

    async def on_detection(d):
        got.append(d)

    async def on_score(s):
        scores.append(s)

    bridge = ExtensionBridge(status, on_detection, on_score)
    hub = Hub(status, None, extension=bridge)
    srv = await start_ws(hub, PORT)
    try:
        yield hub, bridge, got, scores
    finally:
        srv.close()
        await srv.wait_closed()


async def ext_connect():
    return connect(f"ws://127.0.0.1:{PORT}/ws/extension",
                   additional_headers={"Origin": EXT_ORIGIN})


@pytest.mark.asyncio
async def test_handshake_returns_an_ack_with_the_agent_version(server):
    async with await ext_connect() as ws:
        await ws.send(json.dumps({"type": "producer_hello", "extension_version": "0.1.0"}))
        ack = json.loads(await asyncio.wait_for(ws.recv(), 5))
    assert ack["type"] == "producer_ack"
    assert ack["agent_version"] == "0.1.0"
    assert ack["engines"]["rag"] is True


@pytest.mark.asyncio
async def test_a_detection_reaches_the_agent(server):
    _hub, bridge, got, _ = server
    async with await ext_connect() as ws:
        await ws.send(json.dumps({"type": "browser_detection",
                                  "data": {"host": "quietpixel.io", "category": "advertising",
                                           "confidence": 0.92, "site": "news.example"}}))
        await asyncio.sleep(0.25)
    assert len(got) == 1
    assert got[0]["domain"] == "quietpixel.io"
    assert bridge.detections == 1


@pytest.mark.asyncio
async def test_a_site_score_reaches_the_agent(server):
    _hub, _bridge, _got, scores = server
    async with await ext_connect() as ws:
        await ws.send(json.dumps({"type": "site_score",
                                  "data": {"site": "news.example", "score": 42, "grade": "C"}}))
        await asyncio.sleep(0.25)
    assert scores and scores[0]["grade"] == "C"


@pytest.mark.asyncio
async def test_malformed_producer_input_is_rejected_without_dropping_the_socket(server):
    async with await ext_connect() as ws:
        for bad in ["not json", json.dumps([1, 2]), json.dumps({"no_type": 1}),
                    json.dumps({"type": "browser_detection", "data": {"host": "!!"}}),
                    json.dumps({"type": "nonsense"})]:
            await ws.send(bad)
            err = json.loads(await asyncio.wait_for(ws.recv(), 5))
            assert err["type"] == "error", err
        # Still usable afterwards.
        await ws.send(json.dumps({"type": "ping"}))
        assert json.loads(await asyncio.wait_for(ws.recv(), 5))["type"] == "pong"


@pytest.mark.asyncio
async def test_an_oversized_message_is_refused(server):
    async with await ext_connect() as ws:
        await ws.send(json.dumps({"type": "browser_detection", "data": {"host": "a.io",
                                                                        "path": "x" * 300000}}))
        err = json.loads(await asyncio.wait_for(ws.recv(), 5))
    assert err["code"] == "too_large"


# ------------------------------------------------------------------ the boundary
@pytest.mark.asyncio
async def test_an_extension_cannot_reach_the_consumer_feed(server):
    """The producer origin must not get the flow feed, which carries PII."""
    with pytest.raises((ConnectionClosed, InvalidStatus, OSError)):
        async with connect(f"ws://127.0.0.1:{PORT}/ws",
                           additional_headers={"Origin": EXT_ORIGIN}) as ws:
            await asyncio.wait_for(ws.recv(), 5)


@pytest.mark.asyncio
async def test_a_producer_never_receives_flows_or_score(server):
    hub, _bridge, _got, _ = server
    async with await ext_connect() as ws:
        hub.publish({"type": "flow", "flow": {"id": "f1", "host": "x.com",
                                              "pii": [{"type": "email", "redacted": "a**"}]}})
        hub.publish({"type": "score", "score": {"total": 900, "categories": []}})
        await asyncio.sleep(0.2)
        await ws.send(json.dumps({"type": "ping"}))
        # The only thing waiting must be the pong: no flow, no score.
        msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
    assert msg["type"] == "pong", f"producer received {msg['type']}"
    assert not hub.clients, "a producer must not be registered as a feed client"


@pytest.mark.asyncio
async def test_a_website_origin_is_still_refused(server):
    with pytest.raises((InvalidStatus, OSError)):
        async with connect(f"ws://127.0.0.1:{PORT}/ws",
                           additional_headers={"Origin": "https://evil.example"}):
            pass


@pytest.mark.asyncio
async def test_the_dashboard_still_works_with_the_bridge_enabled(server):
    hub, _bridge, _got, _ = server
    async with connect(f"ws://127.0.0.1:{PORT}/ws",
                       additional_headers={"Origin": "http://localhost:5173"}) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), 5))
        assert first["type"] == "status"
        hub.publish({"type": "flow", "flow": {"id": "f2", "host": "y.com", "pii": []}})
        got = json.loads(await asyncio.wait_for(ws.recv(), 5))
    assert got["type"] == "flow"
