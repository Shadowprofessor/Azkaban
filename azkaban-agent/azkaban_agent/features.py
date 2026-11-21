"""Severity model features. Shared by training (train/train_xgb.py) and in-agent inference."""
from __future__ import annotations

import math
import re

FEATURES = [
    "pii_type_count",
    "pii_sensitivity_max",
    "is_tracker",
    "is_cross_border",
    "bytes",                  # log1p(bytes)
    "consent_present",
    "app_category_mismatch",
    "adid_reuse_count",
    "decrypted",
    "hashed_pii_hit",
    "time_since_interaction", # log1p(seconds)
]

SENSITIVITY = {
    "contact": 0.95, "gps": 0.9, "clipboard": 0.85, "imei": 0.8,
    "phone": 0.75, "email": 0.7, "adid": 0.6,
}

APP_CATEGORIES = [
    ("utility", re.compile(r"flash ?light|torch|calculator|qr|scanner|wallpaper|keyboard|cleaner|battery", re.I)),
    ("health", re.compile(r"fit|run|health|step|workout|yoga|period|diet", re.I)),
    ("shopping", re.compile(r"shop|cart|store|mart|buy|deal", re.I)),
    ("news", re.compile(r"news|daily|times|post|herald", re.I)),
    ("finance", re.compile(r"bank|pay|wallet|upi|loan|trade|invest", re.I)),
    ("navigation", re.compile(r"maps?|nav|ride|cab|uber|ola", re.I)),
    ("social", re.compile(r"chat|messag|social|insta|whatsapp|telegram|signal", re.I)),
    ("browser", re.compile(r"chrome|firefox|edge|brave|safari|opera", re.I)),
]

# PII a category has no plausible functional need to send.
UNEXPECTED = {
    "utility": {"gps", "contact", "phone", "imei", "email", "clipboard"},
    "news": {"contact", "imei", "phone", "gps"},
    "health": {"contact", "imei", "clipboard"},
    "shopping": {"contact", "imei", "clipboard"},
    "finance": {"contact", "clipboard"},
    "navigation": {"contact", "clipboard", "imei"},
    "social": {"imei"},
    "browser": {"imei", "contact"},
}


def app_category(app: str) -> str:
    for cat, rx in APP_CATEGORIES:
        if rx.search(app or ""):
            return cat
    return "other"


def category_mismatch(app: str, pii_types: set[str]) -> int:
    return int(bool(UNEXPECTED.get(app_category(app), set()) & pii_types))


def vector(*, pii_types: set[str], is_tracker: bool, cross_border: bool, nbytes: int,
           consent: bool, mismatch: int, adid_reuse: int, decrypted: bool, hashed: int, tsi: float) -> list[float]:
    return [
        float(len(pii_types)),
        max((SENSITIVITY.get(t, 0.5) for t in pii_types), default=0.0),
        float(is_tracker),
        float(cross_border),
        math.log1p(max(0, nbytes)),
        float(consent),
        float(mismatch),
        float(adid_reuse),
        float(decrypted),
        float(min(hashed, 3)),
        math.log1p(max(0.0, tsi)),
    ]


def rubric(f: list[float]) -> float:
    """Expert severity rubric (0-100) used to label synthetic training data.

    The XGBoost model is trained on samples labelled by this rubric plus noise, so
    it learns the rubric's interactions smoothly and exposes feature importances.
    """
    (n, sens, trk, xb, lb, consent, mism, reuse, dec, hashed, ltsi) = f
    s = 0.0
    s += 38 * sens
    s += 6 * min(n, 4)
    s += 14 * trk * (1 if n > 0 else 0.35)
    s += 8 * xb * (1 if n > 0 else 0.3)
    s += 14 * mism
    s += 4 * min(reuse, 5)
    s += 10 * hashed * trk
    s += 6 * (1 - consent) * trk * (n > 0)
    s += 5 * min(ltsi / math.log1p(300), 1.5) * trk          # idle beaconing
    s += 1.2 * max(0.0, lb - 7)
    if not dec:
        s = 0.55 * s + 12 * trk + 6                           # unknown payload: uncertainty floor
    return max(0.0, min(100.0, s))
