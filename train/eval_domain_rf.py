"""Evaluates a lexical unknown-tracker RandomForest (registrable-domain features).

Result on the bundled lists (2026-11-21): 5-fold ROC-AUC ~0.60 (mean). Too weak to label
flows, so the agent detects unlisted trackers from behaviour instead (azkaban_agent/mlextra.py).
Kept so the decision is reproducible.

    python train/eval_domain_rf.py
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score

DATA = Path(__file__).resolve().parents[1] / "azkaban-agent" / "azkaban_agent" / "data" / "trackers.json"
KEYWORDS = ("analytic", "track", "pixel", "ads", "metric", "telemetry", "log", "event", "collect", "beacon",
            "stat", "measure", "tag", "sdk", "attribution", "click", "insight", "crash", "push", "rtb", "bid")
SECOND = {"co", "com", "net", "org", "gov", "ac", "edu"}


def reg(h):
    l = h.lower().split(".")
    return ".".join(l[-3:]) if len(l) >= 3 and len(l[-1]) == 2 and l[-2] in SECOND else ".".join(l[-2:])


def ent(s):
    c = Counter(s)
    return -sum(v / len(s) * math.log2(v / len(s)) for v in c.values()) if s else 0.0


def feats(d):
    name, tld = d.split(".")[0], d.split(".")[-1]
    return [len(name), ent(name), sum(c.isdigit() for c in name) / max(1, len(name)), name.count("-"),
            float(len(tld) == 2), *[float(k in name) for k in KEYWORDS]]


def main():
    d = json.loads(DATA.read_text(encoding="utf-8"))
    pos = sorted({reg(x) for x in d["trackers"]})
    neg = sorted({reg(x) for x in d["owners"]} - set(pos))
    X = np.asarray([feats(x) for x in pos + neg])
    y = np.asarray([1] * len(pos) + [0] * len(neg))
    auc = cross_val_score(RandomForestClassifier(n_estimators=150, max_depth=14, class_weight="balanced",
                                                 random_state=7, n_jobs=-1), X, y, cv=5, scoring="roc_auc")
    print(f"positives={len(pos)} negatives={len(neg)} 5-fold ROC-AUC={auc.round(3)} mean={auc.mean():.3f}")


if __name__ == "__main__":
    sys.exit(main())
