"""Browser-extension bridge: the extension produces, the agent consumes.

The extension sees things the proxy cannot — requests before TLS, canvas fingerprinting,
pre-submit form harvesting, DOM storage — and the proxy sees things the extension cannot:
native apps, non-browser traffic, and payload bodies. This joins the two views.

PRODUCER-ONLY, and that is the security design, not an accident. An extension connection
is never added to Hub.clients, so it receives nothing but an ack: no flow feed, no PII, no
score, no history. That is what makes a permissive origin check acceptable. A Chrome
extension's origin is chrome-extension://<id>, the id changes on every unpacked reload, and
there is no way to pin it without making the user copy a token around. Since the channel
carries no data outward, the worst a hostile extension on the same machine can do is inject
findings into the user's own dashboard — bad, but not an exfiltration path. If this ever
starts streaming data back, it needs a pairing token first.

Everything arriving here is untrusted input from a browser extension and is validated
field by field, clamped and length-capped before it reaches the pipeline.
"""
from __future__ import annotations

import json
import re
import time
from typing import Awaitable, Callable

from .schema import PII_TYPES

MAX_MESSAGE = 64 * 1024          # a detection is small; anything larger is a mistake or an attack
MAX_PII_HITS = 16
MAX_STR = 255
MAX_PATH = 2048
HOSTNAME = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9.-]{0,253}[a-zA-Z0-9])?$")
CATEGORIES = ("advertising", "analytics", "social", "fingerprinting", "cdn", "tracking",
              "essential", "unknown")
KINDS = ("unknown_tracker", "fingerprinting", "harvest", "supercookie", "id_sync",
          "third_party_volume", "hashed_pii")


def _s(v, cap: int = MAX_STR) -> str:
    return v[:cap] if isinstance(v, str) else ""


