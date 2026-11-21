"""Exposure Score (0-1000) with per-category subscores and remediation ranked by
marginal score reduction (how much the total drops if a destination is blocked)."""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from .features import SENSITIVITY
from .schema import Score, ScoreCategory

CAPS = {
    "tracker_breadth": 250,
    "pii_sensitivity": 250,
    "consent_violations": 200,
    "cross_border": 150,
    "hashed_pii": 150,
}


@dataclass(frozen=True)
class Fact:
    """Compact, PII-free summary of one flow."""
    host: str
    company: str
    tracker: bool
    pii: frozenset           # types only
    cross_border: bool
    consent: bool
    hashed: int


def _sat(x: float, k: float) -> float:
    return 1 - math.exp(-x / k)


def compute(facts) -> dict[str, float]:
    companies = set()
    sens: dict[tuple[str, str], float] = {}
    no_consent = set()
    xb_pii = set()
    hashed = set()
    for f in facts:
        dest = f.company or f.host
        if f.tracker:
            companies.add(dest)
        for t in f.pii:
            sens[(t, dest)] = SENSITIVITY.get(t, 0.5)
            if f.tracker and not f.consent:
                no_consent.add((t, dest))
            if f.cross_border:
                xb_pii.add((t, dest))
        if f.hashed:
            hashed.add(dest)
    return {
        "tracker_breadth": CAPS["tracker_breadth"] * _sat(len(companies), 6),
        "pii_sensitivity": CAPS["pii_sensitivity"] * _sat(sum(sens.values()), 4),
        "consent_violations": CAPS["consent_violations"] * _sat(len(no_consent), 5),
        "cross_border": CAPS["cross_border"] * _sat(len(xb_pii), 4),
        "hashed_pii": CAPS["hashed_pii"] * _sat(len(hashed), 1.5),
    }


class ExposureScore:
    def __init__(self, maxlen: int = 5000):
        self.facts: deque[Fact] = deque(maxlen=maxlen)
        self.dirty = False

    def add(self, fact: Fact) -> None:
        self.facts.append(fact)
        self.dirty = True

    def reset(self) -> None:
        self.facts.clear()
        self.dirty = True

    def score(self) -> Score:
        cats = compute(self.facts)
        return Score(total=round(sum(cats.values())),
                     categories=[ScoreCategory(k, round(v, 1)) for k, v in cats.items()])

    def remediation(self, top: int = 10) -> list[dict]:
        facts = list(self.facts)
        base = sum(compute(facts).values())
        out = []
        for company in {f.company for f in facts if f.company and (f.tracker or f.pii)}:
            rest = [f for f in facts if f.company != company]
            out.append({"target": company, "kind": "company", "reduction": round(base - sum(compute(rest).values()))})
        for host in {f.host for f in facts if not f.company and (f.tracker or f.pii)}:
            rest = [f for f in facts if f.host != host]
            out.append({"target": host, "kind": "host", "reduction": round(base - sum(compute(rest).values()))})
        out = [r for r in out if r["reduction"] > 0]
        out.sort(key=lambda r: -r["reduction"])
        return out[:top]

    def message(self) -> dict:
        self.dirty = False
        return {"type": "score", "score": self.score().to_dict(), "remediation": self.remediation()}
