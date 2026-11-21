"""Additive flow fields: idle sessions, traffic, process, keyed correlation."""
from __future__ import annotations

import json
from types import SimpleNamespace

from azkaban_agent.flowext import Correlator, IdleSessions, extend


def finding(value):
    return SimpleNamespace(value=value)


def test_idle_label_follows_the_threshold():
    s = IdleSessions(threshold_ms=60_000)
    assert s.label(10)["state"] == "active"
    assert s.label(61)["state"] == "idle"


def test_one_session_id_per_continuous_stretch():
    s = IdleSessions(60_000)
    a1, a2 = s.label(1)["sessionId"], s.label(2)["sessionId"]
    i1, i2 = s.label(90)["sessionId"], s.label(120)["sessionId"]
    a3 = s.label(0)["sessionId"]
    assert a1 == a2 and i1 == i2           # same stretch, same id
    assert len({a1, i1, a3}) == 3          # each transition starts a new session


def test_threshold_is_clamped():
    s = IdleSessions()
    assert s.set_threshold(10) == 5_000
    assert s.set_threshold(10**12) == 24 * 3600 * 1000
    assert s.set_threshold("junk") == 24 * 3600 * 1000   # unchanged on bad input


def test_idle_is_never_inferred_without_a_measurement():
    d = extend({"pii": []}, {"tsi": 500}, SimpleNamespace(findings=[]),
               idle=IdleSessions(), corr=Correlator(), idle_measured=False)
    assert "idle" not in d


def test_traffic_and_process_come_from_the_capture():
    d = extend({"app": "Maps", "pii": []},
               {"up": 120, "down": 4096, "proto": "HTTP/2.0", "dur_ms": 85, "pid": 4242},
               SimpleNamespace(findings=[]), idle=None, corr=Correlator(), idle_measured=False)
    assert d["traffic"] == {"uploadBytes": 120, "downloadBytes": 4096, "protocol": "HTTP/2.0", "durationMs": 85}
    assert d["process"] == {"pid": 4242, "name": "Maps"}


def test_same_value_in_two_apps_gets_the_same_fingerprint():
    c = Correlator()
    a = extend({"pii": [{"type": "adid", "redacted": "6f1c**", "confidence": 0.9}]}, {},
               SimpleNamespace(findings=[finding("6F1C-AAAA")]), idle=None, corr=c, idle_measured=False)
    b = extend({"pii": [{"type": "adid", "redacted": "6f1c**", "confidence": 0.9}]}, {},
               SimpleNamespace(findings=[finding("6f1c-aaaa ")]), idle=None, corr=c, idle_measured=False)
    fa, fb = a["pii"][0]["correlation"], b["pii"][0]["correlation"]
    assert fa["fingerprint"] == fb["fingerprint"]
    assert fa["scheme"] == "hmac-sha256" and fa["pseudonymized"] is True
    assert len(fa["fingerprint"]) == 64


def test_fingerprints_do_not_link_across_agent_runs():
    hit = lambda: {"pii": [{"type": "email", "redacted": "a**", "confidence": 1}]}
    one = extend(hit(), {}, SimpleNamespace(findings=[finding("a@b.c")]), idle=None,
                 corr=Correlator(), idle_measured=False)
    two = extend(hit(), {}, SimpleNamespace(findings=[finding("a@b.c")]), idle=None,
                 corr=Correlator(), idle_measured=False)
    assert one["pii"][0]["correlation"]["fingerprint"] != two["pii"][0]["correlation"]["fingerprint"]


def test_the_raw_value_never_appears_in_the_output():
    raw_value = "someone@example.com"
    d = extend({"pii": [{"type": "email", "redacted": "so*****@ex*****.com", "confidence": 1}]}, {},
               SimpleNamespace(findings=[finding(raw_value)]), idle=None, corr=Correlator(),
               idle_measured=False)
    assert raw_value not in json.dumps(d)


def test_different_types_with_the_same_text_do_not_collide():
    c = Correlator()
    assert c.fingerprint("phone", "12345") != c.fingerprint("imei", "12345")
