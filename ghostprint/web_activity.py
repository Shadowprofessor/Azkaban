import re
from collections import deque
from datetime import UTC, datetime
from threading import Lock
from urllib.parse import urlsplit

from .retrieval import PLATFORMS, retrieve, tokens


WEB_GUIDES = [
    {
        "id": "web-permissions",
        "title": "Review permissions for this site",
        "terms": "camera microphone location permission permissions clipboard notification notifications access revoke block",
        "steps": [
            "Open the site and choose the site information control beside its address.",
            "Review access to camera, microphone, location, and notifications. Block or reset anything you do not need.",
        ],
        "url": "https://support.google.com/chrome/answer/114662",
    },
    {
        "id": "web-cookies",
        "title": "Clear browser data for this site",
        "terms": "cookies cookie storage cache browser tracking tracker trackers third party browsing data",
        "steps": [
            "Open your browser's privacy settings and search its site data list for the site's hostname.",
            "Remove the site's stored data. Clearing cookies can sign you out or reset preferences.",
            "Review third-party cookie settings to limit tracking across sites.",
        ],
        "url": "https://support.google.com/chrome/answer/95647",
    },
    {
        "id": "web-account",
        "title": "Find the site's account and deletion controls",
        "terms": "account delete deletion erase export remove profile request privacy policy personal information",
        "steps": [
            "Check the site's account or privacy settings for an export or deletion control.",
            "If you cannot find a control, open the site's privacy notice and look for its data request or privacy contact.",
            "Review the effects before confirming deletion. Browser data and account data are managed separately.",
        ],
        "url": "https://consumer.ftc.gov/articles/how-websites-and-apps-collect-and-use-your-information",
    },
]
SITE_PLATFORMS = {"google.com": "Google", "youtube.com": "Google",
                  "instagram.com": "Instagram", "spotify.com": "Spotify"}
BROWSER_ONLY = {"permissions", "permission", "microphone", "camera", "notification", "notifications",
                "cookie", "cookies", "cache", "clipboard", "browser"}
PATH = re.compile(r"/(?:[a-z]{2}(?:-[a-z]{2})?/)?(?:legal/|policies/)?"
                  r"(?:privacy(?:[-_]policy|[-_]notice)?|data[-_]deletion|delete[-_]account|"
                  r"cookie[-_]policy|cookies)(?:\.html)?/?$", re.I)
DOMAIN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
                    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?", re.I)


def hostname(value):
    if not isinstance(value, str) or len(value) > 253 or not DOMAIN.fullmatch(value):
        raise ValueError("Expected a website hostname.")
    return value.lower()


def safe_links(site, links):
    if not isinstance(links, list) or len(links) > 8:
        raise ValueError("Expected a short list of website links.")
    found = set()
    for link in links:
        if not isinstance(link, str) or len(link) > 280:
            continue
        try:
            parts = urlsplit(link)
            origin_host = site if parts.port is None else f"{site}:{parts.port}"
        except ValueError:
            continue
        if (parts.scheme in {"https", "http"} and parts.netloc == origin_host
                and PATH.fullmatch(parts.path) and not parts.query and not parts.fragment):
            found.add(link)
    return sorted(found)


class WebActivity:
    def __init__(self):
        self._events = deque(maxlen=2000)
        self._links = {}
        self._lock = Lock()

    def add(self, site, links=None):
        site = hostname(site)
        found = safe_links(site, links) if links is not None else None
        with self._lock:
            if found is not None:
                self._links[site] = found
            if not self._events or self._events[-1]["site"] != site or links is None:
                self._events.append({"site": site, "seen": datetime.now(UTC).isoformat(timespec="seconds")})
            if len(self._links) > 200:
                self._links.pop(next(iter(self._links)))

    def snapshot(self):
        with self._lock:
            sites = {}
            for event in reversed(self._events):
                site = event["site"]
                item = sites.setdefault(site, {**event, "visits": 0})
                item["visits"] += 1
            return list(sites.values())[:100]

    def links(self, site):
        with self._lock:
            return self._links.get(site, [])

    def clear(self):
        with self._lock:
            self._events.clear()
            self._links.clear()


def answer(prompt, site, observed_links):
    query = set(tokens(prompt))
    web = sorted(
        ((len(query & set(guide["terms"].split())), guide) for guide in WEB_GUIDES),
        key=lambda match: -match[0],
    )
    platform = next((name for domain, name in SITE_PLATFORMS.items()
                     if site == domain or site.endswith("." + domain)), None)
    mentioned_platforms = query & PLATFORMS.keys()
    if len(mentioned_platforms) == 1:
        platform = PLATFORMS[next(iter(mentioned_platforms))]
    platform_guides = retrieve(prompt, platform=platform, k=2) if platform and not query & BROWSER_ONLY else []
    guides = (platform_guides + [guide for score, guide in web if score])[:3]
    if not guides and site and not prompt.strip():
        guides = WEB_GUIDES
    return {"site": site, "links": observed_links, "guides": guides}
