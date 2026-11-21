"""Detect privacy evidence by content, independently of the app that made a report."""

import ipaddress
import re
from collections import defaultdict
from itertools import islice

from .report_formats import MAX_ITEMS, sections


EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[a-z]{2,}", re.I)
PHONE = re.compile(r"\+?[\d(). -]{7,24}")
NUMBER = re.compile(r"[+-]?(?:\d{1,4}(?:\.\d{1,16})?|\.\d{1,16})")
PRESENT = {"granted", "allowed", "enabled"}
SEVERITIES = {"critical", "high", "medium", "moderate", "low"}
SCALARS = {"", "null", "none", "unknown", "redacted", "masked", "n/a", "na", "not available", "false", "-", "[redacted]"}
REPORT_PREFIX = re.compile(
    r"^(?:[-*#\s]*)(?:\[(?:critical|high|medium|moderate|low)\]|"
    r"(?:audit\s+)?(?:finding|observation|issue|risk)(?:\s+#?\d+)?\s*[:–-]|"
    r"(?:critical|high|medium|moderate|low)(?:\s+(?:risk|severity))?\s*[:|–-])\s*(.+)$",
    re.I,
)
POSITIVE = re.compile(
    r"\b(?:expos\w*|publicly accessible|collect\w*|retain\w*|stor\w*|granted|allow\w*|enabl\w*|"
    r"shar\w*|transfer\w*|unencrypted|logged|present|recorded|visible|leak\w*)\b", re.I
)
NEGATIVE = re.compile(
    r"\b(?:no|not|never|denied|blocked|disabled|redacted|masked|mitigated|resolved|"
    r"recommended|consider|should|could|would|may|if|hypothetical|sample|placeholder|example)\b", re.I
)
REPORTED_TOPICS = {
    "location": r"precise location|location history|gps|coordinates?|home address|street address|geolocation",
    "contacts": r"email(?: addresses?)?|phone(?: numbers?)?|synced contacts|address book|contact details|contacts",
    "security": r"ip addresses?|device identifiers?|device ids?|user agents?|session tokens?|passwords?|credentials?",
    "permissions": r"(?:camera|microphone|location|notification) (?:access|permissions?)|browser permissions?",
    "messages": r"message (?:contents?|history|bodies)|chat transcripts?|private messages",
    "sharing": r"third.part(?:y|ies)|external (?:vendor|recipient|processor)|data broker",
    "activity": r"browsing history|search queries|search history|watch history|activity logs",
    "interests": r"advertising profiles?|ad targeting|inferred interests?|profiling",
    "shopping": r"purchase history|order history",
    "identity": r"identity documents?|national ids?|dates? of birth|passport numbers?|tax (?:id|identifier)",
    "financial": r"credit cards?|card numbers?|bank accounts?|financial records",
}
REPORTED_PATTERNS = {name: re.compile(rf"\b(?:{pattern})\b", re.I) for name, pattern in REPORTED_TOPICS.items()}


def key_name(key):
    return re.sub(r"[^a-z0-9]", "", key.lower())


def values_from(record):
    return {key_name(key): str(value).strip()[:300] for key, value in record.items()
            if isinstance(key, str) and type(value) in (str, int, float)
            and str(value).strip().lower() not in SCALARS}


