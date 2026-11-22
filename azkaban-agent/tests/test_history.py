"""Durable flow history: survives restarts, stores only redacted data, honours retention."""
from __future__ import annotations

import json
import time

import pytest

from azkaban_agent.history import FlowHistory


def flow(i: int, *, ts: int | None = None, pii=None, host="x.com", sev=10) -> dict:
    return {"id": f"f{i}", "ts": ts if ts is not None else int(time.time() * 1000) + i,
            "app": "App", "host": host, "method": "POST", "path": "/t", "ip": "1.2.3.4",
            "country": "US", "company": "Acme", "tracker": None, "decrypted": True,
            "pii": pii or [], "severity": sev, "tcf": None, "bytes": 100}


@pytest.fixture
def store(tmp_path):
    h = FlowHistory(tmp_path / "h.db")
    yield h
    h.close()


def test_flows_survive_closing_and_reopening(tmp_path):
    h = FlowHistory(tmp_path / "h.db")
    h.add(flow(1))
    h.close()
    again = FlowHistory(tmp_path / "h.db")
    assert [f["id"] for f in again.recent(10)] == ["f1"]
    again.close()


def test_recent_returns_newest_first(store):
    for i in range(5):
        store.add(flow(i))
    assert [f["id"] for f in store.recent(3)] == ["f4", "f3", "f2"]


def test_filters(store):
    store.add(flow(1, host="ads.example", sev=90, pii=[{"type": "adid", "redacted": "a**", "confidence": 1}]))
    store.add(flow(2, host="cdn.example", sev=5))
    assert [f["id"] for f in store.recent(10, host="ads")] == ["f1"]
    assert [f["id"] for f in store.recent(10, min_severity=50)] == ["f1"]
    assert [f["id"] for f in store.recent(10, pii_only=True)] == ["f1"]


def test_since_filter(store):
    old = int(time.time() * 1000) - 86_400_000
    store.add(flow(1, ts=old))
    store.add(flow(2))
    recent = store.recent(10, since_ms=int(time.time() * 1000) - 3_600_000)
    assert [f["id"] for f in recent] == ["f2"]


def test_retention_drops_flows_past_the_window(tmp_path):
    h = FlowHistory(tmp_path / "h.db", keep_days=7)
    h.add(flow(1, ts=int((time.time() - 30 * 86400) * 1000)))   # 30 days old
    h.add(flow(2))                                               # today
    h.flush()
    h.purge()
    assert [f["id"] for f in h.recent(10)] == ["f2"]
    h.close()


def test_keep_days_zero_keeps_everything(tmp_path):
    h = FlowHistory(tmp_path / "h.db", keep_days=0)
    h.add(flow(1, ts=int((time.time() - 3650 * 86400) * 1000)))
    h.flush()
    assert h.purge() == 0
    assert len(h.recent(10)) == 1
    h.close()


def test_forget_all_removes_every_flow(store):
    for i in range(3):
        store.add(flow(i))
    assert store.forget_all() == 3
    assert store.recent(10) == []


def test_disabled_store_writes_nothing(tmp_path):
    h = FlowHistory(tmp_path / "off.db", enabled=False)
    h.add(flow(1))
    assert h.recent(10) == [] and h.stats()["enabled"] is False
    assert not (tmp_path / "off.db").exists()


def test_only_redacted_values_are_stored(tmp_path):
    """The raw value must never reach disk: the DB is a file the user keeps."""
    raw = "someone@example.com"
    h = FlowHistory(tmp_path / "h.db")
    h.add(flow(1, pii=[{"type": "email", "redacted": "so*****@ex*****.com", "confidence": 1}]))
    h.flush()
    h.close()
    blob = (tmp_path / "h.db").read_bytes()
    assert raw.encode() not in blob
    assert b"so*****@ex*****.com" in blob


def test_a_malformed_flow_is_skipped_not_raised(store):
    store.add({"id": object()})      # unserialisable
    store.add("not a flow")          # type: ignore[arg-type]
    store.add(flow(1))
    assert [f["id"] for f in store.recent(10)] == ["f1"]


def test_stats_describe_the_store(store):
    store.add(flow(1, pii=[{"type": "gps", "redacted": "13.0,77.6", "confidence": 1}]))
    store.add(flow(2))
    s = store.stats()
    assert s["flows"] == 2 and s["withPii"] == 1 and s["sessions"] == 1


def test_a_reopened_store_counts_a_new_session(tmp_path):
    a = FlowHistory(tmp_path / "h.db"); a.add(flow(1)); a.close()
    b = FlowHistory(tmp_path / "h.db"); b.add(flow(2)); b.flush()
    assert b.stats()["sessions"] == 2
    b.close()


def test_duplicate_ids_do_not_multiply(store):
    store.add(flow(1))
    store.add(flow(1))
    assert len(store.recent(10)) == 1


def test_limit_is_bounded(store):
    for i in range(20):
        store.add(flow(i))
    assert len(store.recent(10**9)) == 20
