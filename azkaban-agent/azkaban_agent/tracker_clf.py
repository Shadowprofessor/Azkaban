"""Runtime unknown-tracker detection (CPU ONNX inference; training happens offline on GPU).

Per third-party domain NOT on the bundled lists, the agent accumulates "page" observations
(an app's 30-second request burst = one page load, the agent's equivalent of WhoTracks.me's
page) and, once it has enough, scores the domain with tracker_clf.onnx using exactly the
features the model was trained on (azkaban_agent.tracker_features). If the model or
onnxruntime is missing, detection is skipped silently.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict

import numpy as np

from .config import DATA_DIR
from .tracker_features import DEPLOYED, behaviour_from_pages, lexical, registrable

PAGE_GAP_MS = 30_000
MIN_PAGES = 3
UID_VALUE = re.compile(r"^(?:\d{6,}\.\d{6,}|[0-9a-f]{16,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[A-Za-z0-9_-]{22,})$", re.I)
UID_KEYS = re.compile(r"(^|[._-])(uid|uuid|cid|client_?id|user_?id|device_?id|adid|gaid|idfa|advertiser_?id|vid|sid|fbp|_ga)$", re.I)


def _js_num(v: float):
    """Serialise like JavaScript: 16.0 -> 16, so agent and extension JSON are byte-identical."""
    v = round(float(v), 3)
    return int(v) if v.is_integer() else v


def resource_type(raw: dict) -> str:
    """Approximate the browser's resource type from what a proxy sees."""
    ct = (raw.get("resp_type") or "").lower()
    method = (raw.get("method") or "").upper()
    path = (raw.get("path") or "").lower()
    status = int(raw.get("status") or 0)
    if method == "POST" and (status == 204 or "beacon" in path or not ct):
        return "beacon"
    if ct.startswith("image/") or path.endswith((".gif", ".png", ".jpg", ".webp", ".svg")):
        return "image"
    if "javascript" in ct or path.endswith(".js"):
        return "script"
    if "css" in ct or path.endswith(".css"):
        return "stylesheet"
    if ct.startswith("font/") or "font" in ct or path.endswith((".woff", ".woff2", ".ttf")):
        return "font"
    if ct.startswith(("video/", "audio/")):
        return "media"
    if "html" in ct:
        return "iframe"
    return "xhr"


def _uid_in_query(query: str) -> bool:
    from urllib.parse import parse_qsl
    for k, v in parse_qsl(query or "")[:50]:
        if UID_KEYS.search(k) or UID_VALUE.match(v.strip()):
            return True
    return False


