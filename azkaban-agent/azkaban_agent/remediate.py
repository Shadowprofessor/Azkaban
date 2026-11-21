"""Attach retrieved remediation steps to insight messages.

An insight tells the user what happened. Without a next step it is a complaint, not a
tool. This enriches insights with steps retrieved from the public guide corpus in `rag/`,
added under `data.remediation` — additive, so a dashboard that ignores it is unaffected
(lib/live/protocol.ts types `data` as an open record).

The retrieval layer lives at the repo root and is optional: if `rag/` is missing or fails
to import, insights pass through untouched rather than breaking the agent.
"""
from __future__ import annotations

import sys

from .config import REPO_ROOT

#: Kinds where a per-destination remediation makes sense. 'recheck' and 'bandwidth' report
#: on the tool's own effect and on volume, so there is nothing to go and change.
REMEDIABLE = frozenset({
    "unknown_tracker", "hashed_pii", "cross_app", "idle_beacons", "honeytoken",
    "beacon_anomaly",
})

#: A honeytoken insight names the field the canary leaked from but carries no PII type.
#: The field name is the best available evidence of what kind of data was taken, and it
#: decides which control the user should go and change.
FIELD_PII: tuple[tuple[str, str], ...] = (
    ("contact", "contact"), ("addressbook", "contact"), ("phonebook", "contact"),
    ("clipboard", "clipboard"), ("location", "gps"), ("latlng", "gps"), ("coord", "gps"),
    ("gps", "gps"), ("email", "email"), ("mail", "email"), ("phone", "phone"),
    ("imei", "imei"), ("adid", "adid"), ("advertis", "adid"),
)

_remediate = None
_tried = False


def _loader():
    """Lazily import rag.guides.remediate, once, tolerating its absence."""
    global _remediate, _tried
    if not _tried:
        _tried = True
        root = str(REPO_ROOT)
        if root not in sys.path:
            sys.path.insert(0, root)
        try:
            from rag.guides import remediate as fn   # type: ignore
            _remediate = fn
        except Exception:
            _remediate = None
    return _remediate


def available() -> bool:
    return _loader() is not None


def _subject(data: dict) -> tuple[str, str, list[str]]:
    company = str(data.get("company") or "")
    host = str(data.get("host") or data.get("domain") or "")
    pii = data.get("piiTypes") or data.get("pii_types") or []
    if isinstance(pii, str):
        pii = [pii]
    if not pii and data.get("type"):            # hashed_pii carries the single type
        pii = [str(data["type"])]
    if not pii and data.get("field"):           # honeytoken: infer from the leaked field
        field = str(data["field"]).lower()
        pii = [t for needle, t in FIELD_PII if needle in field][:1]
    return company, host, [str(p) for p in pii][:4]


def enrich(msg: dict) -> dict:
    """Return `msg` with data.remediation filled in where it applies.

    Mutates nothing the caller still needs: the message is copied shallowly and its data
    dict replaced, so a cached insight is not retroactively modified.
    """
    if msg.get("type") != "insight" or msg.get("kind") not in REMEDIABLE:
        return msg
    fn = _loader()
    if fn is None:
        return msg
    data = dict(msg.get("data") or {})
    if "remediation" in data:
        return msg
    company, host, pii = _subject(data)
    if not (company or host):
        return msg
    try:
        data["remediation"] = fn(company=company, host=host, kind=str(msg.get("kind", "")),
                                 pii_types=pii)
    except Exception:
        return msg                              # retrieval must never break an insight
    return {**msg, "data": data}
