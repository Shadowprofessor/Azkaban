"""Hashed-PII matching and cross-app identity correlation.

At startup the operator's own identifiers are hashed (MD5/SHA1/SHA256 over common
normalisations) into a local lookup table. Outgoing hex digests are matched
against it: "this request contains the SHA256 of your email".
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from .pii import Finding, redact_email, redact_id, redact_tail

HEXDIGEST = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{64}|[0-9a-fA-F]{40}|[0-9a-fA-F]{32})(?![0-9a-fA-F])")
ALGOS = ("md5", "sha1", "sha256")


def _email_variants(e: str) -> set[str]:
    e = e.strip()
    v = {e, e.lower()}
    local, _, dom = e.lower().partition("@")
    if dom in ("gmail.com", "googlemail.com"):
        v.add(local.split("+")[0].replace(".", "") + "@" + dom)
    return v


def _phone_variants(p: str) -> set[str]:
    digits = re.sub(r"\D", "", p)
    v = {p.strip(), digits, "+" + digits}
    if len(digits) > 10:
        v |= {digits[-10:], "0" + digits[-10:]}
    return v


def _adid_variants(a: str) -> set[str]:
    a = a.strip()
    return {a, a.lower(), a.upper(), a.replace("-", "").lower()}


def _redact(kind: str, value: str) -> str:
    if kind == "email" and "@" in value:
        local, _, dom = value.partition("@")
        return redact_email(local, dom)
    if kind == "phone":
        return "+" + redact_tail(value, 3)
    if kind == "adid":
        return redact_id(value)
    return "<token>"


class IdentityTable:
    def __init__(self):
        self.table: dict[str, tuple[str, str, str]] = {}   # digest -> (kind, canonical value, algo)
        self.known: dict[str, set[str]] = defaultdict(set)

    def add(self, kind: str, value: str) -> None:
        if not value:
            return
        variants = {"email": _email_variants, "phone": _phone_variants, "adid": _adid_variants}.get(
            kind, lambda x: {x})(value)
        self.known[kind].add(value)
        for v in variants:
            for algo in ALGOS:
                self.table[hashlib.new(algo, v.encode()).hexdigest()] = (kind, value, algo)

    def add_many(self, emails=(), phones=(), adids=()) -> None:
        for e in emails:
            self.add("email", e)
        for p in phones:
            self.add("phone", p)
        for a in adids:
            self.add("adid", a)

    def __len__(self) -> int:
        return len(self.table)

    def match(self, key: str, value: str, via: str = "") -> list[Finding]:
        out = []
        if not self.table:
            return out
        for m in HEXDIGEST.finditer(value[:20000]):
            hit = self.table.get(m.group(1).lower())
            if hit:
                kind, canonical, algo = hit
                tag = f"{via}>{algo}" if via else algo
                out.append(Finding(kind, canonical, f"{algo}({_redact(kind, canonical)})", 0.99, key, via=tag))
        return out


class Correlator:
    """Indexes advertising IDs: which apps sent the same ID to which company."""

    def __init__(self):
        self.by_adid: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        self.apps_by_adid: dict[str, set[str]] = defaultdict(set)

    def observe(self, adid: str, app: str, company: str) -> tuple[int, int]:
        """Returns (apps sending this ID to this company, total apps sending this ID)."""
        company = company or "unknown"
        self.by_adid[adid][company].add(app)
        self.apps_by_adid[adid].add(app)
        return len(self.by_adid[adid][company]), len(self.apps_by_adid[adid])

    def links(self) -> list[dict]:
        out = []
        for adid, comps in self.by_adid.items():
            for company, apps in comps.items():
                if len(apps) >= 2:
                    out.append({"adid": redact_id(adid), "company": company, "apps": sorted(apps)})
        return out
