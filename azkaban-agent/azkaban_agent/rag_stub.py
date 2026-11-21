"""Offline stand-in for the RAG teammate's `rag.query.retrieve`.

Same call shape the agent uses for the real one:
    retrieve(facts: dict, k: int = 4) -> list[{"source", "section", "url", "text"}]
`facts` is STRUCTURED ONLY (never raw PII). Ranks verbatim DPDP sections by tag overlap.
"""
from __future__ import annotations

import json

from .config import DATA_DIR

_SECTIONS = None


def _sections() -> list[dict]:
    global _SECTIONS
    if _SECTIONS is None:
        _SECTIONS = json.loads((DATA_DIR / "dpdp_sections.json").read_text(encoding="utf-8"))
    return _SECTIONS


def _wanted_tags(facts: dict) -> dict[str, float]:
    w = {"consent": 2.0, "personal_data": 1.0, "definition": 0.8, "lawful_purpose": 1.0, "notice": 0.8,
         "purpose_limitation": 1.0, "data_minimisation": 1.0}
    if not facts.get("consent"):
        w["consent"] += 1.5
    if facts.get("is_tracker"):
        w["third_party"] = 1.5
        w["processor"] = 1.2
        w["targeted_advertising"] = 0.6
    if facts.get("cross_border"):
        w["cross_border"] = 2.5
    if facts.get("app_category") in ("utility", "news") and facts.get("pii_types"):
        w["data_minimisation"] += 1.0
    if facts.get("child_app"):
        w["children"] = 3.0
    w["penalty"] = 0.3
    return w


def retrieve(facts: dict, k: int = 4) -> list[dict]:
    secs = {s["section"]: s for s in _sections()}
    # Sections a fact directly triggers come first, then the best tag matches.
    must = ["Section 6"]
    if facts.get("cross_border"):
        must.append("Section 16")
    if facts.get("is_tracker"):
        must.append("Section 8")
    if facts.get("child_app"):
        must.append("Section 9")
    w = _wanted_tags(facts)
    rest = sorted((s for s in secs.values() if s["section"] not in must),
                  key=lambda s: -sum(w.get(t, 0) for t in s.get("tags", [])))
    picked = [secs[m] for m in must if m in secs] + rest
    return [{"source": s["source"], "section": s["section"], "url": s["url"], "text": s["text"]}
            for s in picked[:max(k, len(must))]]
