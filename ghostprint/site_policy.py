"""Compare public website statements with narrow, local browser evidence."""

import re
from datetime import UTC, datetime
from time import monotonic
from urllib.parse import urljoin, urlsplit

from .analyst import SCORE_BASE
from .public_pages import HOSTNAME, POLICY_PATH, PageUnavailable, PolicyPage, doc_kind, download_page, public_url


DATA_TYPES = {
    "email": ("Email addresses", r"e[- ]?mail(?: addresses?)?"),
    "phone": ("Phone numbers", r"(?:telephone|phone|mobile) numbers?"),
    "name": ("Names", r"(?:full|first|last|your) names?"),
    "address": ("Postal addresses", r"(?:postal|mailing|shipping|billing|physical|street) addresses?"),
    "payment": ("Payment details", r"(?:credit|debit|payment) card(?: details| numbers?| information)?|payment (?:details|information)"),
    "credentials": ("Account credentials", r"passwords?|login credentials?|session tokens?"),
    "location": ("Location data", r"(?:precise|approximate|geographic) location|geolocation|location (?:data|information)|gps"),
    "identifiers": ("Device or advertising identifiers", r"(?:device|advertising|mobile) (?:ids?|identifiers?)|unique identifiers?"),
    "ip": ("IP addresses", r"ip addresses?"),
    "activity": ("Browsing or search activity", r"(?:browsing|search|chat|watch) history|search queries|browsing activity"),
    "cookies": ("Cookies or tracking pixels", r"cookies?|tracking pixels?|web beacons?"),
    "storage": ("Browser storage", r"local storage|session storage|browser storage|localStorage|sessionStorage"),
    "personal": ("Personal information", r"personal (?:data|information)"),
}
PATTERNS = {kind: re.compile(rf"\b(?:{pattern})\b", re.I) for kind, (_, pattern) in DATA_TYPES.items()}
BROWSER_TYPES = set(DATA_TYPES) - {"storage", "personal", "cookies"}
PERMISSIONS = {"camera", "microphone", "geolocation", "notifications"}
ACTIONS = {
    "collect": re.compile(r"\b(?:collect(?:s|ed|ing)?|receiv(?:e|es|ed|ing)|obtain(?:s|ed)?|ask for|provid(?:e|es|ed))\b", re.I),
    "store": re.compile(r"\b(?:stor(?:e|es|ed|ing)|sav(?:e|es|ed|ing)|retain(?:s|ed|ing)?|keep(?:s|ing)?|retention)\b", re.I),
    "share": re.compile(r"\b(?:shar(?:e|es|ed|ing)|disclos(?:e|es|ed|ing)|transfer(?:s|red|ring)?)\b", re.I),
    "sell": re.compile(r"\b(?:sell(?:s|ing)?|sold|sale of)\b", re.I),
    "use": re.compile(r"\b(?:use|uses|used|using|process(?:es|ed|ing)?)\b", re.I),
}
DENIAL = re.compile(r"\bwe\s+(?:do not|don['’]t|never|will not|won['’]t|shall not)\b", re.I)
QUALIFIER = re.compile(r"\b(?:unless|except|subject to|however|where necessary|when|if|while|"
                       r"with your consent|without your consent|in certain cases|by default|for this purpose|"
                       r"with advertisers|for advertising)\b", re.I)
SCOPE = re.compile(r"\b(?:we|our|us|you provide|this (?:website|service)|personal information)\b", re.I)
RETENTION = re.compile(r"\b(?:retention|how long|as long as necessary|until you delete|for \d+ (?:days?|months?|years?))\b", re.I)
VERB_CHAIN = re.compile(r"^[\s,]*(?:(?:and|or|may|can|will|only)\s+)*$", re.I)


