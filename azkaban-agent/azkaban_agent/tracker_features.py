"""Tracker-classifier features — the single source of truth for training AND runtime.

train/features.py re-exports this module; the extension has a line-for-line TypeScript port
(azkaban-extension/lib/trackerFeatures.ts) checked against fixtures generated from here.

Semantics follow WhoTracks.me (the source of REAL behaviour for training): behavioural values
are PER-PAGE proportions — e.g. `beh_cookies` = share of page loads on which the domain used
cookies — and request/byte counts are averages per page load. Runtime computes the same
quantities from locally observed page loads (extension: tab navigation; agent: an app's
30-second request burst).

Availability tags:
  browser   computable by the extension and the agent
  agent     computable only by the agent (e.g. Set-Cookie attributes hidden from extensions)
  global    population statistics (reach, Ghostery's own tracking heuristic) — NOT computable
            locally, used only in the ablation study, never in the deployed model
"""
from __future__ import annotations

import math
from collections import Counter

SECOND_LEVEL = {"co", "com", "net", "org", "gov", "ac", "edu", "ne", "or", "go"}
COMMON_TLDS = {"com", "net", "org", "io"}
KEYWORDS = ("ad", "ads", "track", "analytic", "metric", "pixel", "tag", "stat", "click", "beacon",
            "collect", "count", "log", "sync", "bid", "data", "cdn", "static", "font", "img", "api", "media")
NGRAM_BUCKETS = 32

LEXICAL = (["lex_len", "lex_entropy", "lex_digit_ratio", "lex_hyphens", "lex_vowel_ratio",
            "lex_tld_cc", "lex_tld_common", "lex_second_level"]
           + [f"kw_{k}" for k in KEYWORDS] + [f"ng_{i}" for i in range(NGRAM_BUCKETS)])
# Request-structure mix: share of page loads on which the domain served each resource type.
STRUCTURAL = ["beh_script", "beh_iframe", "beh_beacon", "beh_image", "beh_stylesheet", "beh_font", "beh_xhr",
              "beh_media", "beh_log_requests", "beh_log_content_length"]
BEHAVIOURAL = ["beh_cookies", "beh_bad_qs", "beh_https", "beh_referer_leaked", "beh_samesite_none", "has_behavior"]
GLOBAL_ONLY = ["glob_reach", "glob_site_avg_frequency", "glob_site_reach_top10k", "glob_tracked", "glob_requests_tracking"]

AVAILABILITY = {f: "browser" for f in LEXICAL + STRUCTURAL + BEHAVIOURAL}
AVAILABILITY["beh_samesite_none"] = "agent"
AVAILABILITY.update({f: "global" for f in GLOBAL_ONLY})

DEPLOYED = LEXICAL + STRUCTURAL + BEHAVIOURAL  # what tracker_clf.onnx consumes, in this order

# WhoTracks.me column -> feature
WTM_COLUMNS = {
    "script": "beh_script", "iframe": "beh_iframe", "beacon": "beh_beacon", "image": "beh_image",
    "stylesheet": "beh_stylesheet", "font": "beh_font", "xhr": "beh_xhr", "media": "beh_media",
    "cookies": "beh_cookies", "bad_qs": "beh_bad_qs", "https": "beh_https",
    "referer_leaked": "beh_referer_leaked", "cookie_samesite_none": "beh_samesite_none",
    "reach": "glob_reach", "site_avg_frequency": "glob_site_avg_frequency",
    "site_reach_top10k": "glob_site_reach_top10k", "tracked": "glob_tracked",
    "requests_tracking": "glob_requests_tracking",
}


def registrable(host: str) -> str:
    """eTLD+1 heuristic, identical to the extension's lib/domain.ts."""
    h = host.lower().rstrip(".")
    labels = h.split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def group_key(domain: str) -> str:
    """Leakage guard for CV: doubleclick.net and doubleclick.com share a group."""
    return registrable(domain).split(".")[0]


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    c = Counter(s)
    return -sum(v / len(s) * math.log2(v / len(s)) for v in c.values())


