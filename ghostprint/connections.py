"""Read-only, session-local account snapshots authorized through OAuth."""

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from secrets import token_urlsafe
from threading import Lock
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from .analyst import analyze
from .model import NoRedirect


@dataclass(frozen=True)
class Provider:
    title: str
    description: str
    scope: str
    authorization: str
    token_endpoint: str
    grants_url: str
    env_prefix: str


PROVIDERS = {
    "google": Provider(
        "Google Contacts", "Contact counts and whether email or phone fields are present.",
        "https://www.googleapis.com/auth/contacts.readonly",
        "https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token",
        "https://myaccount.google.com/connections", "GOOGLE",
    ),
    "github": Provider(
        "GitHub", "Account email counts and visibility metadata.",
        "user:email", "https://github.com/login/oauth/authorize", "https://github.com/login/oauth/access_token",
        "https://github.com/settings/applications", "GITHUB",
    ),
}
MAX_PAGES = 10
TOKEN_TTL = 3600
STATE_TTL = 600


class ConnectionProblem(RuntimeError):
    def __init__(self, message, *, expired=False):
        super().__init__(message)
        self.expired = expired


def request_json(url, *, form=None, token=None):
    headers = {"Accept": "application/json", "User-Agent": "GhostPrint local account audit"}
    if urlsplit(url).hostname == "api.github.com":
        headers.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"})
    data = None
    if form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urlencode(form).encode()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=data, headers=headers)
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=8) as response:
            raw = response.read(768 * 1024 + 1)
        if len(raw) > 768 * 1024:
            raise ConnectionProblem("The provider returned more data than this snapshot can read.")
        return json.loads(raw)
    except HTTPError as error:
        if error.code == 401:
            raise ConnectionProblem("Authorization expired or was revoked. Connect again.", expired=True) from None
        if error.code == 403:
            raise ConnectionProblem("The provider denied access. Check the API and app permissions.") from None
        if error.code == 429:
            raise ConnectionProblem("The provider rate-limited this request. Try again later.") from None
        raise ConnectionProblem(f"The provider returned HTTP {error.code}. Check the app configuration.") from None
    except (URLError, OSError, ValueError):
        raise ConnectionProblem("Could not read the provider's response. Try again.") from None


def google_snapshot(token):
    count = email_fields = phone_fields = 0
    parameters = {
        "personFields": "metadata,emailAddresses,phoneNumbers",
        "sources": "READ_SOURCE_TYPE_CONTACT", "pageSize": 250,
        "fields": "connections(emailAddresses(metadata),phoneNumbers(metadata)),nextPageToken",
    }
    more = False
    for _ in range(MAX_PAGES):
        result = request_json("https://people.googleapis.com/v1/people/me/connections?" + urlencode(parameters), token=token)
        if not isinstance(result, dict) or "error" in result or not isinstance(result.get("connections", []), list):
            raise ConnectionProblem("Google returned an unexpected contacts response.")
        records = [row for row in result.get("connections", []) if isinstance(row, dict)]
        count += len(records)
        email_fields += sum(bool(row.get("emailAddresses")) for row in records)
        phone_fields += sum(bool(row.get("phoneNumbers")) for row in records)
        next_page = result.get("nextPageToken")
        more = isinstance(next_page, str) and 0 < len(next_page) <= 2048
        if not more:
            break
        parameters["pageToken"] = next_page
    signal = f"Email fields on {email_fields:,} records; phone fields on {phone_fields:,} records"
    return {
        "platform": "Google", "category": "contacts", "kind": "Connected contact metadata",
        "id": "Google People API · contacts snapshot", "count": count, "signal": signal,
    }, more


def github_snapshot(token):
    count = public = private = 0
    more = False
    for page in range(1, MAX_PAGES + 1):
        result = request_json(f"https://api.github.com/user/emails?per_page=100&page={page}", token=token)
        if not isinstance(result, list):
            raise ConnectionProblem("GitHub returned an unexpected email response.")
        records = [row for row in result if isinstance(row, dict) and isinstance(row.get("email"), str)]
        count += len(records)
        public += sum(row.get("visibility") == "public" for row in records)
        private += sum(row.get("visibility") == "private" for row in records)
        more = len(result) == 100
        if not more:
            break
    return {
        "platform": "GitHub", "category": "identity", "kind": "Connected email visibility metadata",
        "id": "GitHub REST API · email snapshot", "count": count,
        "signal": f"{public:,} marked public; {private:,} marked private; {count - public - private:,} unspecified",
        "flags": {"account_email_snapshot": 1, "public_account_email": public},
    }, more


