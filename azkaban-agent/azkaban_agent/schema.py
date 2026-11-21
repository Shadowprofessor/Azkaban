"""Python mirror of lib/schema.ts. Field names MUST match the TS contract exactly."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal, Optional

PiiType = Literal["email", "phone", "imei", "adid", "gps", "contact", "clipboard"]
PII_TYPES: tuple[str, ...] = ("email", "phone", "imei", "adid", "gps", "contact", "clipboard")
VerdictStatus = Literal["compliant", "questionable", "violation"]


@dataclass
class PiiHit:
    type: str
    redacted: str
    confidence: float


@dataclass
class Tracker:
    name: str
    category: str


@dataclass
class Tcf:
    vendors: list[int]
    purposes: list[int]


@dataclass
class Flow:
    id: str
    ts: int
    app: str
    host: str
    method: str
    path: str
    ip: str
    country: str = "ZZ"
    company: str = ""
    tracker: Optional[Tracker] = None
    decrypted: bool = True
    pii: list[PiiHit] = field(default_factory=list)
    severity: int = 0
    tcf: Optional[Tcf] = None
    bytes: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Citation:
    source: str
    section: str
    url: str


@dataclass
class Verdict:
    flowId: str
    status: str
    reasoning: str
    citations: list[Citation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScoreCategory:
    name: str
    value: float


@dataclass
class Score:
    total: float
    categories: list[ScoreCategory] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


FLOW_FIELDS = (
    "id", "ts", "app", "host", "method", "path", "ip", "country", "company",
    "tracker", "decrypted", "pii", "severity", "tcf", "bytes",
)


def flow_from_dict(d: dict) -> Flow:
    tr = d.get("tracker")
    tcf = d.get("tcf")
    return Flow(
        id=d["id"], ts=int(d["ts"]), app=d.get("app", ""), host=d.get("host", ""),
        method=d.get("method", ""), path=d.get("path", ""), ip=d.get("ip", ""),
        country=d.get("country", "ZZ"), company=d.get("company", ""),
        tracker=Tracker(**tr) if tr else None,
        decrypted=bool(d.get("decrypted", True)),
        pii=[PiiHit(**p) for p in d.get("pii", [])],
        severity=int(d.get("severity", 0)),
        tcf=Tcf(**tcf) if tcf else None,
        bytes=int(d.get("bytes", 0)),
    )
