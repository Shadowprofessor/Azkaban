import base64
import hashlib
import json
import os
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from ghostprint.connections import PROVIDERS, ConnectionProblem, Connections, review_snapshot


class ConnectionsTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {
            "GOOGLE_OAUTH_CLIENT_ID": "test-google-client",
            "GOOGLE_OAUTH_CLIENT_SECRET": "test-google-secret",
            "GITHUB_OAUTH_CLIENT_ID": "test-github-client",
            "GITHUB_OAUTH_CLIENT_SECRET": "test-github-secret",
        }):
            self.accounts = Connections()

    def begin(self, provider):
        url = urlsplit(self.accounts.begin(provider, 8765))
        self.assertEqual(f"{url.scheme}://{url.netloc}{url.path}", PROVIDERS[provider].authorization)
        params = {key: values[0] for key, values in parse_qs(url.query).items()}
        self.assertEqual(params["scope"], PROVIDERS[provider].scope)
        self.assertEqual(params["redirect_uri"], "http://127.0.0.1:8765/")
        self.assertEqual(params["code_challenge_method"], "S256")
        self.assertNotIn("client_secret", params)
        return params

    def test_google_consent_fetches_pages_once_and_keeps_only_aggregate_data(self):
        params = self.begin("google")
        with patch("ghostprint.connections.request_json", side_effect=[
            {"access_token": "test-google-token", "scope": PROVIDERS["google"].scope},
            {"connections": [{"emailAddresses": [{"value": "private@example.test"}]}], "nextPageToken": "next"},
            {"connections": [{"phoneNumbers": [{"value": "555-0100"}]}, {}]},
        ]) as request:
            self.assertFalse(self.accounts.finish("z" * 43, "forged"))
            request.assert_not_called()
            self.assertTrue(self.accounts.finish(params["state"], "test-code"))
            self.assertFalse(self.accounts.finish(params["state"], "test-code"))
        exchange, first_page, second_page = request.call_args_list
        self.assertEqual(exchange.args, (PROVIDERS["google"].token_endpoint,))
        form = exchange.kwargs["form"]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest())
        self.assertEqual(challenge.rstrip(b"=").decode(), params["code_challenge"])
        self.assertEqual(form["redirect_uri"], params["redirect_uri"])
        self.assertEqual(first_page.kwargs["token"], "test-google-token")
        query = parse_qs(urlsplit(second_page.args[0]).query)
        self.assertEqual(query["pageToken"], ["next"])
        self.assertNotIn("value", query["fields"][0])
        account = self.accounts.status()[0]
        self.assertTrue(account["connected"])
        self.assertEqual(account["snapshot"]["record_count"], 3)
        output = json.dumps(account)
        self.assertIn("Email fields on 1 records", output)
        for private in ("private@example.test", "555-0100", "test-google-secret", "test-google-token"):
            self.assertNotIn(private, output)

    def test_denial_and_incomplete_scope_do_not_fetch_records(self):
        google = self.begin("google")
        github = self.begin("github")
        with patch("ghostprint.connections.request_json", return_value={
            "access_token": "test-github-token", "scope": "repo",
        }) as request:
            self.assertFalse(self.accounts.finish(google["state"], None, denied=True))
            request.assert_not_called()
            self.assertFalse(self.accounts.finish(github["state"], "test-code"))
            request.assert_called_once()
        self.assertTrue(all(not account["connected"] and not account["snapshot"] and account["error"]
                            for account in self.accounts.status()))

    def test_github_visibility_refresh_and_disconnect(self):
        params = self.begin("github")
        with patch("ghostprint.connections.request_json", side_effect=[
            {"access_token": "test-github-token", "scope": "user:email"},
            [{"email": "public@example.test", "visibility": "public"}, {"email": "hidden@example.test"}],
            [{"email": "hidden@example.test", "visibility": "private"}],
            ConnectionProblem("Authorization expired.", expired=True),
        ]):
            self.assertTrue(self.accounts.finish(params["state"], "test-code"))
            snapshot = self.accounts.status()[1]["snapshot"]
            self.assertEqual(snapshot["review"]["risk"]["level"], "Medium")
            self.assertIn("1 unspecified", json.dumps(snapshot))
            self.assertNotIn("@example.test", json.dumps(snapshot))
            self.accounts.refresh("github")
            updated = self.accounts.status()[1]["snapshot"]
            self.assertEqual(updated["record_count"], 1)
            self.assertEqual(updated["review"]["risk"]["level"], "Low")
            with self.assertRaises(ConnectionProblem):
                self.accounts.refresh("github")
        self.assertFalse(self.accounts.status()[1]["connected"])
        self.assertEqual(self.accounts.status()[1]["snapshot"], updated)
        self.accounts.disconnect("github")
        self.assertIsNone(self.accounts.status()[1]["snapshot"])
        with self.assertRaises(ConnectionProblem):
            self.accounts.refresh("github")

    def test_empty_scope_has_no_exposure_score(self):
        with patch("ghostprint.connections.request_json", return_value=[]):
            snapshot = review_snapshot("github", "test-token")
        self.assertEqual(snapshot["record_count"], 0)
        self.assertIsNone(snapshot["review"]["score"])
        self.assertFalse(snapshot["review"]["claims"])


if __name__ == "__main__":
    unittest.main()