def observed_fields(fields):
    found = {}
    if any(EMAIL.fullmatch(fields.get(key, "")) for key in ("email", "emailaddress", "contactemail", "workemail", "personalemail")):
        found["contacts"] = "Validly formatted email address fields"
    elif any(PHONE.fullmatch(value) and 7 <= sum(char.isdigit() for char in value) <= 15
             for key in ("phone", "phonenumber", "telephone", "mobile", "contactnumber")
             if (value := fields.get(key, ""))):
        found["contacts"] = "Telephone number fields"

    lat = fields.get("latitude", fields.get("lat", ""))
    lng = fields.get("longitude", fields.get("lon", fields.get("lng", "")))
    if NUMBER.fullmatch(lat) and NUMBER.fullmatch(lng) and abs(float(lat)) <= 90 and abs(float(lng)) <= 180:
        found["location"] = "Coordinate pairs within geographic bounds"
    elif any(re.search(r"\d+\s+[\w.]+", fields.get(key, "")) for key in ("streetaddress", "homeaddress", "mailingaddress", "residentialaddress")):
        found["location"] = "Street address fields"

    for key in ("ip", "ipaddress", "clientip", "sourceip", "remoteaddr"):
        try:
            ipaddress.ip_address(fields.get(key, ""))
            found["security"] = "Validly formatted IP address fields"
            break
        except ValueError:
            continue
    if "security" not in found and any(len(fields.get(key, "")) >= 4 for key in ("deviceid", "deviceidentifier", "useragent")):
        found["security"] = "Device identifier or user-agent fields"
    sensors = {"camera", "microphone", "geolocation", "location", "notifications"}
    if (fields.get("permission", "").lower() in sensors
            and fields.get("status", fields.get("state", "")).lower() in PRESENT
            or any(fields.get(name, "").lower() in PRESENT for name in sensors)):
        found["permissions"] = "Explicit granted or enabled permission fields"
    if any(len(fields.get(key, "")) >= 5 for key in ("messagebody", "messagecontent", "chattranscript")):
        found["messages"] = "Message or transcript fields"
    if any(len(fields.get(key, "")) >= 3 for key in ("searchquery", "browserhistory", "visitedurl", "browsingurl", "watchtitle")):
        found["activity"] = "Recorded search, watch, or browsing fields"
    if any(len(fields.get(key, "")) >= 3 for key in ("productname", "itemname", "ordertotal")) and any(
            key in fields for key in ("orderid", "orderdate", "purchaseid", "purchasedate")):
        found["shopping"] = "Dated or identified purchase records"
    if any(re.fullmatch(r"[A-Za-z0-9 -]{5,30}", fields.get(key, ""))
           for key in ("nationalid", "taxid", "passportnumber", "socialsecuritynumber")):
        found["identity"] = "Government identifier fields"
    elif any(re.fullmatch(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}", fields.get(key, ""))
             for key in ("dateofbirth", "birthdate", "dob")):
        found["identity"] = "Birth-date fields"
    for key in ("cardnumber", "creditcardnumber", "bankaccountnumber", "iban"):
        value = fields.get(key, "").replace(" ", "").replace("-", "")
        if re.fullmatch(r"[A-Za-z0-9]{8,34}", value) and sum(char.isdigit() for char in value) >= 8:
            found["financial"] = "Payment or financial account identifier fields"
            break
    return found


def reported_categories(text):
    if not POSITIVE.search(text) or NEGATIVE.search(text):
        return []
    return [category for category, pattern in REPORTED_PATTERNS.items() if pattern.search(text)]


def generic_evidence(data, suffix):
    results = defaultdict(lambda: {"count": 0, "signals": set(), "locations": [], "precise": 0})
    for location, record in islice(sections(data, suffix), MAX_ITEMS):
        reported = []
        if isinstance(record, str):
            finding = REPORT_PREFIX.match(record)
            key, separator, value = record.partition(":")
            fields = values_from({key.strip("-* #"): value}) if separator else {}
            if finding:
                reported = reported_categories(finding[1])
        else:
            fields = values_from(record)
            severity = fields.get("severity", fields.get("risklevel", "")).lower()
            if severity in SEVERITIES and fields.get("status", "").lower() not in {"resolved", "closed", "mitigated", "passed"}:
                text = " ".join(fields.get(key, "") for key in
                                ("title", "finding", "description", "details", "summary", "observation", "issue"))
                reported = reported_categories(text)
        for category, signal in observed_fields(fields).items():
            result = results[category, "observed"]
            result["count"] += 1
            result["signals"].add(signal)
            if signal == "Coordinate pairs within geographic bounds":
                # Numeric coordinates can be rounded. Check precision separately from presence.
                lat = fields.get("latitude", fields.get("lat", ""))
                lon = fields.get("longitude", fields.get("lon", fields.get("lng", "")))
                if all(len(value.partition(".")[2]) >= 4 for value in (lat, lon)):
                    result["precise"] += 1
            if len(result["locations"]) < 3:
                result["locations"].append(location)
        for category in reported:
            result = results[category, "reported"]
            result["count"] += 1
            result["signals"].add("The report states a finding. Independent verification is unavailable.")
            if len(result["locations"]) < 3:
                result["locations"].append(location)
    return results
