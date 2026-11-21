"""Raw capture record -> enriched, redacted Flow."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import pii, tcf
from .config import Config
from .fields import record_fields
from .geo import Geo
from .schema import Flow
from .trackers import TrackerDB


@dataclass
class Enriched:
    flow: Flow
    findings: list[pii.Finding] = field(default_factory=list)   # internal only, holds raw values
    raw: dict = field(default_factory=dict)


class Pipeline:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.trackers = TrackerDB()
        self.geo = Geo(cfg.geoip_db)

    def process(self, raw: dict) -> Enriched:
        flow = Flow(
            id=raw["id"], ts=int(raw["ts"]), app=raw.get("app") or "unknown",
            host=raw.get("host", ""), method=raw.get("method", ""), path=raw.get("path", ""),
            ip=raw.get("ip", ""), decrypted=bool(raw.get("decrypted", True)),
            bytes=int(raw.get("bytes", 0)),
        )
        tracker, company = self.trackers.lookup(flow.host) if flow.host else (None, "")
        flow.tracker, flow.company = tracker, company
        flow.country = raw.get("country") or self.geo.country(flow.ip) if flow.ip else (raw.get("country") or "ZZ")

        findings: list[pii.Finding] = []
        if flow.decrypted:
            pairs = record_fields(raw)
            findings = pii.scan(pairs)
            flow.tcf = tcf.find(pairs)
        flow.pii = [f.hit() for f in findings]
        return Enriched(flow=flow, findings=findings, raw=raw)
