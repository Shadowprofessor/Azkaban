import csv
import io
import json
import math
import os
import re
import zipfile
from collections import Counter
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

from .retrieval import PLATFORMS, retrieve


MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 384 * 1024 * 1024
MAX_FILES = 30_000
WEIGHTS = {"location": 85, "security": 76, "contacts": 72, "messages": 67,
           "connections": 41, "activity": 34, "interests": 30}
REASONS = {
    "location": "Location records can reveal where activity took place.",
    "security": "Session metadata can reveal devices and networks used to access an account.",
    "contacts": "Contact records can contain other people's names and contact details.",
    "messages": "Message archives can retain private communication.",
    "connections": "Follower and following records expose parts of a social graph.",
    "activity": "Timestamped activity can reveal repeated habits.",
    "interests": "Activity or advertising labels can reveal preferences.",
}


class TakeoutActivity(HTMLParser):
    """Count recognized Google Takeout activity cards without rendering HTML."""

    def __init__(self):
        super().__init__()
        self.count = 0

    def handle_starttag(self, tag, attrs):
        if tag == "div" and "outer-cell" in dict(attrs).get("class", "").split():
            self.count += 1


def classify(name, platform=None):
    path = name.lower().replace("\\", "/")
    stem, suffix = os.path.splitext(path.rsplit("/", 1)[-1])
    if platform in (None, "Google"):
        if suffix == ".vcf" or suffix == ".csv" and (
            "/contacts/" in f"/{path}" or platform == "Google" and "contacts" in stem
        ):
            return "Google", "contacts"
        if suffix == ".json" and (stem in {"records", "location history", "timeline"} or
                                  "semantic location history/" in path or stem.startswith("timeline")):
            if platform or any(marker in path for marker in ("location history", "timeline")):
                return "Google", "location"
        if suffix in {".json", ".html"} and ("my activity/" in path or stem in {
            "myactivity", "watch-history", "search-history"
        }):
            return "Google", "activity"
        if suffix == ".json" and stem in {"ad_topics", "ad_interests"} and (
            platform == "Google" or path.startswith("takeout/")
        ):
            return "Google", "interests"
    if suffix != ".json":
        return None
    if platform in (None, "Instagram"):
        rules = [
            (r"synced_contacts|uploaded_contacts|contacts", "contacts"),
            (r"followers(?:_\d+)?|following(?:_\d+)?", "connections"),
            (r"message_\d+", "messages"),
            (r"login_activity(?:_\d+)?|logins", "security"),
            (r"ad_topics|ads_interests|ads_topics|interests", "interests"),
        ]
        for pattern, category in rules:
            if re.fullmatch(pattern, stem) and (platform or stem not in {"contacts", "interests", "logins"}
                                                or "instagram" in path):
                return "Instagram", category
    if platform in (None, "Spotify"):
        if re.fullmatch(r"streaming(?:_?history)(?:[a-z]+)?(?:_.*|\d+)?|endsong_\d+", stem):
            return "Spotify", "activity"
        if stem in {"inferences", "inference"}:
            return "Spotify", "interests"
        if stem in {"follow", "followers", "following"} and (platform or "spotify" in path):
            return "Spotify", "connections"
    return None


def records_in(value, fields):
    if isinstance(value, list):
        return [record for record in value if isinstance(record, (dict, str)) and record]
    if isinstance(value, dict):
        return [record for field in fields if isinstance(value.get(field), list)
                for record in value[field] if isinstance(record, (dict, str)) and record]
    return []


def utc_hour(row):
    for key in ("ts", "time", "endTime", "timestamp", "creation_timestamp", "timestamp_ms",
                "timestampMs", "startTime"):
        value = row.get(key)
        try:
            if isinstance(value, (int, float)) or isinstance(value, str) and value.isdecimal():
                seconds = int(value)
                return datetime.fromtimestamp(seconds / 1000 if seconds > 10**11 else seconds, UTC).hour
            if isinstance(value, str):
                moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
                # Spotify legacy endTime is UTC. Other timezone-less values are ambiguous.
                if moment.tzinfo is None and key != "endTime":
                    continue
                return moment.astimezone(UTC).hour if moment.tzinfo else moment.hour
        except (ValueError, OverflowError, OSError):
            continue
    return None


