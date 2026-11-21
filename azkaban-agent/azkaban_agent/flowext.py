"""Additive flow fields the v1 dashboard (nirmit) renders.

lib/schema.ts Flow is frozen; these are OPTIONAL extra keys on the wire, so a client that
ignores them is unaffected. Every value is a measurement the agent actually made:

  idle     {state, sessionId}   from the OS's real last-input time (idle.py), never guessed
  traffic  {uploadBytes, downloadBytes, protocol, durationMs}   as mitmproxy measured them
  process  {pid, name}          the process owning the client socket (procmap.py)
  pii[i].correlation            keyed HMAC-SHA256 fingerprint of the raw value

Correlation privacy: the key is 32 random bytes generated per agent run and held only in
memory. The same advertising ID sent by two apps produces the same fingerprint, which is
what lets the dashboard show "one identity across apps", but without the key a fingerprint
cannot be dictionary-reversed to the phone number or email it came from. Restarting the
agent rotates the key, so fingerprints do not link sessions either.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

DEFAULT_IDLE_MS = 60_000


class IdleSessions:
    """Labels each flow idle/active and groups consecutive flows into sessions.

    A session is one continuous stretch of the same state. The id is stable for the whole
    stretch and changes when the user goes idle or comes back.
    """

    def __init__(self, threshold_ms: int = DEFAULT_IDLE_MS):
        self.threshold_ms = threshold_ms
        self._state: str | None = None
        self._session = ""
        self._n = 0
        self._run = os.urandom(3).hex()

    def set_threshold(self, ms) -> int:
        try:
            ms = int(ms)
        except (TypeError, ValueError):
            return self.threshold_ms
        self.threshold_ms = max(5_000, min(ms, 24 * 3600 * 1000))   # 5 s .. 24 h
        return self.threshold_ms

    def label(self, tsi_seconds: float) -> dict:
        state = "idle" if tsi_seconds * 1000 >= self.threshold_ms else "active"
        if state != self._state:
            self._state = state
            self._n += 1
            self._session = f"{state}-{self._run}-{self._n}"
        return {"state": state, "sessionId": self._session}


class Correlator:
    def __init__(self, key: bytes | None = None):
        self._key = key or os.urandom(32)

    def fingerprint(self, pii_type: str, value: str) -> str:
        norm = (value or "").strip().lower()
        return hmac.new(self._key, f"{pii_type}\x00{norm}".encode("utf-8"), hashlib.sha256).hexdigest()


def extend(flow_dict: dict, raw: dict, enriched, *, idle: IdleSessions | None,
           corr: Correlator, idle_measured: bool) -> dict:
    """Attach the optional fields in place and return the dict."""
    if idle is not None and idle_measured and "tsi" in raw:
        try:
            flow_dict["idle"] = idle.label(float(raw["tsi"]))
        except (TypeError, ValueError):
            pass
    if "up" in raw or "down" in raw:
        flow_dict["traffic"] = {
            "uploadBytes": max(0, int(raw.get("up") or 0)),
            "downloadBytes": max(0, int(raw.get("down") or 0)),
            "protocol": str(raw.get("proto") or "")[:16],
            "durationMs": max(0, int(raw.get("dur_ms") or 0)),
        }
    if raw.get("pid") is not None:
        flow_dict["process"] = {"pid": int(raw["pid"]), "name": flow_dict.get("app", "")}
    findings = getattr(enriched, "findings", None) or []
    hits = flow_dict.get("pii") or []
    # flow.pii is built from enriched.findings in order (pipeline.process).
    for hit, f in zip(hits, findings):
        value = getattr(f, "value", "")
        if value:
            hit["correlation"] = {"scheme": "hmac-sha256", "pseudonymized": True,
                                  "fingerprint": corr.fingerprint(hit.get("type", ""), str(value)),
                                  "confidence": round(float(hit.get("confidence", 0) or 0), 3)}
    return flow_dict
