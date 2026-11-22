import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from ghostprint.analyst import analyze, is_personal_question
from ghostprint.audit import audit
from ghostprint.demo import write_demo
from ghostprint.web_activity import WebActivity


class AnalystTest(unittest.TestCase):
    def test_discovery_and_cross_platform_timeline(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "demo.zip"
            write_demo(archive)
            report = audit([(archive, None)])
        contacts = analyze("Which companies have my contacts?", report)
        self.assertEqual({item["platform"] for item in contacts["claims"]}, {"Google", "Instagram"})
        self.assertTrue(all(item["confidence"]["level"] == "High" for item in contacts["claims"]))
        interests = analyze("What was I interested in during 2025?", report)
        ai = next(item for item in interests["claims"] if item.get("topic") == "Artificial intelligence")
        self.assertEqual(ai["confidence"]["level"], "Medium")
        self.assertEqual({fact["source"].split(" · ")[0] for fact in ai["evidence"]},
                         {"Google", "Spotify", "YouTube"})
        self.assertEqual(analyze("What was I interested in during 2024?", report)["claims"], [])
        self.assertEqual(analyze("What is my income?", report)["claims"], [])
        self.assertEqual(analyze("What is my home address?", report)["claims"], [])
        self.assertIn("insufficient", analyze("When do I sleep?", report)["answer"])
        self.assertEqual(analyze("What is differential privacy?", report)["claims"], [])
        self.assertIn("Google", analyze("What should I delete first?", report)["actions"][0]["title"])
        self.assertIn({"field": "Age range", "value": "Undetermined", "confidence": "Low"},
                      analyze("What could a data broker infer?", report)["profile"])

    def test_additional_archives_and_safe_evidence(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "mixed.zip"
            with ZipFile(archive, "w") as bundle:
                samples = {
                    "facebook/your_off_facebook_activity.json": {"off_facebook_activity_v2": [{"name": "Private Example"}]},
                    "user_data_tiktok.json": {"Activity": {"Video Browsing History": {"VideoList": [
                        {"Date": "2025-05-03", "Link": "https://private.example/path"}
                    ]}}},
                    "discord/messages/c012/messages.json": [{"Timestamp": "2025-04-01", "Contents": "Private prose"}],
                    "Takeout/Chrome/History.json": {"Browser History": [{"title": "A fitness workout", "time_usec": 1735689600000000}]},
                    "Takeout/Location History/Semantic Location History/2025/2025_JANUARY.json": {
                        "timelineObjects": [{"placeVisit": {"location": {"city": "Pune", "latitudeE7": 123456789,
                                             "longitudeE7": 876543210, "semanticType": "HOME"},
                                             "duration": {"startTimestamp": "2025-01-03T01:02:03Z"}}}]
                    },
                }
                for name, data in samples.items():
                    bundle.writestr(name, json.dumps(data))
                bundle.writestr("linkedin/Positions.csv", "Company Name,Title\nPrivate Co,Private position\n")
                bundle.writestr("linkedin/Education.csv", "School Name,Degree Name\nPrivate school,Private degree\n")
                bundle.writestr("Retail.OrderHistory.1.csv",
                                "Order Date,Product Name\n2025-02-01,A photography guide\n")
                bundle.writestr("twitter/data/tweets.js",
                                'window.YTD.tweets.part0 = [{"tweet":{"created_at":"2025-01-03T01:02:03Z"}}];')
            report = audit([(archive, None)])
        expected = {"Google", "Facebook", "LinkedIn", "Twitter/X", "TikTok", "Discord", "Amazon", "Browser History"}
        self.assertEqual({row["platform"] for row in report["analyst_sources"]}, expected)
        addresses = analyze("What is my home address?", report)
        self.assertEqual(addresses["risk"]["level"], "Critical")
        self.assertNotIn("123456789", json.dumps(addresses))
        self.assertIn("Pune", analyze("Which cities did I visit in 2025?", report)["answer"])
        broker = analyze("What could a data broker infer?", report)
        self.assertNotIn("Private", json.dumps(broker))
        self.assertTrue(any("recipients" in line for line in
                            analyze("What third-party sharing appears in my Facebook data?", report)["limitations"]))

    def test_live_permissions_and_routing(self):
        activity = WebActivity()
        activity.add("private.example", [], {"camera": "granted", "notifications": "denied"})
        answer = analyze("Which websites have excessive permissions?", {}, activity.snapshot(), activity.permissions())
        self.assertIn("camera (1)", json.dumps(answer))
        self.assertNotIn("private.example", json.dumps(answer))
        self.assertTrue(any("excessive" in line for line in answer["limitations"]))
        activity.clear()
        self.assertEqual(activity.permissions(), {})
        for prompt in ("What does Google know about me?", "What was I interested in during 2025?",
                       "What should I delete first?", "Where do I live?"):
            self.assertTrue(is_personal_question(prompt), prompt)
        for prompt in ("How do I delete my Google history?", "What is differential privacy?"):
            self.assertFalse(is_personal_question(prompt), prompt)
