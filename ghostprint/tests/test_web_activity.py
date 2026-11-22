import unittest
from unittest.mock import patch

from ghostprint.web_activity import WebActivity, answer, hostname


class WebsiteAuditTest(unittest.TestCase):
    def test_search_runs_only_after_an_opted_in_local_miss(self):
        fact = "What is differential privacy?"
        with patch("ghostprint.web_activity.search_public_question", return_value={"status": "empty"}) as lookup:
            self.assertNotIn("web", answer(fact, "unshared.example", ["https://unshared.example/privacy"]))
            self.assertNotIn("web", answer("Clear this site's cookies", "unshared.example", [], search_web=True))
            self.assertNotIn("web", answer("", "unshared.example", [], search_web=True))
            lookup.assert_not_called()
            result = answer(fact, "unshared.example", ["https://unshared.example/privacy"], search_web=True)
            self.assertEqual(result["guides"], [])
            self.assertEqual(result["web"], {"status": "empty"})
            lookup.assert_called_once_with(fact)

    def test_new_domains_get_general_guides_without_claims(self):
        result = answer("How do I turn off microphone access?", "newsite.example", [])
        self.assertEqual(result["site"], "newsite.example")
        self.assertEqual(result["guides"][0]["id"], "web-permissions")
        self.assertTrue(result["guides"][0]["url"].startswith("https://support.google.com/"))
        self.assertEqual(answer("Balance an equation", "newsite.example", [])["guides"], [])

    def test_platform_retrieval_is_grounded(self):
        self.assertEqual(answer("Delete my timeline", "maps.google.com", [])["guides"][0]["id"], "google-timeline")
        self.assertEqual(answer("How can I clear Spotify cookies?", "", [])["guides"][0]["id"], "web-cookies")

    def test_site_record_and_privacy_links(self):
        activity = WebActivity()
        activity.add("NEWsite.example")
        activity.add("newsite.example", [
            "https://newsite.example/privacy",
            "https://newsite.example/terms?identifier=private",
            "https://newsite.example/data-deletion?identifier=private",
            "https://newsite.example@foreign.example/privacy",
            "https://foreign.example/privacy",
            "javascript:alert(1)",
        ])
        self.assertEqual(activity.snapshot()[0]["visits"], 1)
        self.assertEqual(activity.links("newsite.example"), ["https://newsite.example/privacy"])
        activity.clear()
        self.assertEqual(activity.snapshot(), [])
        self.assertEqual(activity.links("newsite.example"), [])

    def test_url_and_form_data_are_not_hostnames(self):
        for text in ("https://newsite.example", "newsite.example/path", "newsite.example?q=private"):
            with self.assertRaises(ValueError):
                hostname(text)
