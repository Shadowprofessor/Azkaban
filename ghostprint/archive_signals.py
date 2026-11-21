"""Normalize supported export variants without retaining message or search text."""

import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import PurePosixPath


# Expected basenames are scoped by a platform hint or an identifiable directory.
EXTRA_FORMATS = {
    "Facebook": {
        r"your_posts(?:_\d+)?": ("activity", "Posts"),
        r"search_history(?:_\d+)?": ("activity", "Search history"),
        r"(?:uploaded|synced)_contacts": ("contacts", "Uploaded contacts"),
        r"message_\d+": ("messages", "Message history"),
        r"your_off_facebook_activity": ("sharing", "Off-Meta activity"),
        r"(?:login_activity|logins_and_logouts)": ("security", "Login history"),
    },
    "LinkedIn": {
        r"connections": ("connections", "Connections"),
        r"(?:contacts|importedcontacts)": ("contacts", "Imported contacts"),
        r"positions": ("work", "Profile positions"),
        r"education": ("education", "Profile education"),
        r"messages": ("messages", "Message history"),
    },
    "Twitter/X": {
        r"tweets?(?:-part\d+)?": ("activity", "Posts"),
        r"follower(?:-part\d+)?|following(?:-part\d+)?": ("connections", "Account connections"),
        r"direct-messages(?:-part\d+)?": ("messages", "Message conversations"),
        r"(?:ip-audit|connected-application)(?:-part\d+)?": ("security", "Account access history"),
    },
    "TikTok": {
        r"user_data(?:_tiktok)?|tiktok": ("activity", "Watch history"),
        r"video browsing history|watch_history": ("activity", "Watch history"),
    },
    "Discord": {
        r"messages": ("messages", "Sent messages"),
        r"events(?:-\d+)?": ("activity", "Account events"),
    },
    "Amazon": {
        r"retail\.orderhistory(?:\.\d+)?|orders|order history": ("shopping", "Order history"),
    },
    "YouTube": {
        r"watch-history|myactivity": ("activity", "Watch history"),
        r"search-history": ("activity", "Search history"),
    },
    "Browser History": {
        r"history|browser history|browser_history": ("activity", "Browser history"),
    },
}
MARKERS = {
    "Facebook": ("facebook",), "LinkedIn": ("linkedin",), "Twitter/X": ("twitter",),
    "TikTok": ("tiktok",), "Discord": ("discord", "package"),
    "Amazon": ("amazon", "retail.orderhistory"), "YouTube": ("youtube",),
    "Browser History": ("chrome", "browser history", "browser_history"),
}
KNOWN_PLATFORMS = ("Google", "Instagram", "Spotify", *EXTRA_FORMATS, "Chrome Extension")
ADDITIONAL_FIELDS = {
    "activity": ("searches", "search_history", "activity_log", "entries", "items", "events", "visits",
                 "statuses", "Browser History", "history", "watchHistory", "VideoList"),
    "contacts": ("contacts_v2", "address_book", "uploaded_contacts"),
    "security": ("login_activity_v2", "logins_and_logouts"),
    "shopping": ("orders",), "sharing": ("off_facebook_activity_v2", "off_facebook_activity"),
    "work": ("positions",), "education": ("education",),
}
TOPICS = {
    "Artificial intelligence": r"\b(?:artificial intelligence|machine learning|generative ai|ai podcast|chatgpt|llms?)\b",
    "Software and technology": r"\b(?:programming|software development|python tutorial|web development|coding|computer science)\b",
    "Travel": r"\b(?:travel guide|tourism|vacation|flight booking|road trip|city tour|travel itinerary)\b",
    "Cooking": r"\b(?:cooking|recipes?|baking|meal prep|cookbook)\b",
    "Fitness": r"\b(?:fitness|workout|marathon training|running shoes|strength training)\b",
    "Gaming": r"\b(?:video games?|gaming|esports|gameplay)\b",
    "Music": r"\b(?:music|concerts?|guitar|songwriting|piano)\b",
    "Photography": r"\b(?:photography|camera lens|photo editing|lightroom)\b",
}
TOPIC_PATTERNS = {topic: re.compile(pattern, re.I) for topic, pattern in TOPICS.items()}


def classify_extra(name, hint):
    path = name.replace("\\", "/").lower()
    file = PurePosixPath(path)
    if file.suffix not in {".json", ".csv", ".html", ".js"}:
        return None
    for platform, patterns in EXTRA_FORMATS.items():
        if hint and hint != platform:
            continue
        distinctive = platform == "TikTok" and file.name == "user_data_tiktok.json"
        if not hint and not distinctive and not any(re.search(rf"(?:^|/)({re.escape(marker)})(?:[-_ ./]|$)", path)
                                                    for marker in MARKERS[platform]):
            continue
        if platform == "Discord" and "discord" not in path and not hint and "/messages/" not in f"/{path}" and "/activity/" not in f"/{path}":
            continue
        for pattern, (category, kind) in patterns.items():
            if re.fullmatch(pattern, file.stem):
                return platform, category, kind
    return None


