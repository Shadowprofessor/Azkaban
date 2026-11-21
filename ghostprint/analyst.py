"""Answer personal questions from locally retrieved aggregate evidence."""

import re
from math import log10
from collections import Counter, defaultdict

from .archive_signals import KNOWN_PLATFORMS, TOPIC_PATTERNS
from .retrieval import retrieve


PLATFORM_NAMES = {platform: (platform.lower(),) for platform in KNOWN_PLATFORMS}
PLATFORM_NAMES.update({
    "Google": ("google", "takeout"), "Twitter/X": ("twitter", "twitter/x", "x"),
    "Chrome Extension": ("chrome extension", "browser companion", "live browsing"),
})
CATEGORIES = {
    "location": r"location|gps|coordinates?|whereabouts|travel|cities|city|home address|workplace",
    "contacts": r"contacts?|address book|phonebook",
    "security": r"devices?|sessions?|logins?|ip address",
    "messages": r"messages?|chats?|dms?",
    "activity": r"search(?:es)?|watch(?:ed)?|listen(?:ing|ed)?|activity|browsing|routines?",
    "interests": r"interests?|hobbies|ad topics|ad categories",
    "connections": r"followers?|connections?|following",
    "sharing": r"third.party|off.platform|sharing",
    "shopping": r"shopping|purchases?|orders?|spending",
    "work": r"occupation|employment|profession|job|work history",
    "education": r"education|degree|school|university",
    "permissions": r"permissions?",
    "identity": r"government|passport|national id|social security|birth date|identity",
    "financial": r"financial|credit card|bank account|payment",
}
LABELS = {
    "location": "location", "contacts": "contacts", "security": "device or session",
    "messages": "message", "activity": "activity", "interests": "interest or ad",
    "connections": "account connection", "sharing": "off-platform activity", "shopping": "purchase",
    "work": "employment profile", "education": "education profile",
    "permissions": "granted site permission",
    "identity": "identity", "financial": "financial account",
}
RISKS = {
    "location": ("Medium", "Location indicators can reveal the places or regions associated with your activity."),
    "contacts": ("High", "Contact exports can expose other people's details as well as your relationships."),
    "security": ("Medium", "Account access metadata can help link sessions and devices."),
    "messages": ("High", "Message records can contain private communications involving multiple people."),
    "activity": ("Medium", "Activity logs can reveal routines and make your behavior easier to profile."),
    "interests": ("Medium", "Repeated topics or saved ad categories can inform behavioral targeting."),
    "connections": ("Medium", "Connection lists expose parts of your social graph."),
    "sharing": ("High", "Off-platform records can associate actions from other services with an account."),
    "shopping": ("Medium", "Purchases can reveal preferences and changes in spending behavior."),
    "work": ("Medium", "Employment records can connect professional and personal identities."),
    "education": ("Medium", "Education records can make a profile easier to identify or correlate."),
    "permissions": ("High", "A site with a granted sensor permission can access that sensor subject to browser controls."),
    "identity": ("High", "Government identifiers and birth dates can make records easier to link and misuse."),
    "financial": ("High", "Financial account identifiers can expose details that should be shared only when necessary."),
}
RISK_ORDER = {"Unknown": 0, "Low": 1, "Medium": 2, "High": 3, "Critical": 4}
SCORE_BASE = {"Low": 20, "Medium": 45, "High": 70, "Critical": 95}
BENEFIT = {"permissions": 92, "location": 90, "contacts": 80, "sharing": 78, "messages": 75,
           "security": 70, "activity": 57, "shopping": 52, "connections": 48, "interests": 45,
           "work": 38, "education": 36, "identity": 84, "financial": 86}
