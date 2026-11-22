"""The website (nirmit) <-> GhostPrint backend (yash) translation layer."""
import json

from ghostprint import integration


class FakeHandler:
    def __init__(self, path, body=b""):
        self.path = path
        self._body = body
        self.sent = None
        self.server = type("S", (), {"server_port": 8765})()

    def send_json(self, status, data):
        self.sent = (status, data)

    def read_body(self, maximum):
        return self._body[:maximum]


class FakeConnections:
    def __init__(self):
        self.calls = []

    def begin(self, key, port):
        self.calls.append(("begin", key, port))
        return f"https://example.test/authorize?client={key}"

    def disconnect(self, key):
        self.calls.append(("disconnect", key))

    def status(self):
        return []


def test_website_origin_is_allowed_and_others_are_not(monkeypatch):
    monkeypatch.delenv("GHOSTPRINT_ALLOWED_ORIGINS", raising=False)
    allowed = integration.allowed_origins()
    assert "http://127.0.0.1:5173" in allowed
    assert "https://evil.example" not in allowed


def test_extra_origins_come_only_from_explicit_config(monkeypatch):
    monkeypatch.setenv("GHOSTPRINT_ALLOWED_ORIGINS", "http://127.0.0.1:4173/")
    assert "http://127.0.0.1:4173" in integration.allowed_origins()


def test_oauth_start_returns_the_url_the_website_expects():
    h, c = FakeHandler("/api/oauth/github/start"), FakeConnections()
    assert integration.handle_post(h, c)
    status, data = h.sent
    assert status == 200 and data["authorizationUrl"].startswith("https://")
    assert c.calls == [("begin", "github", 8765)]


def test_disconnect_is_routed():
    h, c = FakeHandler("/api/oauth/google/disconnect"), FakeConnections()
    integration.handle_post(h, c)
    assert c.calls == [("disconnect", "google")] and h.sent[0] == 200


def test_unsupported_provider_says_what_is_supported():
    h = FakeHandler("/api/oauth/instagram/start")
    integration.handle_post(h, FakeConnections())
    status, data = h.sent
    assert status == 501 and "Google" in data["error"] and "GitHub" in data["error"]


def test_other_paths_are_left_to_the_original_handler():
    assert integration.handle_post(FakeHandler("/api/connections"), FakeConnections()) is False


def test_breach_scan_without_a_key_explains_how_to_enable_it(monkeypatch):
    monkeypatch.delenv("HIBP_API_KEY", raising=False)
    h = FakeHandler("/api/hibp", json.dumps({"email": "a@b.co"}).encode())
    integration.handle_post(h, FakeConnections())
    assert h.sent[0] == 501 and "HIBP_API_KEY" in h.sent[1]["error"]


def test_breach_scan_rejects_a_bad_email_before_any_network(monkeypatch):
    monkeypatch.setenv("HIBP_API_KEY", "k")
    h = FakeHandler("/api/hibp", json.dumps({"email": "not-an-email"}).encode())
    integration.handle_post(h, FakeConnections())
    assert h.sent[0] == 400


def test_oauth_return_goes_back_to_the_website(monkeypatch):
    monkeypatch.setenv("GHOSTPRINT_RETURN_URL", "http://127.0.0.1:5173/")
    assert integration.after_oauth("github", True) == "http://127.0.0.1:5173/?oauth=connected&provider=github"
    assert integration.after_oauth("github", False).endswith("oauth=failed&provider=github")


def test_without_a_return_url_the_old_page_is_kept(monkeypatch):
    monkeypatch.delenv("GHOSTPRINT_RETURN_URL", raising=False)
    assert integration.after_oauth("github", True) is None
