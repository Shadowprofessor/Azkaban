"""Blocklist ("Patronus") generation and the apply-and-recheck loop.

Apply = enforce in-proxy (no admin needed): CONNECT and requests to blocked hosts
are refused. The exported formats let the user enforce it system- or network-wide.
Recheck = leak count after applying vs the stored baseline.
"""
from __future__ import annotations

import time
from collections import defaultdict

SEVERITY_FLAG = 50


def leak(flow) -> bool:
    """A leak = personal data sent to a third-party tracker."""
    return flow.tracker is not None and bool(flow.pii)


def host_blocked(host: str, blocked: set[str]) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(host == b or host.endswith("." + b) for b in blocked)


class Blocklist:
    def __init__(self):
        self.flagged: dict[str, dict] = {}            # host -> {company, tracker, leaks, maxSeverity}
        self.ips: dict[str, set[str]] = defaultdict(set)
        self.hosts: list[str] = []
        self.applied = False
        self.blocked: set[str] = set()
        self.baseline: int | None = None
        self.baseline_score: float | None = None
        self.leaks = 0                                # leaks in the current window
        self.prevented = 0                            # requests refused since apply
        self.applied_at = 0.0

    # ------------------------------------------------------------ observe
    def observe(self, flow) -> None:
        if leak(flow):
            self.leaks += 1
        if flow.tracker is not None and (flow.pii or flow.severity >= SEVERITY_FLAG):
            h = flow.host.lower()
            d = self.flagged.setdefault(h, {"company": flow.company, "tracker": flow.tracker.name,
                                            "leaks": 0, "maxSeverity": 0})
            d["leaks"] += int(leak(flow))
            d["maxSeverity"] = max(d["maxSeverity"], flow.severity)
            if flow.ip:
                self.ips[h].add(flow.ip)

    # ------------------------------------------------------------ generate
    def generate(self) -> list[str]:
        self.hosts = sorted(self.flagged, key=lambda h: (-self.flagged[h]["leaks"], -self.flagged[h]["maxSeverity"], h))
        return self.hosts

    def formats(self) -> dict[str, str]:
        hs = self.hosts
        header = "# Azkaban Patronus blocklist — generated from your own captured traffic\n"
        hosts = header + "".join(f"0.0.0.0 {h}\n" for h in hs)
        pihole = header + "".join(f"{h}\n" for h in hs)
        nextdns = "".join(f"{h}\n" for h in hs)          # paste into NextDNS > Denylist
        ips = sorted({ip for h in hs for ip in self.ips.get(h, ()) if ":" not in ip})
        pf = (header + "table <azkaban_patronus> { " + ", ".join(ips) + " }\n"
              "block drop out quick to <azkaban_patronus>\n") if ips else header + "# no IPv4 addresses observed\n"
        return {"hosts": hosts, "pihole": pihole, "nextdns": nextdns, "pf": pf}

    # ------------------------------------------------------------ apply / recheck
    def apply(self, current_score: float) -> set[str]:
        if not self.hosts:
            self.generate()
        self.baseline = self.leaks
        self.baseline_score = current_score
        self.leaks = 0
        self.prevented = 0
        self.blocked = set(self.hosts)
        self.applied = True
        self.applied_at = time.time()
        return self.blocked

    def clear(self) -> None:
        self.blocked = set()
        self.applied = False
        self.baseline = None
        self.baseline_score = None

    def recheck(self) -> dict | None:
        if self.baseline is None:
            return None
        # delta = current - baseline: negative means fewer leaks after the fix.
        return {"baseline": self.baseline, "current": self.leaks, "delta": self.leaks - self.baseline}

    def message(self) -> dict:
        return {"type": "blocklist", "hosts": self.hosts, "formats": self.formats(),
                "applied": self.applied, "recheck": self.recheck()}