def fnv1a(s: str) -> int:
    """32-bit FNV-1a — trivial to reproduce bit-for-bit in TypeScript."""
    h = 0x811C9DC5
    for ch in s.encode("utf-8"):
        h ^= ch
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def lexical(domain: str) -> dict[str, float]:
    reg = registrable(domain)
    labels = reg.split(".")
    name = labels[0]
    tld = labels[-1]
    f = {
        "lex_len": float(len(name)),
        "lex_entropy": _entropy(name),
        "lex_digit_ratio": sum(c.isdigit() for c in name) / max(1, len(name)),
        "lex_hyphens": float(name.count("-")),
        "lex_vowel_ratio": sum(c in "aeiou" for c in name) / max(1, len(name)),
        "lex_tld_cc": float(len(tld) == 2),
        "lex_tld_common": float(tld in COMMON_TLDS),
        "lex_second_level": float(len(labels) == 3),
    }
    for k in KEYWORDS:
        f[f"kw_{k}"] = float(k in name)
    grams = [name[i:i + 3] for i in range(max(0, len(name) - 2))] or [name]
    buckets = [0.0] * NGRAM_BUCKETS
    for g in grams:
        buckets[fnv1a(g) % NGRAM_BUCKETS] += 1.0
    total = sum(buckets) or 1.0
    for i, v in enumerate(buckets):
        f[f"ng_{i}"] = v / total
    return f


def behaviour_from_wtm(row: dict) -> dict[str, float]:
    """WhoTracks.me aggregate -> features (NaN when absent)."""
    nan = float("nan")
    f = {feat: _num(row.get(f"wtm_{col}", row.get(col))) for col, feat in WTM_COLUMNS.items()}
    req = _num(row.get("wtm_requests", row.get("requests")))
    cl = _num(row.get("wtm_content_length", row.get("content_length")))
    f["beh_log_requests"] = math.log1p(req) if not math.isnan(req) else nan
    f["beh_log_content_length"] = math.log1p(cl) if not math.isnan(cl) else nan
    f["has_behavior"] = 0.0 if math.isnan(f["beh_script"]) else 1.0
    return f


def behaviour_from_pages(pages: list[dict]) -> dict[str, float]:
    """Runtime: per-page observations for ONE domain -> same features as WhoTracks.

    Each page dict: {types: set[str], requests: int, bytes: int, cookies: bool, uid_qs: bool,
                     https: bool, referer_leaked: bool, samesite_none: bool | None}
    """
    n = len(pages)
    if n == 0:
        return {f: float("nan") for f in STRUCTURAL + BEHAVIOURAL[:-1]} | {"has_behavior": 0.0}
    share = lambda pred: sum(1 for p in pages if pred(p)) / n  # noqa: E731
    f = {f"beh_{t}": share(lambda p, t=t: t in p["types"]) for t in
         ("script", "iframe", "beacon", "image", "stylesheet", "font", "xhr", "media")}
    f["beh_log_requests"] = math.log1p(sum(p["requests"] for p in pages) / n)
    f["beh_log_content_length"] = math.log1p(sum(p["bytes"] for p in pages) / n)
    f["beh_cookies"] = share(lambda p: p["cookies"])
    f["beh_bad_qs"] = share(lambda p: p["uid_qs"])
    f["beh_https"] = share(lambda p: p["https"])
    f["beh_referer_leaked"] = share(lambda p: p["referer_leaked"])
    known = [p for p in pages if p.get("samesite_none") is not None]
    f["beh_samesite_none"] = sum(1 for p in known if p["samesite_none"]) / len(known) if known else float("nan")
    f["has_behavior"] = 1.0
    return f


def vector(domain: str, beh: dict[str, float], columns: list[str] = DEPLOYED) -> list[float]:
    feats = lexical(domain) | beh
    return [float(feats.get(c, float("nan"))) for c in columns]


def _num(v) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else float("nan")
    except (TypeError, ValueError):
        return float("nan")