def _f(v, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return lo


def _i(v, lo: int = 0, hi: int = 2**31) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return lo


def _host(v) -> str:
    """A hostname, or "" if it is not one.

    Deliberately rejects rather than truncates: a truncated hostname is a different host,
    so accepting one would attribute a finding to the wrong domain.
    """
    if not isinstance(v, str) or len(v) > 253:
        return ""
    h = v.strip().lower().rstrip(".")
    return h if h and HOSTNAME.match(h) else ""


def clean_pii(raw) -> list[dict]:
    """Keep only well-formed, already-redacted hits of a known type."""
    out = []
    if not isinstance(raw, list):
        return out
    for hit in raw[:MAX_PII_HITS]:
        if not isinstance(hit, dict):
            continue
        t = _s(hit.get("type"), 32)
        if t not in PII_TYPES:
            continue
        out.append({"type": t, "redacted": _s(hit.get("redacted"), 128),
                    "confidence": _f(hit.get("confidence"))})
    return out


def clean_detection(raw) -> dict | None:
    """Normalise one browser detection, or None if it is not usable.

    A detection must name a host; without one there is nothing to attribute it to and
    nothing the user could act on.
    """
    if not isinstance(raw, dict):
        return None
    host = _host(raw.get("host") or raw.get("domain"))
    if not host:
        return None
    kind = _s(raw.get("kind"), 32) or "unknown_tracker"
    category = _s(raw.get("category"), 32).lower()
    return {
        "source": "extension",
        "kind": kind if kind in KINDS else "unknown_tracker",
        "host": host,
        "domain": _host(raw.get("domain")) or host,
        "site": _host(raw.get("site") or raw.get("app") or raw.get("initiator")),
        "app": _s(raw.get("app") or raw.get("site"), 128) or "browser",
        "method": _s(raw.get("method"), 16).upper(),
        "path": _s(raw.get("path"), MAX_PATH),
        "company": _s(raw.get("company"), 128),
        "category": category if category in CATEGORIES else "unknown",
        "confidence": _f(raw.get("confidence")),
        "thirdParty": bool(raw.get("thirdParty", True)),
        "bytes": _i(raw.get("bytes"), 0, 2**31),
        "severity": _i(raw.get("severity"), 0, 100),
        "pii": clean_pii(raw.get("pii")),
        "ts": int(time.time() * 1000),
    }


def clean_site_score(raw) -> dict | None:
    """Normalise a site safety score from the popup (lib/scoring.ts)."""
    if not isinstance(raw, dict):
        return None
    grade = _s(raw.get("grade"), 1).upper()
    bd = raw.get("breakdown") if isinstance(raw.get("breakdown"), dict) else {}
    site = _host(raw.get("site")) or _host(raw.get("url"))
    if not site and isinstance(raw.get("url"), str):
        # Accept a full URL but keep only its host: a full URL is browsing history.
        m = re.match(r"^[a-z]+://([^/?#]+)", raw["url"].strip().lower())
        site = _host(m.group(1).split(":")[0]) if m else ""
    if not site:
        return None
    return {
        "source": "extension",
        "site": site,
        "score": _i(raw.get("score"), 0, 100),
        "grade": grade if grade in ("A", "B", "C", "D", "F") else "F",
        "breakdown": {
            "trackerCount": _i(bd.get("trackerCount")),
            "unknownTrackerCount": _i(bd.get("unknownTrackerCount")),
            "thirdPartyCount": _i(bd.get("thirdPartyCount")),
            "cookieCount": _i(bd.get("cookieCount")),
            "fingerprintingDetected": bool(bd.get("fingerprintingDetected")),
        },
        "ts": int(time.time() * 1000),
    }


class ExtensionBridge:
    """Handles one extension connection for its lifetime.

    `on_detection` and `on_site_score` are called with validated dicts. `status_fn` supplies
    the agent version and engine state for the handshake ack.
    """

    def __init__(self, status_fn: Callable[[], dict],
                 on_detection: Callable[[dict], Awaitable[None]],
                 on_site_score: Callable[[dict], Awaitable[None]]):
        self.status_fn = status_fn
        self.on_detection = on_detection
        self.on_site_score = on_site_score
        self.clients = 0
        self.detections = 0
        self.scores = 0
        self.version = ""           # extension version from the last handshake

    # ------------------------------------------------------------------ handshake
    def ack(self) -> str:
        st = self.status_fn()
        return json.dumps({
            "type": "producer_ack",
            "agent_version": st.get("version", ""),
            "engines": st.get("engines", {}),
            "mode": st.get("mode", "idle"),
        }, separators=(",", ":"))

    # ------------------------------------------------------------------ connection
    async def handle(self, ws) -> None:
        from websockets.exceptions import ConnectionClosed

        self.clients += 1
        try:
            async for raw in ws:
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8", "replace")
                if len(raw) > MAX_MESSAGE:
                    await self._err(ws, "too_large", "message exceeds 64 KiB")
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    await self._err(ws, "bad_json", "message is not JSON")
                    continue
                if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
                    await self._err(ws, "bad_request", "expected an object with a string 'type'")
                    continue
                await self._dispatch(ws, msg)
        except ConnectionClosed:
            pass
        finally:
            self.clients = max(0, self.clients - 1)

    async def _dispatch(self, ws, msg: dict) -> None:
        t = msg["type"]
        if t == "producer_hello":
            self.version = _s(msg.get("extension_version"), 32)
            await ws.send(self.ack())
            return
        if t == "browser_detection":
            d = clean_detection(msg.get("data"))
            if d is None:
                await self._err(ws, "bad_detection", "detection needs a valid host")
                return
            self.detections += 1
            await self.on_detection(d)
            return
        if t == "site_score":
            s = clean_site_score(msg.get("data"))
            if s is None:
                await self._err(ws, "bad_site_score", "site score needs a valid site")
                return
            self.scores += 1
            await self.on_site_score(s)
            return
        if t == "ping":
            await ws.send(json.dumps({"type": "pong"}))
            return
        await self._err(ws, "unsupported", f"producer command '{t[:32]}' is not supported")

    @staticmethod
    async def _err(ws, code: str, message: str) -> None:
        try:
            await ws.send(json.dumps({"type": "error", "code": code, "message": message}))
        except Exception:
            pass