class TrackerClassifier:
    def __init__(self, path=DATA_DIR / "tracker_clf.onnx"):
        self.sess = self.cat_sess = None
        self.meta: dict = {}
        try:
            import onnxruntime as ort
            meta_p = path.with_name("tracker_clf_meta.json")
            if path.is_file() and meta_p.is_file():
                self.meta = json.loads(meta_p.read_text())
                if self.meta.get("features") != DEPLOYED:
                    raise ValueError("feature contract mismatch between model and runtime")
                self.sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
                cat = path.with_name("tracker_clf_cat.onnx")
                if cat.is_file():
                    self.cat_sess = ort.InferenceSession(str(cat), providers=["CPUExecutionProvider"])
        except Exception:
            self.sess = self.cat_sess = None
        self.threshold = float(self.meta.get("threshold", 0.5))
        self.medians = self.meta.get("impute_medians", {})
        self.classes = self.meta.get("classes", [])
        self.top_global = [f["feature"] for f in self.meta.get("top_features", [])]
        # domain -> list of page dicts; domain -> (app, page start ms) of the open page
        self.pages: dict[str, list[dict]] = defaultdict(list)
        self.open_page: dict[tuple[str, str], int] = {}
        self.reported: set[str] = set()

    @property
    def available(self) -> bool:
        return self.sess is not None

    # ---------------------------------------------------------------- observe
    def observe(self, raw: dict, listed: bool) -> None:
        if not self.available or listed:
            return
        host = (raw.get("host") or "").lower()
        if not host or "." not in host:
            return
        dom = registrable(host)
        app = raw.get("app") or "unknown"
        ts = int(raw.get("orig_ts") or raw.get("ts") or 0)
        key = (app, dom)
        start = self.open_page.get(key)
        pages = self.pages[dom]
        if start is None or ts - start > PAGE_GAP_MS or not pages:
            pages.append({"types": set(), "requests": 0, "bytes": 0, "cookies": False, "uid_qs": False,
                          "https": False, "referer_leaked": False, "samesite_none": None})
            self.open_page[key] = ts
            if len(pages) > 200:
                del pages[:100]
        p = pages[-1]
        headers = {k.lower(): v for k, v in (raw.get("headers") or {}).items()}
        p["types"].add(resource_type(raw))
        p["requests"] += 1
        p["bytes"] += int(raw.get("bytes") or 0)
        p["cookies"] |= bool(headers.get("cookie"))
        p["uid_qs"] |= _uid_in_query(raw.get("query") or "")
        p["https"] |= bool(raw.get("decrypted", True))  # proxied flows are TLS-intercepted HTTPS
        ref = headers.get("referer", "")
        p["referer_leaked"] |= bool(ref and ("?" in ref or ref.rstrip("/").count("/") > 2))
        if raw.get("samesite_none") is not None:
            p["samesite_none"] = bool(p["samesite_none"]) or bool(raw["samesite_none"])

    # ---------------------------------------------------------------- score
    def features(self, domain: str) -> np.ndarray:
        feats = lexical(domain) | behaviour_from_pages(self.pages.get(domain, []))
        row = []
        for c in DEPLOYED:
            v = feats.get(c, float("nan"))
            if v is None or (isinstance(v, float) and math.isnan(v)):
                v = self.medians.get(c, 0.0)
            row.append(float(v))
        return np.asarray([row], dtype=np.float32)

    def score(self, domain: str) -> tuple[float, str]:
        x = self.features(domain)
        out = self.sess.run(None, {self.sess.get_inputs()[0].name: x})
        probs = np.asarray(out[1])
        p = float(probs[0][1]) if probs.ndim == 2 else float(out[1][0][1])
        category = ""
        if self.cat_sess is not None:
            pc = np.asarray(self.cat_sess.run(None, {self.cat_sess.get_inputs()[0].name: x})[1])[0]
            category = self.classes[int(np.argmax(pc))] if self.classes else ""
        return p, category

    def top_features(self, domain: str, k: int = 4) -> list[dict]:
        """Most important (globally) features whose value for this domain departs from the median."""
        x = self.features(domain)[0]
        out = []
        for name in self.top_global:
            i = DEPLOYED.index(name)
            med = float(self.medians.get(name, 0.0))
            if abs(float(x[i]) - med) > 1e-6:
                out.append({"feature": name, "value": _js_num(x[i]), "median": _js_num(med)})
            if len(out) >= k:
                break
        return out

    def candidates(self) -> list[dict]:
        """Unreported, unlisted domains with enough evidence that the model flags."""
        res = []
        if not self.available:
            return res
        for dom, pages in self.pages.items():
            if dom in self.reported or len(pages) < MIN_PAGES:
                continue
            p, category = self.score(dom)
            if p >= self.threshold:
                self.reported.add(dom)
                res.append({"domain": dom, "category": category or "tracking", "confidence": _js_num(p),
                            "topFeatures": self.top_features(dom), "pages": len(pages)})
        return res


def insight(c: dict) -> dict:
    """The unknown_tracker InsightMsg — the same shape the extension forwards."""
    return {
        "type": "insight",
        "key": f"unknown_tracker:{c['domain']}",
        "kind": "unknown_tracker",
        "level": "warn",
        "title": f"Likely tracker not on any list: {c['domain']}",
        "detail": f"{c['category']}, confidence {c['confidence']:.2f}; flagged by behaviour+structure, not a blocklist",
        "data": {"domain": c["domain"], "category": c["category"], "confidence": c["confidence"],
                 "topFeatures": c["topFeatures"]},
    }
