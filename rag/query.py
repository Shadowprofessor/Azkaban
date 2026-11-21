"""Statute retrieval for the legal engine.

`retrieve(facts, k)` is the contract azkaban_agent/legal.py looks for at import time
(it falls back to azkaban_agent/rag_stub.py when this package is absent). The input is
STRUCTURED FACTS ONLY — PII *types*, company, jurisdiction, consent flags, app category.
Never a raw or redacted PII value, never a URL or body. See legal.build_facts.

Ranking is deliberately hybrid:

  1. Trigger sections. Some facts implicate a section as a matter of law, not of word
     overlap: any processing engages Section 6 (consent), a transfer abroad engages
     Section 16, a tracker acting for another company engages Section 8 (processor
     duties), a children's app engages Section 9. These are always returned, in a fixed
     order, because a citation the user can check must not depend on term frequency.

  2. BM25 over the remaining sections, with a tag boost. This is what the stub could not
     do: it ranked by tag overlap alone, so two sections sharing a tag were
     indistinguishable and the statute body was never consulted.

The two are concatenated, triggers first, so `k` smaller than the trigger set still
returns every section the facts legally require.
"""
from __future__ import annotations

from .bm25 import BM25Index, tokens
from .corpus import law, law_text

#: Facts that make a section mandatory, in citation order.
TRIGGERS: list[tuple[str, str]] = [
    ("", "Section 6"),              # consent governs every observed flow
    ("cross_border", "Section 16"),
    ("is_tracker", "Section 8"),
    ("child_app", "Section 9"),
]

#: Tag weights by fact. Mirrors the stub's weighting so behaviour stays recognisable,
#: but now rides on top of a real text score instead of replacing it.
BASE_TAGS: dict[str, float] = {
    "consent": 2.0, "personal_data": 1.0, "definition": 0.8, "lawful_purpose": 1.0,
    "notice": 0.8, "purpose_limitation": 1.0, "data_minimisation": 1.0, "penalty": 0.3,
}
TAG_BOOST = 1.6

#: Tags whose section only applies when a fact holds. Without the fact the section is
#: noise, and worse than noise: legal.py tells the model to cite only the law it is
#: given, so handing it Section 9 for an adult app invites a misapplied citation.
#: A negative weight pushes the section below the score>0 cutoff instead of hard-filtering,
#: so it can still surface when the facts genuinely point at it.
GATED: dict[str, str] = {"children": "child_app", "cross_border": "cross_border"}
GATE_PENALTY = -2.5

_index: BM25Index | None = None


def index() -> BM25Index:
    global _index
    if _index is None:
        _index = BM25Index(law(), law_text)
    return _index


def tag_weights(facts: dict) -> dict[str, float]:
    w = dict(BASE_TAGS)
    if not facts.get("consent"):
        w["consent"] += 1.5
    if facts.get("is_tracker"):
        w.update(third_party=1.5, processor=1.2, targeted_advertising=0.6)
    if facts.get("cross_border"):
        w["cross_border"] = 2.5
    if facts.get("pii_unexpected_for_app_category") or (
        facts.get("app_category") in ("utility", "news") and facts.get("pii_types")
    ):
        w["data_minimisation"] += 1.0
    if facts.get("child_app"):
        w["children"] = 3.0
    if facts.get("hashed_identifier") or facts.get("same_adid_across_apps"):
        w["personal_data"] += 0.8      # is a hash still personal data? Section 2(t)
    for tag, fact in GATED.items():
        if not facts.get(fact):
            w[tag] = GATE_PENALTY
    return w


def query_text(facts: dict) -> str:
    """A bag of words describing the flow, built only from structured fields."""
    parts: list[str] = ["personal data consent lawful purpose"]
    parts += list(facts.get("pii_types") or [])
    parts += list(facts.get("pii_unexpected_for_app_category") or [])
    if facts.get("is_tracker"):
        parts.append("third party processor targeted advertising tracking")
    if facts.get("tracker_category"):
        parts.append(str(facts["tracker_category"]))
    if facts.get("cross_border"):
        parts.append("transfer outside india cross border country restriction")
    if not facts.get("consent"):
        parts.append("notice free informed specific unconditional withdraw")
    if facts.get("hashed_identifier"):
        parts.append("identifier pseudonymous definition")
    if facts.get("child_app"):
        parts.append("child children verifiable parental consent")
    if facts.get("while_user_idle"):
        parts.append("purpose limitation necessary specified purpose")
    if facts.get("app_category"):
        parts.append(str(facts["app_category"]))
    return " ".join(parts)


def trigger_sections(facts: dict) -> list[str]:
    return [sec for fact, sec in TRIGGERS if not fact or facts.get(fact)]


def _shape(d: dict, score: float | None = None) -> dict:
    out = {"source": d.get("source", "Digital Personal Data Protection Act, 2023"),
           "section": d["section"], "title": d.get("title", ""),
           "url": d.get("url", ""), "text": d["text"]}
    if score is not None:
        out["score"] = round(score, 4)
    return out


def retrieve(facts: dict | str, k: int = 4) -> list[dict]:
    """Rank DPDP sections for one observed flow. Returns at least the trigger sections."""
    if isinstance(facts, str):          # convenience for interactive use and the CLI
        facts = {"pii_types": [], "free_text": facts}
        q = set(tokens(str(facts["free_text"])))
        must: list[str] = []
    else:
        q = set(tokens(query_text(facts)))
        must = trigger_sections(facts)

    by_section = {d["section"]: d for d in law()}
    weights = tag_weights(facts if isinstance(facts, dict) else {})

    def boost(doc: dict, _q: set[str]) -> float:
        return TAG_BOOST * sum(weights.get(t, 0.0) for t in doc.get("tags", []))

    picked = [_shape(by_section[s]) for s in must if s in by_section]
    seen = {d["section"] for d in picked}
    for score, doc in index().search(q, k=len(law()), where=lambda d: d["section"] not in seen,
                                     boost=boost, tie_key=lambda d: d["section"]):
        picked.append(_shape(doc, score))
    return picked[:max(k, len(must))]


def explain(facts: dict, k: int = 4) -> str:
    """Human-readable trace of why each section was returned. Used by `azkaban rag-check`."""
    must = set(trigger_sections(facts))
    lines = [f"query terms: {' '.join(sorted(set(tokens(query_text(facts)))))}"]
    for d in retrieve(facts, k):
        why = "trigger (required by the facts)" if d["section"] in must else f"bm25+tags {d.get('score', 0)}"
        lines.append(f"  {d['section']:<12} {d.get('title', '')[:52]:<54} {why}")
    return "\n".join(lines)
