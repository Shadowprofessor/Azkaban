"""Raw capture record -> enriched, redacted Flow."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import pii, tcf
from .config import Config
from .decode import expand
from .fields import record_fields
from .geo import Geo
from .honeytoken import Canary, load as load_honeytokens
from .identity import Correlator, IdentityTable
from .schema import Flow
from .score import Fact
from .severity import SeverityModel
from .trackers import TrackerDB

HASH_ALGOS = ("md5", "sha1", "sha256")


@dataclass
class Enriched:
    flow: Flow
    findings: list[pii.Finding] = field(default_factory=list)   # internal only, holds raw values
    raw: dict = field(default_factory=dict)
    hashed_hits: int = 0
    encoded_hits: int = 0
    adid_reuse: int = 0          # apps that sent the same ad ID to this flow's company
    tsi: float = 0.0             # seconds since last user interaction
    features: list = field(default_factory=list)
    honey: list = field(default_factory=list)    # honeytoken hits


def _family(via: str) -> str:
    if any(a in via for a in HASH_ALGOS):
        return "hash"
    return "enc" if via else "plain"


def merge(findings: list[pii.Finding]) -> list[pii.Finding]:
    best: dict[tuple[str, str, str], pii.Finding] = {}
    for f in findings:
        k = (f.type, f.value, _family(f.via))
        if k not in best or f.confidence > best[k].confidence:
            best[k] = f
    # An encoded copy of a value already seen in plaintext adds nothing.
    plain = {(t, v) for (t, v, fam) in best if fam == "plain"}
    return [f for (t, v, fam), f in best.items() if not (fam == "enc" and (t, v) in plain)]


class Pipeline:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.trackers = TrackerDB()
        self.geo = Geo(cfg.geoip_db)
        self.identity = IdentityTable()
        self.identity.add_many(cfg.known_emails, cfg.known_phones, cfg.known_adids)
        self.correlator = Correlator()
        self.severity = SeverityModel()
        self.canary = Canary(load_honeytokens())

    def scan_payload(self, raw: dict) -> tuple[list[pii.Finding], object]:
        pairs = record_fields(raw)
        layers = expand(pairs)
        found: list[pii.Finding] = []
        groups: dict[str, list[tuple[str, str]]] = {}
        for k, v, via in layers:
            groups.setdefault(via, []).append((k, v))
            found += self.identity.match(k, v, via)
        for via, group in groups.items():
            for f in pii.scan(group):
                if via:
                    f.via = via
                    f.redacted = f"{f.redacted} [{via}]"
                    f.confidence = min(f.confidence, 0.9)
                found.append(f)
        self._last_layers = layers
        return merge(found), tcf.find(pairs + [(k, v) for k, v, via in layers if via])

    def process(self, raw: dict) -> Enriched:
        def s(k: str, cap: int = 512) -> str:
            v = raw.get(k)
            return v[:cap] if isinstance(v, str) else ""

        flow = Flow(
            id=s("id", 64) or "unknown", ts=int(raw["ts"]), app=s("app", 128) or "unknown",
            host=s("host", 255), method=s("method", 16), path=s("path", 2048),
            ip=s("ip", 64), decrypted=bool(raw.get("decrypted", True)),
            bytes=max(0, int(raw.get("bytes", 0) or 0)),
        )
        tracker, company = self.trackers.lookup(flow.host) if flow.host else (None, "")
        flow.tracker, flow.company = tracker, company
        flow.country = self.geo.country(flow.ip) if flow.ip else "ZZ"

        e = Enriched(flow=flow, raw=raw, tsi=float(raw.get("tsi", 0.0) or 0.0))
        if flow.decrypted:
            e.findings, flow.tcf = self.scan_payload(raw)
            e.honey = self.canary.scan(self._last_layers)

        for f in e.findings:
            fam = _family(f.via)
            e.hashed_hits += fam == "hash"
            e.encoded_hits += fam == "enc"
            if f.type == "adid":
                same_co, _total = self.correlator.observe(f.value, flow.app, company or flow.host)
                e.adid_reuse = max(e.adid_reuse, same_co)
                if same_co >= 2:
                    f.redacted = f"{f.redacted} · same ID from {same_co} apps → {company or flow.host}"
        flow.pii = [f.hit() for f in e.findings]
        e.features = self.severity.features(e, self.cfg.home_country)
        flow.severity = self.severity.score(e.features)
        if e.honey:
            flow.severity = max(flow.severity, 95)   # proven exfiltration of a planted value
        return e

    def fact(self, e: Enriched) -> Fact:
        f = e.flow
        return Fact(host=f.host, company=f.company, tracker=f.tracker is not None,
                    pii=frozenset(h.type for h in f.pii),
                    cross_border=f.country not in ("ZZ", "", self.cfg.home_country),
                    consent=bool(f.tcf and f.tcf.purposes), hashed=e.hashed_hits)
