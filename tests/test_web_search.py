import unittest
from urllib.error import URLError
from unittest.mock import patch

from ghostprint.web_search import BRAVE_URL, WIKIPEDIA_URL, search_public_question


class PublicSearchTest(unittest.TestCase):
    def test_wikipedia_returns_ranked_excerpts(self):
        pages = [
            {"index": 2, "title": "Second", "extract": "Second excerpt.", "fullurl": "https://en.wikipedia.org/wiki/Second"},
            {"index": 1, "title": "First", "extract": "First excerpt.", "fullurl": "https://en.wikipedia.org/wiki/First"},
        ]
        with patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": ""}):
            with patch("ghostprint.web_search.request_json", return_value={"query": {"pages": pages}}) as request:
                result = search_public_question("What is differential privacy?")
        self.assertEqual(result["provider"], "English Wikipedia")
        self.assertEqual([item["title"] for item in result["sources"]], ["First", "Second"])
        endpoint, params = request.call_args.args
        self.assertEqual(endpoint, WIKIPEDIA_URL)
        self.assertEqual(params["gsrsearch"], "differential privacy")

    def test_brave_keeps_https_citations_only(self):
        response = {"web": {"results": [
            {"title": "Official", "description": "A &amp; B", "url": "https://example.org/article"},
            {"title": "Invalid", "description": "Text", "url": "javascript:alert(1)"},
        ]}}
        with patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "test-key"}):
            with patch("ghostprint.web_search.request_json", return_value=response) as request:
                result = search_public_question("Browser fingerprinting")
        self.assertEqual(result["sources"], [{
            "title": "Official", "snippet": "A & B", "url": "https://example.org/article"
        }])
        self.assertEqual(request.call_args.args[0], BRAVE_URL)
        self.assertEqual(request.call_args.args[2], {"X-Subscription-Token": "test-key"})

    def test_sensitive_and_overlong_queries_never_reach_the_provider(self):
        with patch("ghostprint.web_search.request_json") as request:
            for question in ("Remove person@example.org", "My token: test-secret",
                             "Data at https://example.org/secret", "Open C:\\Exports\\takeout.zip"):
                self.assertEqual(search_public_question(question), {"status": "blocked"})
            self.assertEqual(search_public_question("public " * 85), {"status": "too_long"})
            request.assert_not_called()

    def test_network_failure_is_recoverable(self):
        with patch("ghostprint.web_search.request_json", side_effect=URLError("offline")):
            self.assertEqual(search_public_question("differential privacy")["status"], "unavailable")
