"""Extension -> agent request stream (browser_flows): validation and the path to the dashboard."""
from __future__ import annotations

import asyncio
import json

from azkaban_agent.agent import Agent
from azkaban_agent.config import Config
from azkaban_agent.extbridge import ExtensionBridge, clean_browser_flow

NOW = 1_800_000_000_000


def flow(**kw):
    base = {"id": "ext-1-1", "ts": NOW - 1000, "site": "news.example", "host": "px.tracker.io",
            "method": "post", "path": "/collect?uid=123#frag", "ip": "1.2.3.4", "bytes": 512,
            "status": 204, "rtype": "ping", "ms": 41, "scheme": "https", "thirdParty": True,
            "cookieSent": True, "setCookies": ["_ga", "bad name;=x"], "blocked": "",
            "queryKeys": ["uid"]}
    base.update(kw)
    return base


def test_a_valid_request_is_normalised():
    f = clean_browser_flow(flow(), now_ms=NOW)
    assert f["method"] == "POST" and f["host"] == "px.tracker.io"
    assert f["path"] == "/collect"                 # query and fragment never kept
    assert f["query"] == "" and f["body"] == "" and f["headers"] == {}
    assert f["app"] == "news.example" and f["source"] == "extension"
    assert f["status"] == 204 and f["rtype"] == "ping" and f["dur_ms"] == 41
    assert f["setCookies"] == ["_ga"]              # malformed cookie names dropped


def test_requests_without_a_usable_host_or_method_are_dropped():
    assert clean_browser_flow(flow(host="not a host"), now_ms=NOW) is None
    assert clean_browser_flow(flow(method="BREW"), now_ms=NOW) is None
    assert clean_browser_flow("nope", now_ms=NOW) is None


def test_values_are_clamped_and_unknowns_neutralised():
    f = clean_browser_flow(flow(ts=1, status=9999, rtype="evil", blocked="all", ip="<script>"),
                           now_ms=NOW)
    assert f["ts"] == NOW                          # implausible time -> now
    assert f["status"] == 599 and f["rtype"] == "other"
    assert f["blocked"] == "" and f["ip"] == ""


class _WS:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)


def test_a_batch_reaches_the_flow_callback():
    got = []

    async def on_flow(f):
        got.append(f)

    async def noop(_):
        return None

    b = ExtensionBridge(lambda: {}, noop, noop, on_flow=on_flow)
    asyncio.run(b._dispatch(_WS(), {"type": "browser_flows",
                                    "data": [flow(id="ext-a"), flow(id="ext-b"), {"bad": 1}]}))
    assert [f["id"] for f in got] == ["ext-a", "ext-b"]
    assert b.flows == 2


def test_the_agent_publishes_browser_requests_as_dashboard_flows(tmp_path, monkeypatch):
    agent = Agent(Config(), mode="replay")        # replay: never touches the real history file
    published = []
    monkeypatch.setattr(agent.hub, "publish", lambda msg, keep=True: published.append(msg))
    asyncio.run(agent.on_browser_flow(clean_browser_flow(flow())))
    assert len(published) == 1 and published[0]["type"] == "flow"
    f = published[0]["flow"]
    assert f["host"] == "px.tracker.io" and f["source"] == "extension"
    assert f["traffic"]["status"] == 204 and f["cookieSent"] is True
    json.dumps(published[0])                       # wire-serialisable


def test_non_live_agents_never_write_history():
    assert Agent(Config(), mode="replay").history.enabled is False
