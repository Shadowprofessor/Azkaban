"""Cross-flow findings emitted as `insight` messages (lib/live/protocol.ts, additive v1.1)."""
from __future__ import annotations

import time
from collections import Counter, defaultdict

from .idle import IDLE_BEACON_S


def insight(key: str, kind: str, level: str, title: str, detail: str, data: dict | None = None) -> dict:
    return {"type": "insight", "key": key, "kind": kind, "level": level, "title": title,
            "detail": detail, "data": data or {}}


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class InsightEngine:
    def __init__(self):
        self.idle_beacons = 0
        self.idle_by_app: Counter = Counter()
        self.idle_by_company: Counter = Counter()
        self.bytes_company: Counter = Counter()
        self.bytes_tracker: Counter = Counter()
        self.flows_company: Counter = Counter()
        self.hashed_seen: set[tuple[str, str]] = set()
        self.cross_app_seen: dict[str, int] = {}
        self._dirty = {"idle": False, "bw": False}
        self._last_periodic = 0.0

    def on_flow(self, e) -> list[dict]:
        f = e.flow
        out = []
        dest = f.company or f.host
        if f.tracker or f.company:
            self.bytes_company[dest] += f.bytes
            self.flows_company[dest] += 1
            self._dirty["bw"] = True
        if f.tracker:
            self.bytes_tracker[f.tracker.name] += f.bytes
        if f.tracker and e.tsi >= IDLE_BEACON_S:
            self.idle_beacons += 1
            self.idle_by_app[f.app] += 1
            self.idle_by_company[dest] += 1
            self._dirty["idle"] = True

        for fi in e.findings:
            fam_hash = any(a in fi.via for a in ("md5", "sha1", "sha256"))
            if fam_hash and (fi.type, dest) not in self.hashed_seen:
                self.hashed_seen.add((fi.type, dest))
                algo = fi.via.split(">")[-1]
                out.append(insight(
                    f"hashed:{fi.type}:{dest}", "hashed_pii", "critical",
                    f"{f.app} sent the {algo.upper()} of your {fi.type} to {dest}",
                    f"Hashing is not anonymisation: {dest} can match this digest against its own "
                    f"records of your {fi.type}. Seen in field '{fi.key}' ({fi.via}).",
                    {"app": f.app, "company": dest, "pii": fi.type, "algo": algo, "flowId": f.id}))
            if fi.type == "adid" and e.adid_reuse >= 2 and self.cross_app_seen.get(dest, 0) < e.adid_reuse:
                self.cross_app_seen[dest] = e.adid_reuse
                out.append(insight(
                    f"cross_app:{dest}", "cross_app", "warn",
                    f"{dest} sees the same advertising ID from {e.adid_reuse} apps",
                    "One ID across apps lets the company join your activity in every one of them into a single profile.",
                    {"company": dest, "apps": e.adid_reuse}))
        return out

    def periodic(self, bypass: dict[str, list[dict]] | None = None) -> list[dict]:
        out = []
        if self._dirty["idle"] and self.idle_beacons:
            self._dirty["idle"] = False
            out.append(insight(
                "idle_beacons", "idle_beacons", "warn",
                f"Your device phoned home {self.idle_beacons} time{'s' if self.idle_beacons != 1 else ''} while you did nothing",
                f"Tracker requests sent after {int(IDLE_BEACON_S)}s+ without keyboard or mouse input.",
                {"count": self.idle_beacons, "byApp": dict(self.idle_by_app.most_common(10)),
                 "byCompany": dict(self.idle_by_company.most_common(10))}))
        if self._dirty["bw"]:
            self._dirty["bw"] = False
            top = self.bytes_company.most_common(10)
            total = sum(self.bytes_company.values())
            out.append(insight(
                "bandwidth", "bandwidth", "info",
                f"{_human_bytes(total)} sent to/received from tracking companies",
                ", ".join(f"{c}: {_human_bytes(b)}" for c, b in top[:3]),
                {"byCompany": dict(top), "byTracker": dict(self.bytes_tracker.most_common(10)),
                 "flowsByCompany": dict(self.flows_company.most_common(10)), "totalBytes": total}))
        if bypass:
            n = sum(len(v) for v in bypass.values())
            out.append(insight(
                "dns_bypass", "dns_bypass", "info",
                f"{len(bypass)} apps talk to the internet without going through The Trace",
                f"{n} direct connections (not proxied, so not inspected).",
                {"byApp": {a: v[:20] for a, v in sorted(bypass.items(), key=lambda kv: -len(kv[1]))[:15]}}))
        return out
