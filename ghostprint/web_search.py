import json
import os
import re
from html import unescape
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener

from .model import NoRedirect


BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
WIKIPEDIA_URL = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "GhostPrint/1.0 (https://github.com/Shadowprofessor/Azkaban)"
PRIVATE_TEXT = re.compile(
    r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b|\b(?:https?://|file://)\S+|"
    r"\b[A-Z]:[\\/]|\\\\\w+\\|\b(?:nvapi-|sk-|ghp_|github_pat_)[\w-]{8,}|"
    r"\b(?:api[ _-]?key|password|secret|token)\s*[:=]|(?<!\w)\+?\d(?:[ .()-]*\d){8,}(?!\w)",
    re.I,
)
WIKI_PREFIX = re.compile(
    r"^(?:what (?:is|are)|please explain|explain|define|tell me about)\s+(?:(?:a|an|the)\s+)?",
    re.I,
)


def clean_result(title, snippet, url):
    if not all(isinstance(item, str) for item in (title, snippet, url)):
        return None
    if len(url) > 2048 or "\\" in url or any(char.isspace() or ord(char) < 32 for char in url):
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username is not None:
            return None
    except ValueError:
        return None
    title = " ".join(title.split())[:160]
    snippet = " ".join(snippet.split())
    if len(snippet) > 450:
        snippet = snippet[:450].rsplit(" ", 1)[0] + "…"
    return {"title": title, "snippet": snippet, "url": url} if title and snippet else None


def request_json(endpoint, parameters, headers=None):
    request = Request(
        f"{endpoint}?{urlencode(parameters)}",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT, **(headers or {})},
    )
    with build_opener(NoRedirect()).open(request, timeout=6) as response:
        body = response.read(512 * 1024 + 1)
    if len(body) > 512 * 1024:
        raise ValueError("Search response exceeded its size limit.")
    data = json.loads(body)
    if not isinstance(data, dict) or "error" in data:
        raise ValueError("Search provider returned an error.")
    return data


def brave(query, key):
    data = request_json(BRAVE_URL, {
        "q": query, "count": 5, "text_decorations": "false", "safesearch": "moderate",
    }, {"X-Subscription-Token": key})
    for item in (data.get("web") or {}).get("results", []):
        yield clean_result(item.get("title"), unescape(item.get("description") or ""), item.get("url"))


def wikipedia(query):
    term = WIKI_PREFIX.sub("", query).strip(" .?!")
    data = request_json(WIKIPEDIA_URL, {
        "action": "query", "generator": "search", "gsrsearch": term, "gsrnamespace": 0, "gsrlimit": 4,
        "prop": "extracts|info", "exintro": 1, "explaintext": 1, "exchars": 450,
        "inprop": "url", "format": "json", "formatversion": 2,
    })
    pages = data.get("query", {}).get("pages", [])
    for page in sorted(pages, key=lambda item: item.get("index", 100)):
        yield clean_result(page.get("title"), page.get("extract"), page.get("fullurl"))


def search_public_question(prompt):
    query = " ".join(prompt.split())
    if PRIVATE_TEXT.search(prompt):
        return {"status": "blocked"}
    if len(query) > 500 or len(query.split()) > 70:
        return {"status": "too_long"}
    if not any(char.isalnum() for char in query):
        return {"status": "empty"}
    key = os.getenv("BRAVE_SEARCH_API_KEY")
    provider = "Brave Search" if key else "English Wikipedia"
    try:
        results = {}
        for result in brave(query, key) if key else wikipedia(query):
            if result:
                results.setdefault(result["url"], result)
            if len(results) == 3:
                break
    except (OSError, ValueError, TypeError, AttributeError):
        return {"status": "unavailable", "provider": provider}
    return {"status": "ok" if results else "empty", "provider": provider, "sources": list(results.values())}