GENERIC_ACTIONS = {
    "location": ("Review stored location history", ["Review the service's location history and retention controls.",
                 "Remove location records you no longer need and review app location permissions."]),
    "contacts": ("Remove unnecessary contact data", ["Review imported contact and sync controls.",
                 "Remove unnecessary contacts and turn off continuous upload where available."]),
    "messages": ("Review retained conversations", ["Review sensitive conversations in the service.",
                 "Use its deletion controls where available and consider copies held by recipients."]),
    "activity": ("Limit activity history", ["Review saved activity and delete entries you no longer need.",
                 "Check whether the service offers history controls or automatic deletion."]),
    "security": ("Review devices and app access", ["Review active sessions and connected apps.",
                 "Sign out of unfamiliar sessions and revoke access that is no longer needed."]),
    "interests": ("Review profiling settings", ["Check whether the platform shows inferred interests or ad categories.",
                  "Reduce ad personalization or clear selected interests where available."]),
    "connections": ("Limit connection visibility", ["Review who can see your followers and connections."]),
    "sharing": ("Review off-platform activity settings", ["Open the service's privacy controls.",
                "Review its off-platform activity controls and disconnect linked activity where offered."]),
    "shopping": ("Review purchase visibility and preferences", ["Look for order or shopping visibility controls.",
                 "Review ads personalization and remove stored delivery details you no longer need."]),
    "work": ("Reduce public employment details", ["Review the public visibility of employment entries.",
             "Remove entries or fields you do not need to share."]),
    "education": ("Reduce public education details", ["Review the public visibility of education entries.",
                  "Remove fields you do not need to share."]),
    "permissions": ("Revoke unnecessary site permissions", ["Open the site's page information and review its permissions.",
                    "Block or reset access to sensors you do not want the site to use."]),
    "identity": ("Limit access to identity details", ["Redact identity identifiers from copies that do not need them.",
                 "Review who can access the originals and how long they are kept."]),
    "financial": ("Limit access to financial identifiers", ["Remove unnecessary financial identifiers from shared copies.",
                  "Review access to the original record and retain only the fields needed."]),
}
PERSONAL = re.compile(r"\b(?:me|my|mine|i am|am i|i did|did i|was i|have i|i visit|i watch|i listen|personal archive)\b", re.I)
ANALYSIS = re.compile(
    r"\b(?:know|collected|collects?|location|contacts?|history|profile|advertisers?|brokers?|infer|habits?|"
    r"interests?|interested|hobbies|occupation|education|stores?|stored|data|sleep|income|age|cities|visit|risks?|"
    r"permissions?|sharing|overcollection|prioritize|prioritise|timeline|behavior|behaviour|workplace|home address)\b",
    re.I,
)
PUBLIC_ACTION = re.compile(
    r"^\s*(?:how\b|where\b|can i)\s+.*\b(?:delete|clear|block|change|remove|revoke|turn off|disable|"
    r"download|stop|protect|manage|limit|export|reset|restrict|opt out)\b",
    re.I,
)
PROFILE = re.compile(r"\b(?:profile|advertisers?|brokers?|demographics|income|age|lifestyle)\b", re.I)
INTEREST = re.compile(r"\b(?:interested|interests?|hobbies|ad categories|correlat\w*|cross.platform|artificial intelligence|machine learning)\b", re.I)
PERIOD = re.compile(r"\b(?:19[7-9]\d|20\d\d|2100)\b")
PLAN = re.compile(r"\b(?:prioriti[sz]\w*|action plan|fix first|delete first|lock down first|highest risk|risks?)\b", re.I)
IDENTITY = re.compile(r"\b(?:my (?:age|income|name|birthday|birth date|nationality|gender)|how old am i)\b", re.I)


def is_personal_question(prompt):
    if re.search(r"\b(?:data broker|privacy footprint|cross.platform|risk assessment|excessive permissions)\b", prompt, re.I):
        return True
    inventory = re.search(r"\b(?:what|which)\b.*\b(?:knows?|collected|collects?|has my|have my|holds? my)\b", prompt, re.I)
    return not PUBLIC_ACTION.search(prompt) and bool(
        inventory or PLAN.search(prompt) and PERSONAL.search(prompt)
        or IDENTITY.search(prompt) or PERSONAL.search(prompt) and ANALYSIS.search(prompt)
        or re.search(r"\b(?:how old am i|what do i do|which cities did i visit|where do i live|about me|"
                     r"what should i (?:delete|remove|lock down|fix) first)\b", prompt, re.I)
    )