def summarize(text, name, platform, category):
    if name.lower().endswith(".vcf"):
        return len(re.findall(r"^BEGIN:VCARD\s*$", text, re.I | re.M)), [], Counter(), Counter()
    if name.lower().endswith(".csv"):
        count = sum(any(cell.strip() for cell in row) for row in csv.reader(io.StringIO(text)))
        return max(0, count - 1), [], Counter(), Counter()
    if name.lower().endswith(".html"):
        parser = TakeoutActivity()
        parser.feed(text)
        return parser.count, [], Counter(), Counter()
    value = json.loads(text)
    fields = {
        "location": ("locations", "timelineObjects", "semanticSegments", "timelinePath", "rawSignals"),
        "contacts": ("contacts", "synced_contacts", "contacts_contact_info"),
        "connections": ("relationships_following", "relationships_followers", "following", "followers"),
        "messages": ("messages",),
        "security": ("account_history_login_history", "login_activity", "logins"),
        "interests": ("inferences", "ad_topics", "ads_interests", "topics", "topics_your_topics"),
        "activity": ("activities", "items"),
    }
    rows = records_in(value, fields[category])
    objects = [row for row in rows if isinstance(row, dict)]
    extra = []
    hours = Counter(hour for row in objects if (hour := utc_hour(row)) is not None)
    artists = Counter()
    if platform == "Spotify" and category == "activity":
        countries = [row for row in objects if row.get("conn_country")]
        ips = [row for row in objects if row.get("ip_addr") or row.get("ip_addr_decrypted")]
        if countries:
            extra.append(("location", len(countries), "Connection country"))
        if ips:
            extra.append(("security", len(ips), "Streaming IP present"))
        for row in objects:
            artist = row.get("master_metadata_album_artist_name") or row.get("artistName")
            if isinstance(artist, str) and (artist := artist.strip()):
                artists[artist[:160]] += 1
    return len(rows), extra, hours, artists


def directory_members(path):
    for root, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = sorted(directory for directory in dirs
                         if not (Path(root) / directory).is_symlink()
                         and not getattr(Path(root) / directory, "is_junction", lambda: False)())
        for filename in sorted(files):
            member = Path(root) / filename
            if not member.is_symlink() and member.is_file():
                yield member.relative_to(path).as_posix(), member.stat().st_size, member.open


def archive_members(archive):
    for member in archive.infolist():
        if not member.is_dir():
            yield member.filename, member.file_size, lambda mode, member=member: archive.open(member, mode)


def audit(inputs):
    """Each input is a (path, optional platform) pair. Raw export data stays in this process."""
    findings = {}
    hours = {}
    artists = Counter()
    coverage = []

    def add(platform, category, count, source, signal=None):
        finding = findings.setdefault((platform, category), {
            "platform": platform, "category": category, "count": 0, "sources": [], "signals": []
        })
        finding["count"] += count
        if len(finding["sources"]) < 5 and source not in finding["sources"]:
            finding["sources"].append(source)
        if signal and signal not in finding["signals"]:
            finding["signals"].append(signal)

    def scan(members, hint, status, input_number):
        consumed = 0
        for index, (name, size, open_member) in enumerate(members):
            if index >= MAX_FILES:
                status["file_limit_reached"] = True
                break
            classification = classify(name, hint)
            if classification is None:
                status["unrecognized_files"] += 1
                continue
            if size > MAX_FILE or size > MAX_TOTAL - consumed:
                status["limited_files"] += 1
                continue
            platform, category = classification
            try:
                with open_member("r" if status["kind"] == "zip" else "rb") as stream:
                    data = stream.read(size + 1)
                consumed += len(data)
                if len(data) > size:
                    status["limited_files"] += 1
                    continue
                count, extra, activity, preferences = summarize(
                    data.decode("utf-8-sig"), name, platform, category
                )
            except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, csv.Error, RecursionError):
                status["unreadable_files"] += 1
                continue
            if not count:
                status["empty_or_unsupported_files"] += 1
                continue
            status["parsed_files"] += 1
            evidence = f"Export {input_number} · {name[:400]}"
            add(platform, category, count, evidence)
            for extra_category, amount, signal in extra:
                add(platform, extra_category, amount, evidence, signal)
            if activity and category == "activity":
                hours.setdefault(platform, Counter()).update(activity)
            artists.update(preferences)

    seen = set()
    for number, (filename, hint) in enumerate(inputs, 1):
        if hint is not None and hint not in PLATFORMS.values():
            raise ValueError("Unknown platform hint.")
        path = Path(filename).expanduser().resolve()
        if path in seen:
            continue
        seen.add(path)
        status = dict(export=number, kind="zip" if path.is_file() else "directory",
                      parsed_files=0, unrecognized_files=0, limited_files=0,
                      unreadable_files=0, empty_or_unsupported_files=0, file_limit_reached=False)
        if path.is_dir():
            scan(directory_members(path), hint, status, number)
        elif path.is_file() and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                scan(archive_members(archive), hint, status, number)
        else:
            raise ValueError(f"Export {number} must be a ZIP or a directory.")
        coverage.append(status)
    ranked = []
    for (platform, category), finding in findings.items():
        score = min(100, WEIGHTS[category] + round(4 * math.log10(finding["count"] + 1)))
        if platform == "Spotify" and category in {"location", "security"}:
            score = min(score, 57 if category == "location" else 51)
        sources = retrieve(f"{platform} {category}", platform=platform, category=category, k=1)
        ranked.append({**finding, "priority": score, "reason": REASONS[category],
                       "guide": sources[0] if sources else None})
    ranked.sort(key=lambda item: (-item["priority"], item["platform"], item["category"]))
    return {
        "findings": ranked,
        "coverage": coverage,
        "activity_utc": {platform: [counts[hour] for hour in range(24)]
                         for platform, counts in sorted(hours.items())},
        "interest_signals": [{"artist": name, "plays": count}
                             for name, count in artists.most_common(5) if count >= 2],
    }