def validate_observation(value):
    if not isinstance(value, dict) or set(value) != {"forms", "requests", "hosts", "storage"}:
        raise ValueError("Expected a browser privacy snapshot.")
    forms, requests, hosts, storage = (value[key] for key in ("forms", "requests", "hosts", "storage"))
    if (not isinstance(forms, list) or len(forms) > len(BROWSER_TYPES)
            or any(not isinstance(kind, str) or kind not in BROWSER_TYPES for kind in forms)):
        raise ValueError("Invalid form field categories.")
    if (not isinstance(hosts, list) or len(hosts) > 20
            or any(not isinstance(host, str) or len(host) > 253 or not HOSTNAME.fullmatch(host) for host in hosts)):
        raise ValueError("Invalid resource hostnames.")
    if not isinstance(requests, list) or len(requests) > 24:
        raise ValueError("Invalid request observations.")
    for item in requests:
        if (not isinstance(item, dict) or set(item) != {"host", "category", "count"}
                or not isinstance(item["host"], str) or len(item["host"]) > 253 or not HOSTNAME.fullmatch(item["host"])
                or not isinstance(item["category"], str) or item["category"] not in BROWSER_TYPES
                or type(item["count"]) is not int or not 1 <= item["count"] <= 500):
            raise ValueError("Invalid request observation.")
    if (not isinstance(storage, dict) or set(storage) != {"local", "session"}
            or any(count is not None and (type(count) is not int or not 0 <= count <= 100_000)
                   for count in storage.values())):
        raise ValueError("Invalid browser storage counts.")
    return {
        "forms": sorted(set(forms)), "hosts": sorted({host.lower() for host in hosts}),
        "requests": [{**item, "host": item["host"].lower()} for item in requests],
        "storage": storage.copy(), "seen": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def excerpt(text, category=None):
    words = text.split()
    if len(words) <= 26:
        return text
    matched = PATTERNS[category].search(text) if category else None
    offset = max(0, len(text[:matched.start()].split()) - 13) if matched else 0
    return ("…" if offset else "") + " ".join(words[offset:offset + 26]) + ("…" if offset + 26 < len(words) else "")


def actions_for(sentence, category_pattern, heading):
    verbs = sorted((match.start(), match.end(), action)
                   for action, pattern in ACTIONS.items() for match in pattern.finditer(sentence))
    found = set()
    for field in category_pattern.finditer(sentence):
        preceding = [item for item in verbs if item[1] <= field.start()]
        if not preceding:
            continue
        start, _, action = preceding.pop()
        found.add(action)
        for earlier, stop, previous in reversed(preceding):
            if not VERB_CHAIN.fullmatch(sentence[stop:start]):
                break
            found.add(previous)
            start = earlier
    if not verbs and heading:
        found.add(heading)
    return sorted(found)


def extract_statements(page, kind):
    statements = []
    retention = []
    heading = None
    seen = set()
    for index, (is_heading, block) in enumerate(page.blocks[:2500]):
        if is_heading:
            heading = next((action for action, pattern in ACTIONS.items() if pattern.search(block)), None)
        following = page.blocks[index + 1][1] if index + 1 < len(page.blocks) else ""
        neighboring_exception = re.match(r"^(?:however|except|unless|in certain cases)\b", following, re.I)
        if RETENTION.search(block) and SCOPE.search(block) and len(retention) < 4:
            retention.append({"quote": excerpt(block), "source": page.url, "document": kind})
        for sentence in re.split(r"(?<=[.!?])\s+|;\s+|,\s+(?=but\b|however\b)|\s+and\s+(?=we\s)", block):
            negation = DENIAL.search(sentence)
            conditional = bool(QUALIFIER.search(sentence) or neighboring_exception)
            if not (SCOPE.search(sentence) or heading or negation):
                continue
            for category, pattern in PATTERNS.items():
                if not pattern.search(sentence):
                    continue
                for verb in actions_for(sentence, pattern, None if is_heading else heading):
                    stance = "disclosed"
                    if negation:
                        after_denial = sentence[negation.end():]
                        # Limit contradiction checks to direct, unqualified first-person denials.
                        direct = re.match(r"^\s*(?:(?:ever|knowingly)\s+)?", after_denial)
                        tail = after_denial[direct.end():]
                        match = ACTIONS[verb].match(tail)
                        if not match:
                            # Handle coordinated denials such as "we never sell or share email addresses."
                            match = re.match(r"^[a-z]+\s+(?:or|and)\s+", tail, re.I)
                            match = ACTIONS[verb].match(tail[match.end():]) if match else None
                        if not match:
                            continue
                        stance = "qualified_denial" if conditional else "denied"
                    elif conditional:
                        stance = "qualified"
                    key = category, verb, stance, sentence
                    if key not in seen and len(statements) < 90:
                        seen.add(key)
                        statements.append({"category": category, "data": DATA_TYPES[category][0],
                                           "action": verb, "stance": stance, "quote": excerpt(sentence, category),
                                           "document": kind, "source": page.url})
    return statements, retention


def same_host(site, other):
    return site.removeprefix("www.") == other.removeprefix("www.")


def preferred_links(urls, home, *, supplied):
    unique = list(dict.fromkeys(urls))
    pinned = unique[:1] if supplied else []
    remaining = unique[len(pinned):]
    remaining.sort(key=lambda url: (not same_host(urlsplit(home).hostname, urlsplit(url).hostname),
                                    urlsplit(url).path.strip("/").count("/")))
    return (pinned + remaining)[:4]


def comparisons(site, observation, statements):
    if not observation:
        return []
    events = [(category, "collect", f"The page displays a field for {DATA_TYPES[category][0].lower()}.",
               "A form field alone does not establish submission.")
              for category in observation["forms"]]
    for item in observation["requests"]:
        other = not same_host(site, item["host"])
        action = "share" if other else "collect"
        label = DATA_TYPES[item["category"]][0].lower()
        events.append((item["category"], action,
                       f"{item['count']} resource URL observation(s) for {item['host']} contained a parameter for {label}.",
                       "The destination hostname differs. Its relationship to this site is unknown." if other else
                       "A URL observation does not establish how long the site retained the value."))
    if any(count for count in observation["storage"].values()):
        events.append(("storage", "store", "The page's browser storage contained entries.",
                       "Storage contents and retention were not read."))

    results = []
    for category, action, evidence, note in events:
        related = [statement for statement in statements
                   if statement["category"] == category and statement["action"] == action]
        denials = [statement for statement in related if statement["stance"] == "denied"]
        limited_denials = [statement for statement in related if statement["stance"] == "qualified_denial"]
        allowances = [statement for statement in related if statement["stance"] in {"disclosed", "qualified"}]
        if denials and not allowances and not limited_denials:
            status = "Possible mismatch"
            matched = denials
        elif denials or limited_denials:
            status = "Policy scope needs review"
            matched = (denials + limited_denials)[:1] + allowances[:1]
        elif allowances:
            status = ("Disclosed with qualifications" if all(item["stance"] == "qualified" for item in allowances)
                      else "Disclosed in the document")
            matched = allowances
        else:
            status = "No explicit matching statement" if statements else "Insufficient policy evidence"
            matched = []
        results.append({"data": DATA_TYPES[category][0], "status": status, "evidence": evidence, "note": note,
                        "statements": matched[:2]})
    rank = {"Possible mismatch": 0, "Policy scope needs review": 1, "No explicit matching statement": 2,
            "Insufficient policy evidence": 3, "Disclosed with qualifications": 4, "Disclosed in the document": 5}
    return sorted(results, key=lambda item: rank[item["status"]])


def url_risks(site, observation):
    risks = []
    if not observation:
        return risks
    for item in observation["requests"]:
        category = item["category"]
        other = not same_host(site, item["host"])
        label = DATA_TYPES[category][0].lower()
        if category in {"credentials", "payment"}:
            risks.append({"title": "Sensitive field name in a URL", "level": "High",
                          "detail": f"A resource URL for {item['host']} had a nonempty parameter for {label}.",
                          "action": "Verify the request with the site owner before entering sensitive information. URL parameters can appear in logs."})
        elif other and category in {"email", "phone", "address", "location"}:
            risks.append({"title": "Personal-data field name in an other-host URL", "level": "Medium",
                          "detail": f"A resource URL for {item['host']} had a nonempty parameter for {label}.",
                          "action": "Check why the other hostname receives this field and review the site's sharing disclosure."})
    return risks


def review_website(result):
    observation = result.get("observation")
    if observation is None:
        return {"answer": "Only the public documents were checked. Capture an open tab to score observed evidence.",
                "score": None, "claims": [], "limitations": []}

    source = f"{result['site']} browser snapshot"
    findings = []

    def add(title, fact, reason, step, level, *, confidence="High", statements=()):
        findings.append({
            "claim": fact, "risk": {"level": level, "why": reason}, "score": SCORE_BASE[level],
            "confidence": {"level": confidence, "basis": ("Observed directly in the browser snapshot."
                           if confidence == "High" else "The policy language needs verification in context.")},
            "evidence": [{"source": source, "fact": fact}] + [
                {"source": row["document"], "fact": row["quote"]} for row in statements
            ],
            "fix": {"title": title, "steps": [step], "url": statements[0]["source"] if statements else None},
        })

    for item in result["risks"]:
        add(item["title"], item["detail"], "URL parameters can be retained in browser history and logs.",
            item["action"], item["level"])
    for name, state in sorted(observation["permissions"].items()):
        if state == "granted":
            add(f"Review {name} access", f"The browser reports {name} permission as granted.",
                "A permission grant allows access subject to browser controls. This snapshot cannot establish use.",
                f"Open this site's browser permissions and block or reset {name} access if it is unnecessary.",
                "Medium" if name == "notifications" else "High")
    for row in result["comparisons"]:
        if row["status"] in {"Possible mismatch", "Policy scope needs review"}:
            add(f"Check the disclosure for {row['data'].lower()}", row["evidence"], row["note"],
                "Read the cited disclosure in context and ask the site owner to clarify the observed behavior.",
                "Medium", confidence="Medium", statements=row["statements"])
        elif row["evidence"].startswith("The page"):
            add(f"Review {row['data'].lower()}", row["evidence"], row["note"],
                "Share only fields needed for this task and review the site's privacy or storage controls.",
                "Low", statements=row["statements"])
    findings.sort(key=lambda finding: finding["score"], reverse=True)
    if findings:
        answer = f"{len(findings)} findings from the latest capture of {result['site']}."
    else:
        answer = f"The latest capture of {result['site']} had no findings that GhostPrint can score."
    return {
        "answer": answer, "claims": findings, "score": findings[0]["score"] if findings else None,
        "risk": findings[0]["risk"] if findings else None,
        "limitations": ["The browser snapshot covers visible field categories, selected URL metadata, permissions, "
                        "and storage counts. Server storage and request bodies are outside the capture."],
    }


def browser_only_website(site, observation):
    return {
        "site": site, "observation": observation, "statements": [], "retention": [],
        "documents": [{"kind": kind, "status": "Unavailable", "detail": "Public lookup is unavailable for this hostname."}
                      for kind in ("Privacy policy", "Terms")],
        "comparisons": comparisons(site, observation, []), "risks": url_risks(site, observation),
    }


def website_check(website, observation=None, links=(), privacy_url=None, terms_url=None):
    home = public_url(website, homepage=True)
    site = urlsplit(home).hostname
    deadline = monotonic() + 15
    candidates = {"Privacy policy": [], "Terms": []}
    for kind, supplied in (("Privacy policy", privacy_url), ("Terms", terms_url)):
        if supplied:
            candidates[kind].append(public_url(supplied))
    for url in links:
        try:
            normalized = public_url(url)
            kind = doc_kind(normalized)
        except ValueError:
            continue
        if kind:
            candidates[kind].append(normalized)
    try:
        landing = PolicyPage(*download_page(home, deadline))
        home = public_url(landing.url, homepage=True)
        for kind, url in landing.links:
            candidates[kind].append(url)
    except PageUnavailable:
        pass
    for kind, paths in (("Privacy policy", ("privacy", "privacy-policy")), ("Terms", ("terms", "terms-of-service"))):
        candidates[kind].extend(urljoin(home, path) for path in paths)
    documents, statements, retention = [], [], []
    for kind, urls in candidates.items():
        error = "No readable public document was found."
        for url in preferred_links(urls, home, supplied=privacy_url if kind == "Privacy policy" else terms_url):
            try:
                page = PolicyPage(*download_page(url, deadline))
                heading_matches = any(is_heading and doc_kind("https://example.com/", text) == kind
                                      for is_heading, text in page.blocks[:35])
                found, notes = extract_statements(page, kind)
                if not page.blocks or not (heading_matches or doc_kind(page.url) == kind and (found or notes)):
                    error = "The link did not open a recognizable policy document."
                    continue
            except PageUnavailable as exc:
                error = str(exc)
                continue
            documents.append({"kind": kind, "status": "Read", "url": page.url})
            statements.extend(found)
            retention.extend(notes)
            break
        else:
            documents.append({"kind": kind, "status": "Unavailable", "detail": error})
    # Merge similar presentation rows while preserving the full set for comparison.
    distinct = {}
    for item in statements:
        key = item["category"], item["action"], item["stance"], item["document"]
        distinct.setdefault(key, item)
    return {
        "site": site, "documents": documents, "statements": list(distinct.values())[:36],
        "retention": retention, "observation": observation, "comparisons": comparisons(site, observation, statements),
        "risks": url_risks(site, observation),
    }
