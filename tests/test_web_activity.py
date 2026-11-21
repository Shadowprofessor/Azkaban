import unittest

from ghostprint.web_activity import WebActivity, answer, hostname


class WebsiteAuditTest(unittest.TestCase):
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