def review_snapshot(key, token):
    row, partial = google_snapshot(token) if key == "google" else github_snapshot(token)
    review = analyze("", {"analyst_sources": [row] if row["count"] else []}, automatic=True)
    review["limitations"][0] = "This review covers only the records returned by the authorized API snapshot."
    if partial:
        review["limitations"].append("The page limit was reached. This snapshot covers the records returned so far.")
    if not row["count"]:
        review["answer"] = "The provider returned no records in the authorized scope."
    return {"record_count": row["count"], "synced_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "review": review}


class Connections:
    def __init__(self):
        self._config = {key: (os.getenv(f"{provider.env_prefix}_OAUTH_CLIENT_ID", "").strip(),
                              os.getenv(f"{provider.env_prefix}_OAUTH_CLIENT_SECRET", "").strip())
                        for key, provider in PROVIDERS.items()}
        self._pending = {}
        self._active = {}
        self._snapshots = {}
        self._tokens = {}
        self._errors = {}
        self._lock = Lock()

    def status(self):
        with self._lock:
            return [{
                "id": key, "title": provider.title, "description": provider.description,
                "grants_url": provider.grants_url, "configured": all(self._config[key]),
                "busy": key in self._active, "connected": self._current_token(key) is not None,
                "snapshot": self._snapshots.get(key), "error": self._errors.get(key),
            } for key, provider in PROVIDERS.items()]

    def _current_token(self, key):
        connected = self._tokens.get(key)
        if connected and connected[1] <= monotonic():
            self._tokens.pop(key, None)
            return None
        return connected

    def begin(self, key, port):
        provider = PROVIDERS[key]
        client_id, client_secret = self._config[key]
        if not client_id or not client_secret:
            raise ConnectionProblem(f"{provider.title} requires local OAuth app configuration.")
        state, verifier = token_urlsafe(32), token_urlsafe(48)
        redirect = f"http://127.0.0.1:{port}/"
        with self._lock:
            if key in self._active:
                raise ConnectionProblem("This account is already syncing.")
            self._errors.pop(key, None)
            self._pending[key] = (state, verifier, redirect, monotonic() + STATE_TTL)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        return provider.authorization + "?" + urlencode({
            "client_id": client_id, "redirect_uri": redirect, "response_type": "code",
            "scope": provider.scope, "state": state, "code_challenge": challenge,
            "code_challenge_method": "S256", "prompt": "select_account",
        })

    def key_for_state(self, state):
        """Provider id a pending OAuth state belongs to, or None. Read-only."""
        with self._lock:
            return next((key for key, pending in self._pending.items() if pending[0] == state), None)

    def finish(self, state, code, denied=False):
        if not isinstance(state, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", state):
            return False
        with self._lock:
            key = next((key for key, pending in self._pending.items() if pending[0] == state), None)
            if key is None:
                return False
            _, verifier, redirect, expires = self._pending.pop(key)
            if expires <= monotonic():
                self._errors[key] = "The sign-in window expired. Connect again."
                return False
            if denied or not isinstance(code, str) or not 1 <= len(code) <= 4096:
                self._errors[key] = "Authorization was not completed. Try connecting again."
                return False
            marker = object()
            self._active[key] = marker
        try:
            client_id, secret = self._config[key]
            answer = request_json(PROVIDERS[key].token_endpoint, form={
                "client_id": client_id, "client_secret": secret, "code": code,
                "redirect_uri": redirect, "code_verifier": verifier, "grant_type": "authorization_code",
            })
            token = answer.get("access_token") if isinstance(answer, dict) else None
            if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_~+./=-]{1,8192}", token):
                raise ConnectionProblem("The provider did not grant access. Check the OAuth app settings.")
            expiry = answer.get("expires_in")
            ttl = min(TOKEN_TTL, expiry) if type(expiry) is int and expiry > 0 else TOKEN_TTL
            granted = answer.get("scope")
            if isinstance(granted, str) and PROVIDERS[key].scope not in re.split(r"[ ,]+", granted):
                raise ConnectionProblem("The requested read-only scope was not granted.")
            return self._sync(key, marker, (token, monotonic() + ttl))
        except ConnectionProblem as exc:
            self._finish_error(key, marker, exc)
            return False

    def _finish_error(self, key, marker, error):
        with self._lock:
            if self._active.get(key) is marker:
                self._active.pop(key, None)
                self._errors[key] = str(error)
                if error.expired:
                    self._tokens.pop(key, None)

    def _sync(self, key, marker, connected):
        snapshot = review_snapshot(key, connected[0])
        with self._lock:
            if self._active.get(key) is not marker:
                return False
            self._active.pop(key, None)
            self._tokens[key] = connected
            self._snapshots[key] = snapshot
            self._errors.pop(key, None)
            return True

    def refresh(self, key):
        with self._lock:
            connected = self._current_token(key)
            if not connected:
                raise ConnectionProblem("Connect the account again to refresh it.")
            if key in self._active:
                raise ConnectionProblem("This account is already syncing.")
            self._pending.pop(key, None)
            marker = object()
            self._active[key] = marker
        try:
            self._sync(key, marker, connected)
        except ConnectionProblem as exc:
            self._finish_error(key, marker, exc)
            raise

    def disconnect(self, key):
        with self._lock:
            for collection in (self._pending, self._active, self._tokens, self._snapshots, self._errors):
                collection.pop(key, None)
