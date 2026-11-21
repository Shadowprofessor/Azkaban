"""PII extractors. Raw values stay inside the agent; only `PiiHit.redacted` is emitted."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import PiiHit

EMAIL = re.compile(r"(?<![\w.+-])([A-Za-z0-9._%+-]{1,64})@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24})(?![\w-])")
UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
DIGITS15 = re.compile(r"(?<!\d)(\d{15})(?!\d)")
PHONE_E164 = re.compile(r"(?<![\w])\+(\d{1,3})[\s-]?(\d[\d\s-]{6,13}\d)(?!\d)")
PHONE_IN = re.compile(r"(?<!\d)(?:0|91)?([6-9]\d{9})(?!\d)")
LATLNG = re.compile(r"(?<![\d.])(-?\d{1,2}\.\d{4,})\s*,\s*(-?\d{1,3}\.\d{4,})(?![\d.])")
FLOAT = re.compile(r"^-?\d{1,3}\.\d{3,}$")

ADID_KEYS = re.compile(r"(^|[._\[])(adid|ad_id|gaid|aaid|idfa|advertising_?id|advertiserid|rdid|ifa|google_ad_id|android_ad_id)($|[._\]])", re.I)
IMEI_KEYS = re.compile(r"imei|device_?id|meid", re.I)
PHONE_KEYS = re.compile(r"phone|mobile|msisdn|tel\b|contact_?number|cell", re.I)
LAT_KEYS = re.compile(r"(^|[._])(lat|latitude)$", re.I)
LNG_KEYS = re.compile(r"(^|[._])(lng|lon|long|longitude)$", re.I)
CONTACT_KEYS = re.compile(r"contacts?|address_?book|phonebook", re.I)
CLIP_KEYS = re.compile(r"clipboard|pasteboard|clip_?text", re.I)
SKIP_KEYS = re.compile(r"^(header\.(user-agent|content-type)|path)$", re.I)

ZERO_UUID = "00000000-0000-0000-0000-000000000000"


@dataclass
class Finding:
    type: str
    value: str          # raw — never serialised out of the agent
    redacted: str
    confidence: float
    key: str = ""
    via: str = ""        # e.g. "base64", "sha256" (Phase 5)

    def hit(self) -> PiiHit:
        return PiiHit(type=self.type, redacted=self.redacted, confidence=round(self.confidence, 2))


# ------------------------------------------------------------------ redaction
def redact_email(local: str, domain: str) -> str:
    d0, _, tld = domain.rpartition(".")
    return f"{local[:1]}***@{d0[:1]}***.{tld}"


def redact_tail(s: str, keep: int = 4) -> str:
    digits = re.sub(r"\D", "", s)
    return "*" * max(0, len(digits) - keep) + digits[-keep:]


def redact_id(s: str) -> str:
    return f"{s[:4]}****-****{s[-4:]}"


def redact_gps(lat: float, lng: float) -> str:
    return f"{lat:.1f},{lng:.1f} (~11km)"


def luhn_ok(num: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(num)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ------------------------------------------------------------------ detectors
def scan_pair(key: str, value: str) -> list[Finding]:
    if not value or SKIP_KEYS.match(key):
        return []
    out: list[Finding] = []
    v = value[:20000]

    for m in EMAIL.finditer(v):
        local, dom = m.group(1), m.group(2)
        out.append(Finding("email", f"{local}@{dom}".lower(), redact_email(local, dom), 0.95, key))

    keyed_adid = bool(ADID_KEYS.search(key))
    for m in UUID.finditer(v):
        u = m.group(0).lower()
        if u == ZERO_UUID:
            continue
        if keyed_adid:
            out.append(Finding("adid", u, redact_id(u), 0.95, key))

    for m in DIGITS15.finditer(v):
        n = m.group(1)
        if luhn_ok(n) and n[:2] in {"01", "30", "33", "35", "44", "45", "49", "50", "51", "52", "53", "54", "86", "91", "98", "99"}:
            conf = 0.95 if IMEI_KEYS.search(key) else 0.6
            out.append(Finding("imei", n, n[:2] + redact_tail(n)[2:], conf, key))

    phone_key = bool(PHONE_KEYS.search(key))
    for m in PHONE_E164.finditer(v):
        raw = "+" + m.group(1) + re.sub(r"\D", "", m.group(2))
        if 8 <= len(raw) - 1 <= 15:
            out.append(Finding("phone", raw, "+" + m.group(1) + redact_tail(m.group(2), 3)[-10:], 0.9 if phone_key else 0.7, key))
    if phone_key or not out:
        for m in PHONE_IN.finditer(v):
            num = "+91" + m.group(1)
            if any(f.value == num for f in out):
                continue
            if phone_key:
                out.append(Finding("phone", num, "+91" + redact_tail(m.group(1), 3), 0.85, key))

    for m in LATLNG.finditer(v):
        lat, lng = float(m.group(1)), float(m.group(2))
        if -90 <= lat <= 90 and -180 <= lng <= 180 and (lat, lng) != (0.0, 0.0):
            out.append(Finding("gps", f"{lat},{lng}", redact_gps(lat, lng), 0.8, key))

    if CONTACT_KEYS.search(key):
        out.append(Finding("contact", f"{key}:{v[:64]}", f"contact data in '{key.split('.')[-1]}'", 0.75, key))
    if CLIP_KEYS.search(key):
        out.append(Finding("clipboard", v[:256], f"<clipboard {len(v)} chars>", 0.9, key))
    return out


def scan_gps_pairs(pairs: list[tuple[str, str]]) -> list[Finding]:
    """lat / lng sent as separate fields."""
    lats = {k.rsplit(".", 1)[0] if "." in k else "": v for k, v in pairs if LAT_KEYS.search(k) and FLOAT.match(v.strip())}
    lngs = {k.rsplit(".", 1)[0] if "." in k else "": v for k, v in pairs if LNG_KEYS.search(k) and FLOAT.match(v.strip())}
    out = []
    for parent, lat in lats.items():
        lng = lngs.get(parent)
        if lng is None:
            continue
        la, lo = float(lat), float(lng)
        if -90 <= la <= 90 and -180 <= lo <= 180:
            out.append(Finding("gps", f"{la},{lo}", redact_gps(la, lo), 0.9, parent or "lat/lng"))
    return out


def scan(pairs: list[tuple[str, str]]) -> list[Finding]:
    found: list[Finding] = []
    for k, v in pairs:
        found += scan_pair(k, v)
    found += scan_gps_pairs(pairs)
    # Contact lists: JSON arrays of objects that each carry a phone or email.
    arr_hits = {}
    for f in found:
        if f.type in ("phone", "email") and re.search(r"\[\d+\]", f.key):
            root = f.key.split("[")[0]
            arr_hits.setdefault(root, set()).add(f.key.split("]")[0])
    for root, items in arr_hits.items():
        if len(items) >= 3:
            found.append(Finding("contact", f"{root}:{len(items)}", f"{len(items)} contacts in '{root}'", 0.85, root))
    return dedupe(found)


def dedupe(found: list[Finding]) -> list[Finding]:
    best: dict[tuple[str, str], Finding] = {}
    for f in found:
        k = (f.type, f.value)
        if k not in best or f.confidence > best[k].confidence:
            best[k] = f
    return list(best.values())
