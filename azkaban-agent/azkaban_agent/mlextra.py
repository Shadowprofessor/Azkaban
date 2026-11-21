"""Stretch ML: catch trackers no list knows about, from BEHAVIOUR.

Why not a lexical domain classifier: a RandomForest on registrable-domain features
(entropy, TLD, keywords) trained on the bundled Exodus/DDG lists reached only
ROC-AUC ~0.64 in 5-fold CV (see train/eval_domain_rf.py) — not good enough to
label anything. Behaviour is the real signal:

BeaconAnomaly  — IsolationForest (unsupervised) over per-(app, host) series:
                 count, mean gap, gap regularity (CV), mean bytes, idle fraction, PII rate.
suspected()    — an UNLISTED host that receives a device/user identifier (ad ID,
                 hashed identifier, IMEI) in regular, repeated requests.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict

import numpy as np

ID_TYPES = {"adid", "imei"}


class BeaconAnomaly:
    MIN_SERIES = 8
    MIN_POINTS = 3

    def __init__(self):
        # (app, host) -> [(ts_s, bytes, tsi, has_pii, has_identifier)]
        self.series: dict[tuple[str, str], list[tuple]] = defaultdict(list)
        self.listed: dict[tuple[str, str], bool] = {}
        self.flagged: set[tuple[str, str]] = set()
        self.suspects: set[str] = set()

    def observe(self, app: str, host: str, ts_ms: int, nbytes: int, tsi: float, pii_types: set[str],
                hashed: int, listed: bool) -> None:
        k = (app, host)
        s = self.series[k]
        s.append((ts_ms / 1000, nbytes, tsi, bool(pii_types), bool(pii_types & ID_TYPES) or hashed > 0))
        self.listed[k] = listed
        if len(s) > 200:
            del s[:100]

    @staticmethod
    def _vec(pts) -> list[float]:
        ts = [p[0] for p in pts]
        gaps = [b - a for a, b in zip(ts, ts[1:])] or [0.0]
        mean_gap = statistics.fmean(gaps)
        cv = (statistics.pstdev(gaps) / mean_gap) if mean_gap > 0 else 0.0
        return [math.log1p(len(pts)), math.log1p(mean_gap), min(cv, 5.0),
                math.log1p(statistics.fmean(p[1] for p in pts)),
                sum(p[2] >= 60 for p in pts) / len(pts), sum(p[3] for p in pts) / len(pts)]

    def detect(self) -> list[dict]:
        keys = [k for k, v in self.series.items() if len(v) >= self.MIN_POINTS]
        if len(keys) < self.MIN_SERIES:
            return []
        from sklearn.ensemble import IsolationForest
        X = np.asarray([self._vec(self.series[k]) for k in keys])
        iso = IsolationForest(n_estimators=100, contamination=0.1, random_state=7).fit(X)
        out = []
        for k, sc, v in zip(keys, iso.decision_function(X), X):
            if sc < 0 and k not in self.flagged:
                self.flagged.add(k)
                out.append({"app": k[0], "host": k[1], "anomaly": round(float(-sc), 3),
                            "requests": len(self.series[k]), "meanGapS": round(math.expm1(v[1]), 1),
                            "regularityCV": round(float(v[2]), 2), "idleFraction": round(float(v[4]), 2)})
        return out

    def suspected(self) -> list[dict]:
        """Unlisted hosts receiving identifiers in a repeated pattern."""
        out = []
        for (app, host), pts in self.series.items():
            if self.listed.get((app, host)) or host in self.suspects or len(pts) < self.MIN_POINTS:
                continue
            id_rate = sum(p[4] for p in pts) / len(pts)
            if id_rate >= 0.5:
                v = self._vec(pts)
                self.suspects.add(host)
                out.append({"host": host, "app": app, "requests": len(pts), "identifierRate": round(id_rate, 2),
                            "meanGapS": round(math.expm1(v[1]), 1), "regularityCV": round(v[2], 2)})
        return out
