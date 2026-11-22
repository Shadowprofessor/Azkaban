"""Routes the merged website (dashboard/, from the nirmit branch) calls on this backend.

nirmit's UI was written against `/api/oauth/<provider>/start|disconnect` and `/api/hibp`.
This backend (from the yash branch) already implements the substance under
`/api/connections`; this module is the thin translation, so neither side's code had to be
rewritten.

Everything still binds 127.0.0.1 only and keeps the server's own Host check. The website
runs on a different port (Vite, 5173), so its Origin is added through an explicit
allowlist (GHOSTPRINT_ALLOWED_ORIGINS) rather than by disabling the check.
"""
from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import ProxyHandler, Request, build_opener

from .connections import PROVIDERS, ConnectionProblem

DEFAULT_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")
OAUTH_ROUTE = re.compile(r"^/api/oauth/([a-z]{2,20})/(start|disconnect)$")
EMAIL = re.compile(r"^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,24}$")
HIBP_URL = "https://haveibeenpwned.com/api/v3/breachedaccount/"


def allowed_origins() -> set[str]:
    raw = os.getenv("GHOSTPRINT_ALLOWED_ORIGINS", "")
    extra = {o.strip().rstrip("/") for o in raw.split(",") if o.strip()}
    return set(DEFAULT_ORIGINS) | extra


def after_oauth(provider: str | None, ok: bool) -> str | None:
    """Where to send the browser after an OAuth callback.

    With GHOSTPRINT_RETURN_URL set (the website's address) the user lands back on the
    website with ?oauth=connected|failed&provider=<id>, which its Link apps page reads.
    Unset, the old in-backend page is used.
    """
    base = os.getenv("GHOSTPRINT_RETURN_URL", "").strip()
    if not base or not provider:
        return None
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}" + urlencode({"oauth": "connected" if ok else "failed", "provider": provider})


def _reply(handler, status: int, data: dict) -> bool:
    handler.send_json(status, data)
    return True


def handle_post(handler, connections) -> bool:
    """Serve a website route if this is one. Returns True when the request was handled."""
    path = handler.path.split("?", 1)[0]
    m = OAUTH_ROUTE.match(path)
    if m:
        return _oauth(handler, connections, m.group(1), m.group(2))
    if path == "/api/hibp":
        return _hibp(handler)
    return False


def _oauth(handler, connections, provider: str, action: str) -> bool:
    if provider not in PROVIDERS:
        supported = ", ".join(p.title for p in PROVIDERS.values())
        return _reply(handler, 501, {"error": f"{provider.title()} sign-in is not available in this build. "
                                              f"Supported: {supported}."})
    try:
        if action == "start":
            url = connections.begin(provider, handler.server.server_port)
            return _reply(handler, 200, {"authorizationUrl": url})
        connections.disconnect(provider)
        return _reply(handler, 200, {"ok": True, "accounts": connections.status()})
    except ConnectionProblem as error:
        msg = str(error)
        if "requires local OAuth app configuration" in msg:
            prefix = PROVIDERS[provider].env_prefix
            msg += (f" Add {prefix}_OAUTH_CLIENT_ID and {prefix}_OAUTH_CLIENT_SECRET to .env, with "
                    f"redirect URI http://127.0.0.1:{handler.server.server_port}/ registered for the app.")
        return _reply(handler, 409, {"error": msg})


def _hibp(handler) -> bool:
    """Breach lookup for one email the user typed, through Have I Been Pwned.

    This is the one route that sends an identifier off the machine, so it only runs when
    the user has configured HIBP_API_KEY (HIBP requires a key for this endpoint) and asked
    for the scan. The address is sent to HIBP and nowhere else, and is not logged.
    """
    key = os.getenv("HIBP_API_KEY", "").strip()
    if not key:
        return _reply(handler, 501, {"error": "Breach scan needs an Have I Been Pwned API key. "
                                              "Add HIBP_API_KEY to .env to enable it."})
    try:
        body = json.loads(handler.read_body(1024))
    except (ValueError, TypeError):
        return _reply(handler, 400, {"error": "Send a JSON body with an email field."})
    email = body.get("email") if isinstance(body, dict) else None
    if not isinstance(email, str) or not EMAIL.match(email.strip()):
        return _reply(handler, 400, {"error": "Enter a valid email address."})
    req = Request(HIBP_URL + quote(email.strip()) + "?truncateResponse=false",
                  headers={"hibp-api-key": key, "user-agent": "Azkaban-local-audit"})
    try:
        with build_opener(ProxyHandler({})).open(req, timeout=10) as r:
            breaches = json.loads(r.read(512 * 1024))
    except HTTPError as error:
        if error.code == 404:
            return _reply(handler, 200, {"breached": False, "count": 0, "breaches": []})
        if error.code == 401:
            return _reply(handler, 502, {"error": "Have I Been Pwned rejected the API key."})
        if error.code == 429:
            return _reply(handler, 429, {"error": "Have I Been Pwned rate-limited the scan. Try again shortly."})
        return _reply(handler, 502, {"error": f"Have I Been Pwned returned HTTP {error.code}."})
    except (URLError, TimeoutError, OSError, ValueError):
        return _reply(handler, 502, {"error": "Could not reach Have I Been Pwned."})
    rows = [{"name": b.get("Name"), "domain": b.get("Domain"), "date": b.get("BreachDate"),
             "data": b.get("DataClasses", [])} for b in breaches if isinstance(b, dict)]
    return _reply(handler, 200, {"breached": bool(rows), "count": len(rows), "breaches": rows})