def archive_hint(filename):
    name = filename.lower()
    for platform, prefixes in (
        ("Facebook", ("facebook",)), ("LinkedIn", ("linkedin", "complete_linkedindataexport",
                                                   "basic_linkedindataexport")),
        ("Twitter/X", ("twitter", "x-archive")), ("TikTok", ("tiktok",)),
        ("Discord", ("discord",)), ("Amazon", ("amazon",)), ("Instagram", ("instagram",)),
    ):
        if name.startswith(prefixes):
            return platform
    return None


def product_and_kind(name, platform, category):
    recognized = classify_extra(name, platform)
    if recognized:
        return recognized[0], recognized[2]
    path = name.lower().replace("\\", "/")
    if platform == "Google" and category == "activity":
        if "youtube" in path or "watch-history" in path:
            return "YouTube", "Search history" if "search" in path else "Watch history"
        if "/search/" in f"/{path}" or "search-history" in path:
            return platform, "Search history"
    kinds = {
        "location": "Location records", "contacts": "Contact records", "security": "Session metadata",
        "activity": "Activity history", "messages": "Message history",
        "connections": "Account connections", "interests": "Interest or ad records",
    }
    return platform, "Listening history" if platform == "Spotify" and category == "activity" else kinds[category]


def timestamp(row):
    visit = row.get("placeVisit")
    if isinstance(visit, dict) and isinstance(duration := visit.get("duration"), dict):
        visit_time = duration.get("startTimestamp", duration.get("startTimestampMs"))
        if visit_time is not None:
            row = {**row, "startTime": visit_time}
    for key in ("ts", "time", "endTime", "timestamp", "creation_timestamp", "timestamp_ms", "timestampMs",
                "startTime", "created_at", "time_usec", "Date", "Order Date", "Timestamp", "Visit Time"):
        value = row.get(key)
        if isinstance(value, bool) or value is None:
            continue
        try:
            if isinstance(value, (int, float)) or isinstance(value, str) and value.isdecimal():
                seconds = int(value)
                scale = 1_000_000 if key == "time_usec" else 1000 if abs(seconds) > 10**11 else 1
                moment = datetime.fromtimestamp(seconds / scale, UTC)
            elif isinstance(value, str):
                try:
                    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    if key != "created_at":
                        continue
                    moment = parsedate_to_datetime(value)
                if moment.tzinfo is None and key == "endTime":
                    moment = moment.replace(tzinfo=UTC)
            else:
                continue
            if 1970 <= moment.year <= 2100:
                return moment.astimezone(UTC) if moment.tzinfo else moment
        except (ValueError, OverflowError, OSError):
            continue
    return None


def topic_text(row, category):
    if category not in {"activity", "interests", "shopping"}:
        return ""
    if isinstance(row, str):
        return row[:500] if category == "interests" else ""
    keys = ("title", "trackName", "episodeName", "episodeShowName", "episode_name", "episode_show_name",
            "Product Name", "Product Title", "Title", "query", "topic", "name")
    return " ".join(value[:240] for key in keys if isinstance(value := row.get(key), str))


def evidence_summary(rows, category):
    years = Counter()
    by_year = defaultdict(Counter)
    by_topic = Counter()
    hours = defaultdict(Counter)
    cities = defaultdict(Counter)
    flags = Counter()
    for row in rows:
        moment = timestamp(row) if isinstance(row, dict) else None
        if moment:
            years[str(moment.year)] += 1
            if moment.tzinfo and category == "activity":
                hours[str(moment.year)][str(moment.hour)] += 1
        label = topic_text(row, category)
        for topic, pattern in TOPIC_PATTERNS.items():
            if label and pattern.search(label):
                by_topic[topic] += 1
                if moment:
                    by_year[str(moment.year)][topic] += 1
        if not isinstance(row, dict):
            continue
        if category == "security":
            keys = {"device", "device_name", "platform", "user_agent", "User Agent", "Device"}
            inner = row.get("string_map_data")
            if keys & row.keys() or isinstance(inner, dict) and keys & inner.keys():
                flags["device_fields"] += 1
        if category != "location":
            continue
        visit = row.get("placeVisit")
        location = visit.get("location") if isinstance(visit, dict) else None
        place = location if isinstance(location, dict) else row
        lat, lng = place.get("latitudeE7"), place.get("longitudeE7")
        precise = type(lat) is int and type(lng) is int and abs(lat) <= 900_000_000 and abs(lng) <= 1_800_000_000
        if precise:
            flags["precise_coordinates"] += 1
        if isinstance(visit, dict):
            city = place.get("city")
            if isinstance(city, str) and 1 < len(city) <= 48 and all(char.isalpha() or char in " -'." for char in city):
                bucket = str(moment.year) if moment else "undated"
                if len(cities[bucket]) < 40 or city in cities[bucket]:
                    cities[bucket][city] += 1
        for key in ("semanticType", "placeLabel", "semanticLocationType"):
            place_label = place.get(key)
            if isinstance(place_label, str) and place_label.lower() in {"home", "work", "workplace"}:
                label = "home" if place_label.lower() == "home" else "work"
                flags[f"{label}_label"] += 1
                if precise:
                    flags[f"{label}_with_coordinates"] += 1
                break
    return {
        "years": dict(years), "topics": dict(by_topic), "topics_by_year": dict(by_year),
        "hours_by_year": dict(hours), "cities_by_year": dict(cities), "flags": dict(flags),
    }
