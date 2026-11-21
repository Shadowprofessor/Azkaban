import socket
import unittest
from unittest.mock import patch

from ghostprint.public_pages import PageUnavailable, PolicyPage, doc_kind, public_addresses, public_url
from ghostprint.site_policy import comparisons, extract_statements, validate_observation, website_check
from ghostprint.web_activity import WebActivity


HOME = "https://shop.example.com"
PRIVACY = HOME + "/privacy"
TERMS = HOME + "/terms"
POLICY = """
<h1>Privacy Policy</h1>
<p>We collect email addresses to respond to customer requests.</p>
<p>We do not share email addresses.</p>
<p>We do not share phone numbers unless required by law.</p>
<p>We collect your full name and share IP addresses.</p>
<p>We retain personal information for 30 days.</p>
"""


def snapshot():
    return {
        "forms": ["email"],
        "requests": [
            {"host": "external.example.com", "category": "email", "count": 1},
            {"host": "external.example.com", "category": "phone", "count": 1},
            {"host": "shop.example.com", "category": "credentials", "count": 1},
        ],
        "hosts": ["external.example.com"],
        "storage": {"local": 0, "session": None},
    }


class WebsitePolicyTest(unittest.TestCase):
    def test_links_and_comparisons_keep_scope_and_attribution(self):
        fake = {
            HOME + "/": '<footer><a href="/compare-privacy">Privacy features</a>'
                         '<a href="/privacy?visitor=remove-me">Privacy Policy</a>'
                         '<a href="/terms">Terms of Service</a></footer>',
            PRIVACY: POLICY,
            TERMS: "<h1>Terms of Service</h1><p>Some account features require an account.</p>",
        }

        def download(url, _deadline):
            if url not in fake:
                raise PageUnavailable("No document.")
            return url, "text/html", fake[url]

        with patch("ghostprint.site_policy.download_page", side_effect=download) as reader:
            result = website_check(HOME + "/account?unused=local", validate_observation(snapshot()))
        self.assertEqual([item["url"] for item in result["documents"]], [PRIVACY, TERMS])
        self.assertEqual({args.args[0] for args in reader.call_args_list}, set(fake))
        self.assertEqual(result["comparisons"][0]["status"], "Possible mismatch")
        self.assertEqual(result["comparisons"][0]["statements"][0]["source"], PRIVACY)
        self.assertTrue(any(row["status"] == "Policy scope needs review" and row["data"] == "Phone numbers"
                            for row in result["comparisons"]))
        self.assertTrue(any(row["status"] == "Disclosed in the document" and row["data"] == "Email addresses"
                            for row in result["comparisons"]))
        self.assertTrue(result["retention"])
        self.assertTrue(any(item["title"] == "Sensitive field name in a URL" for item in result["risks"]))
        self.assertNotIn(("name", "share"), {(s["category"], s["action"]) for s in result["statements"]})

    def test_permission_alone_and_sale_denial_do_not_claim_sharing(self):
        clauses, _ = extract_statements(PolicyPage(PRIVACY, "text/html", "<p>We never sell email addresses.</p>"),
                                        "Privacy policy")
        self.assertEqual(comparisons("shop.example.com", None, clauses), [])
        observation = validate_observation(snapshot())
        observation["forms"] = []
        observation["requests"] = observation["requests"][:1]
        observation["permissions"] = {"geolocation": "granted"}
        result = comparisons("shop.example.com", observation, clauses)
        self.assertEqual([item["status"] for item in result], ["No explicit matching statement"])

    def test_snapshots_reject_data_values_and_clear_with_activity(self):
        activity = WebActivity()
        bad = snapshot()
        bad["requests"][0]["value"] = "private@example.invalid"
        with self.assertRaises(ValueError):
            activity.add("shop.example.com", [], observation=bad)
        activity.add("shop.example.com", [TERMS], {"camera": "denied"}, snapshot())
        self.assertEqual(activity.links("shop.example.com"), [TERMS])
        self.assertEqual(activity.site_observation("shop.example.com")["permissions"], {"camera": "denied"})
        activity.clear()
        self.assertIsNone(activity.site_observation("shop.example.com"))

    def test_unsafe_destinations_and_marketing_links_are_rejected(self):
        for value in ("http://example.com/", "https://127.0.0.1", "https://[::1]", "https://a.local/",
                      "https://user@example.com/", "https://example.com:444/", "https://example.com/%0a"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                public_url(value)
        address_info = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ]
        with patch("ghostprint.public_pages.socket.getaddrinfo", return_value=address_info):
            with self.assertRaises(PageUnavailable):
                public_addresses("public-looking.com")
        self.assertIsNone(doc_kind(HOME + "/compare-privacy"))
        self.assertIsNone(doc_kind(HOME + "/privacy/websites/cookie-settings/", "Privacy Policy"))