def selected_platforms(prompt):
    return {platform for platform, names in PLATFORM_NAMES.items()
            if any(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", prompt, re.I) for name in names)}


def source_facts(rows):
    grouped = defaultdict(list)
    for row, fact in rows:
        grouped[(row["platform"], row["kind"], fact)].append(row["id"])
    facts = []
    for (platform, kind, fact), ids in grouped.items():
        citation = ", ".join(dict.fromkeys(ids[:3]))
        suffix = f" and {len(ids) - 3} more files" if len(ids) > 3 else ""
        facts.append({"source": f"{platform} · {kind} · {citation}{suffix}", "fact": fact})
    return facts


def evidence_counts(rows, values, unit):
    groups = defaultdict(list)
    for row, count in zip(rows, values):
        if count:
            groups[(row["platform"], row["kind"])].append((row, count))
    return source_facts([
        (row, f"{sum(n for _, n in group):,} {unit}.")
        for group in groups.values() for row, _ in group
    ])


def risk_for(category, flags):
    if flags["home_with_coordinates"] or flags["work_with_coordinates"]:
        return "Critical", "The export contains precise coordinates associated with a home or work label. It could expose a sensitive place."
    if flags["precise_coordinates"]:
        return "High", "Precise coordinates can reveal recurring places and travel patterns."
    return RISKS[category]


def claim(text, evidence, level, basis, category, platform, flags=None, *, records, reported=False):
    risk, why = risk_for(category, flags or Counter())
    if reported:
        if RISK_ORDER[risk] > RISK_ORDER["Medium"]:
            risk = "Medium"
        why = "The stated concern warrants verification. " + why
    return {
        "claim": text, "evidence": evidence, "confidence": {"level": level, "basis": basis},
        "risk": {"level": risk, "why": why}, "category": category, "platform": platform,
        "reported": reported,
        "score": min(100, SCORE_BASE[risk] + min(14, int(5 * log10(records + 1)))),
    }


def action_for(item):
    platform, category = item["platform"], item["category"]
    title, steps = GENERIC_ACTIONS[category]
    guides = retrieve(category, platform="Google" if platform == "YouTube" else platform, category=category, k=1)
    guide = guides[0] if guides and platform else None
    steps = guide["steps"] if guide else steps
    if item["reported"] and platform == "Uploaded reports" and category == "security":
        if any("Credentials or session tokens" in signal for signal in item["signals"]):
            title = "Review potential credential exposure"
            steps = ["Restrict access to the affected records. Revoke or rotate credentials confirmed to be exposed."]
        else:
            title = "Limit access to network and device identifiers"
            steps = ["Restrict access to the records. Remove or mask identifiers that are not needed."]
    if item["reported"]:
        steps = ["Check the reported issue against the original records or current settings."] + steps
    return {"title": f"{platform} · {guide['title'] if guide else title}" if platform else title,
            "reason": item["risk"]["why"], "impact": item["risk"]["level"],
            "difficulty": "Medium" if category in {"messages", "location", "contacts", "shopping"} else "Low",
            "steps": steps, "url": guide["url"] if guide else None}


def count_in(row, year):
    return row.get("years", {}).get(year, 0) if year else row["count"]


def discovery(rows, year, *, qualifier=""):
    claims = []
    groups = defaultdict(list)
    for row in rows:
        groups[row["platform"], row["category"], row.get("origin")].append(row)
    for (platform, category, origin), group in groups.items():
        if qualifier:
            count = sum(row.get("flags", {}).get(qualifier, 0) for row in group)
            if not count:
                continue
            values = [row.get("flags", {}).get(qualifier, 0) for row in group]
        else:
            values = [count_in(row, year) for row in group]
            count = sum(values)
        if not count:
            continue
        flags = Counter()
        if not year:
            for row in group:
                flags.update(row.get("flags", {}))
        if qualifier in {"home_label", "work_label"}:
            flag = qualifier.replace("_label", "_with_coordinates")
            flags = Counter({flag: flags[flag]})
        if qualifier:
            field = "device or client field" if qualifier == "device_fields" else f"explicit {qualifier.split('_')[0]} label"
            text = f"{platform} has {count:,} records with a {field}."
        else:
            text = f"{platform} has {count:,} {LABELS[category]} records in the available data"
            text += f" for {year}." if year else "."
        signals = sorted({row["signal"] for row, value in zip(group, values) if value and row.get("signal")})
        if origin == "reported":
            subject = "; ".join(signals).lower() or LABELS[category]
            text = f"The uploaded reports flag {subject} in {count:,} finding{'s' if count != 1 else ''}."
        elif origin == "observed":
            text = f"The uploaded files contain {count:,} records with {LABELS[category]} fields."
        elif category == "permissions":
            text = f"{count:,} checked site-and-permission combination{'s' if count != 1 else ''} had a granted permission."
        if signals and origin != "reported":
            text += " Observed fields include " + "; ".join(signal.lower() for signal in signals) + "."
        if not year and not qualifier and flags["precise_coordinates"]:
            text += f" Precise coordinate fields are present in {flags['precise_coordinates']:,} records."
        evidence = evidence_counts(group, values, "matching records")
        if origin != "reported":
            evidence += source_facts([(row, f"Observed fields: {row['signal']}.")
                                      for row, value in zip(group, values) if value and row.get("signal")])
        else:
            evidence += source_facts([(row, f"Reported concern: {row['signal']}.")
                                      for row, value in zip(group, values) if value and row.get("signal")])
        for flag, label in (
            ("precise_coordinates", "rows with precise coordinate fields"),
            ("home_with_coordinates", "coordinate rows labeled home"),
            ("work_with_coordinates", "coordinate rows labeled work"),
        ):
            if flags[flag]:
                evidence += evidence_counts(group, [row.get("flags", {}).get(flag, 0) for row in group], label)
        basis = ("The wording appears in the uploaded report. The underlying real-world claim is unverified."
                 if origin == "reported" else "The counted record type or field appears in the available data.")
        item = claim(text, evidence, "Medium" if origin == "reported" else "High",
                     basis, category, platform, flags, records=count, reported=origin == "reported")
        if origin == "reported":
            item["signals"] = signals
        claims.append(item)
    return claims


def topics(rows, year, prompt):
    groups = defaultdict(list)
    for row in rows:
        counts = row.get("topics_by_year", {}).get(year, {}) if year else row.get("topics", {})
        for topic, count in counts.items():
            groups[topic].append((row, count))
    requested = {topic for topic, pattern in TOPIC_PATTERNS.items()
                 if topic.lower() in prompt or pattern.search(prompt)}
    if requested:
        groups = {topic: rows for topic, rows in groups.items() if topic in requested}
    claims = []
    for topic, matches in sorted(groups.items(), key=lambda item: -sum(count for _, count in item[1]))[:5]:
        platforms = {row["platform"] for row, _ in matches}
        total = sum(count for _, count in matches)
        scope = f" in {year}" if year else ""
        if len(platforms) > 1:
            text = f"The available data suggests interest in {topic.lower()}{scope}, with signals across {len(platforms)} services or products."
        elif total > 1:
            text = f"The available data suggests a possible interest in {topic.lower()}{scope}."
        else:
            text = f"One record mentions {topic.lower()}{scope}. This is a weak interest signal."
        item = claim(text, evidence_counts([row for row, _ in matches], [count for _, count in matches],
                                          "records matching this topic"),
                     "Medium" if total >= 2 else "Low",
                     "Matched activity or interest labels. They may reflect incidental or shared-account activity.",
                     "interests", None if len(platforms) > 1 else next(iter(platforms)), records=total)
        claims.append({**item, "topic": topic})
    return claims


def city_claims(rows, year):
    claims = []
    for row in rows:
        counts = Counter()
        for bucket, cities in row.get("cities_by_year", {}).items():
            if not year or year == bucket:
                counts.update(cities)
        if not counts:
            continue
        names = ", ".join(name for name, _ in counts.most_common(5))
        text = f"{row['platform']} has visit records labeled with these cities: {names}."
        evidence = source_facts([(row, f"{sum(counts.values()):,} explicitly city-labeled visit records. Labels include {names}.")])
        claims.append(claim(text, evidence,
                            "Medium", "The export labels these as visits. Labels and inferred visits can be inaccurate.",
                            "location", row["platform"], records=sum(counts.values())))
    return claims


def activity_claims(rows, year, compare):
    claims = []
    for platform in sorted({row["platform"] for row in rows}):
        group = [row for row in rows if row["platform"] == platform and row["category"] == "activity"]
        years = Counter()
        hours = Counter()
        used = []
        for row in group:
            selected = {key: count for key, count in row.get("years", {}).items() if not year or key == year}
            if selected:
                years.update(selected)
                used.append((row, sum(selected.values())))
            for key, counts in row.get("hours_by_year", {}).items():
                if not year or key == year:
                    hours.update(counts)
        if compare and len(years) >= 2:
            breakdown = ", ".join(f"{key}: {years[key]:,}" for key in sorted(years)[-5:])
            text = f"{platform} has the following activity counts by year: {breakdown}."
            basis = "Counts describe dated records. Changes can reflect export coverage or actual activity."
            evidence = source_facts([(row, "Dated records: " + ", ".join(
                f"{key}: {value:,}" for key, value in sorted(row["years"].items())[-5:]
            ) + ".") for row, _ in used])
        elif not compare and hours:
            hour, count = max(hours.items(), key=lambda item: (item[1], -int(item[0])))
            text = f"{platform} has the most recorded activity in the {int(hour):02d}:00–{int(hour):02d}:59 UTC hour ({count:,} records)."
            basis = "Computed from timezone-aware activity timestamps. This cannot establish a sleep schedule."
            used = [(row, sum(sum(group.values()) for key, group in row.get("hours_by_year", {}).items()
                              if not year or key == year)) for row in group]
            evidence = evidence_counts([row for row, _ in used], [count for _, count in used], "timezone-aware activity records")
            evidence += evidence_counts(group, [sum(counts.get(hour, 0) for key, counts in row.get("hours_by_year", {}).items()
                                                    if not year or key == year) for row in group], f"records in the {int(hour):02d}:00 UTC hour")
        else:
            continue
        claims.append(claim(text, evidence, "High", basis, "activity", platform,
                            records=sum(count for _, count in used)))
    return claims


def profile_summary(claims, broker):
    by_category = defaultdict(list)
    for item in claims:
        by_category[item["category"]].append(item)
    interests = ", ".join(item["topic"] for item in by_category["interests"] if item.get("topic"))
    interest_level = "Medium" if interests and all(item["confidence"]["level"] == "Medium" for item in by_category["interests"]) else "Low"
    fields = [
        {"field": "Demographics", "value": "Undetermined", "confidence": "Low"},
        {"field": "Interests", "value": interests or "Undetermined", "confidence": interest_level},
        {"field": "Behavior patterns", "value": "Activity timing signals found" if by_category["activity"] else "Undetermined",
         "confidence": "Medium" if by_category["activity"] else "Low"},
    ]
    if not broker:
        fields.append({"field": "Possible ad categories", "value": interests or "Undetermined", "confidence": interest_level})
        return fields
    fields += [
        {"field": "Age range", "value": "Undetermined", "confidence": "Low"},
        {"field": "Income range", "value": "Undetermined", "confidence": "Low"},
        {"field": "Occupation", "value": "Profile entries available. Current occupation undetermined."
         if by_category["work"] else "Undetermined", "confidence": "Low"},
        {"field": "Education", "value": "Profile entries available. Education level undetermined."
         if by_category["education"] else "Undetermined", "confidence": "Low"},
        {"field": "Lifestyle", "value": "Undetermined beyond the activity or interest signals above.", "confidence": "Low"},
        {"field": "Shopping preferences", "value": "Purchase records available. Preferences undetermined."
         if by_category["shopping"] else "Undetermined", "confidence": "Low"},
    ]
    return fields


def analyze(prompt, report, live_sites=(), live_permissions=None, *, automatic=False):
    """Compose a cited assessment. This path has no external search or model calls."""
    prompt = prompt.lower()
    years = set(PERIOD.findall(prompt))
    year = next(iter(years)) if len(years) == 1 else None
    requested = selected_platforms(prompt)
    eligible = requested | ({"YouTube"} if "Google" in requested else set())
    index = list(report.get("analyst_sources", ()))
    if live_sites and not years:
        index.append({"id": "Current paired session", "platform": "Chrome Extension", "kind": "Foreground website events",
                      "category": "activity", "count": sum(site["visits"] for site in live_sites)})
    if live_permissions and not years:
        granted = {name: n for name, n in live_permissions.items() if n}
        if granted:
            index.append({"id": "Explicit site checks in the current session", "platform": "Chrome Extension",
                          "kind": "Site permission checks", "category": "permissions",
                          "count": sum(granted.values()),
                          "signal": ", ".join(f"{name} ({n})" for name, n in sorted(granted.items()))})
    rows = [row for row in index if not eligible or row["platform"] in eligible]
    categories = {key for key, pattern in CATEGORIES.items() if re.search(rf"\b(?:{pattern})\b", prompt)}
    selected = [row for row in rows if not categories or row["category"] in categories]
    for word, kind in (("search", "Search history"), ("watch", "Watch history"), ("listen", "Listening history")):
        if re.search(rf"\b{word}(?:es|ed|ing)?\s+(?:history|habits)\b", prompt):
            selected = [row for row in selected if row["kind"] == kind]
            break
    limitations = []
    profile = bool(PROFILE.search(prompt))
    profile_view = bool(re.search(r"\b(?:advertisers?|brokers?|profile me|profile view)\b", prompt))
    broker = bool(re.search(r"\bbrokers?\b", prompt))
    sleep_question = bool(re.search(r"\bsleep\b", prompt))
    plan = bool(PLAN.search(prompt))
    specific_target = re.search(r"\bwhat (?:does|did) (.+?) (?:know|collect|store)\b", prompt)

    if automatic:
        claims = discovery(rows, None)
        limitations.append("The review covers supported records in this import. Missing or unrecognized records are outside its scope.")
    elif not requested and specific_target:
        claims = []
        limitations.append("No supported archive was matched to the named service.")
    elif not profile_view and (IDENTITY.search(prompt) or re.search(r"\bdemographics\b", prompt)):
        claims = []
        limitations.append("The retrieved data does not support the requested identity or demographic inference.")
    elif len(years) > 1:
        rows = [{**row, "years": {k: v for k, v in row.get("years", {}).items() if k in years}}
                for row in rows]
        claims = activity_claims(rows, None, True)
    elif re.search(r"\b(?:cities|which city)\b", prompt):
        claims = city_claims(selected, year)
        limitations.append("City names require explicit visit labels. Coordinate records and streaming countries cannot establish a city visit.")
    elif re.search(r"\b(?:home address|where do i live|workplace|work address)\b", prompt):
        qualifier = "work_label" if re.search(r"workplace|work address", prompt) else "home_label"
        claims = discovery([row for row in rows if row["category"] == "location"], year, qualifier=qualifier) if not year else []
        limitations.append("Exact addresses are withheld. Unlabeled coordinate records do not establish home or workplace.")
    elif re.search(r"\bdevices?\b", prompt):
        claims = discovery([row for row in rows if row["category"] == "security"], None,
                           qualifier="device_fields") if not year else []
        limitations.append("An IP address or login event alone does not identify a specific device.")
    elif re.search(r"\b(?:sleep|routine|routines|activity patterns?|behavior patterns?|behaviour patterns?|over time|changed)\b", prompt):
        claims = activity_claims(rows, year, bool(re.search(r"over time|changed", prompt)))
        limitations.append("Recorded activity covers the supplied exports. It cannot establish sleep, inactivity, or behavior outside that coverage.")
    elif profile or INTEREST.search(prompt):
        topic_rows = [row for row in rows if row["category"] == "shopping"] if "shopping" in categories else rows
        claims = topics(topic_rows, year, prompt)
        if profile:
            claims += activity_claims(rows, year, False)[:2]
            if re.search(r"\b(?:broker|brokers|occupation|education)\b", prompt):
                claims += discovery([row for row in rows if row["category"] in {"work", "education", "shopping"}], year)
            limitations.append("Age, income, and demographics are undetermined. Profile records do not establish current occupation or education level.")
            limitations.append("The topic labels are possible profiling signals. They do not establish actual advertiser targeting or broker access.")
    elif categories or requested or plan or is_personal_question(prompt) or not prompt:
        claims = discovery(selected, year)
        if not plan and categories & {"work", "education"}:
            limitations.append("Profile entries do not establish your current occupation or education level.")
        if "sharing" in categories or re.search(r"\bovercollection\b", prompt):
            limitations.append("The exports do not by themselves establish transfer recipients, consent, necessity, or overcollection.")
        if "permissions" in prompt and not claims:
            limitations.append("Visit history cannot show permissions. Use the browser companion's site check to inspect the current site's grants.")
        elif "permissions" in categories:
            limitations.append("A granted permission does not establish that a site used it or that access was excessive.")
    else:
        claims = []

    missing = requested - {row["platform"] for row in rows}
    if "Google" in missing and any(row["platform"] == "YouTube" for row in rows):
        missing.remove("Google")
    if missing:
        limitations.append("No supported records were available for " + ", ".join(sorted(missing)) + ".")
    if year:
        limitations.append(f"This answer uses dated records from {year}. Undated records are excluded.")
    if report.get("analyst_limited"):
        limitations.append("The source limit was reached. Some imported files were excluded from analysis.")
    if not claims:
        return {
            "answer": "There were no supported records to score in this import." if automatic else
                      "The available evidence is insufficient to answer that question.",
            "claims": [], "confidence": {"level": "Low", "basis": "No supported evidence matched the requested inference."},
            "risk": {"level": "Unknown", "why": "The available records do not establish the requested exposure."},
            "score": None,
            "actions": [], "profile": profile_summary([], broker) if profile_view else [],
            "limitations": limitations or ["Import a relevant archive or narrow the question to a supported data type."],
        }
    claims.sort(key=lambda i: (-RISK_ORDER[i["risk"]["level"]], -i["score"], -BENEFIT[i["category"]], i["platform"] or ""))
    score = max(item["score"] for item in claims)
    if not automatic:
        claims = claims[:12]
    actions = {}
    for item in claims:
        key = item["platform"], item["category"], item["reported"]
        if key not in actions:
            actions[key] = action_for(item)
        item["recommendation"] = actions[key]["title"]
        if automatic:
            item["fix"] = actions[key]
    level = min((item["confidence"]["level"] for item in claims), key=("Low", "Medium", "High").index)
    headline = claims[0]["claim"]
    if plan:
        headline = f"Start with {claims[0]['recommendation']}."
    elif automatic:
        noun = "finding" if len(claims) == 1 else "findings"
        headline = f"{len(claims)} {noun} from the uploaded files, highest priority first."
    elif len(categories) == 1 and categories & {"location", "contacts"} and len(claims) > 1:
        services = ", ".join(sorted({item["platform"] for item in claims if item["platform"]}))
        headline = f"The supplied evidence contains {LABELS[next(iter(categories))]} records from {services}."
    elif len(claims) > 1 and not (profile or INTEREST.search(prompt)):
        headline += f" See {len(claims) - 1} additional findings below."
    if sleep_question:
        headline = "The available timestamps show activity patterns, but there is insufficient evidence to infer when you sleep."
    if profile_view:
        headline = "The available data supports some profiling signals. Age, income, and other unsupported demographics remain undetermined."
    return {
        "answer": headline, "claims": claims,
        "confidence": {"level": level, "basis": "Overall confidence reflects the weakest reported finding."},
        "risk": claims[0]["risk"], "actions": list(actions.values())[:5], "limitations": limitations,
        "profile": profile_summary(claims, broker) if profile_view else [],
        "score": score,
        **({"insights": topics(rows, None, "") + activity_claims(rows, None, False)} if automatic else {}),
    }
