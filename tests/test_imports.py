import io
import json
import unittest
from zipfile import ZipFile

from ghostprint.analyst import analyze
from ghostprint.imports import import_batch


def batch(files, platform=None):
    manifest = json.dumps({
        "files": [{"name": name, "size": len(payload)} for name, payload in files],
        "platform": platform,
    }).encode()
    return len(manifest).to_bytes(4, "big") + manifest + b"".join(payload for _, payload in files)


class ImportReviewTest(unittest.TestCase):
    def test_batch_automatically_analyzes_mixed_exports(self):
        archive = io.BytesIO()
        with ZipFile(archive, "w") as zip_file:
            zip_file.writestr("Takeout/Location History/Records.json",
                              json.dumps({"locations": [{"latitudeE7": 123456789, "longitudeE7": 876543210}]}))
        payload = batch([("takeout.zip", archive.getvalue()),
                         ("StreamingHistory0.json", b'[{"artistName":"Example Artist","endTime":"2025-01-01 12:00"}]')])
        report = import_batch(io.BytesIO(payload), len(payload))
        review = report["review"]
        self.assertEqual(len(report["coverage"]), 2)
        self.assertEqual({row["platform"] for row in report["findings"]}, {"Google", "Spotify"})
        self.assertEqual(review["risk"]["level"], "High")
        self.assertEqual(review["score"], max(claim["score"] for claim in review["claims"]))
        self.assertTrue(review["actions"][0]["title"].startswith("Google"))
        self.assertNotIn("123456789", json.dumps(review))

    def test_unrecognized_file_has_no_score(self):
        data = batch([("unknown.json", b"{}")])
        report = import_batch(io.BytesIO(data), len(data))
        self.assertIsNone(report["review"]["score"])
        self.assertEqual(report["coverage"][0]["unrecognized_files"], 1)

    def test_automatic_review_includes_a_fix_for_every_finding(self):
        rows = [
            {"id": f"Export {number}, file 1", "platform": f"Platform {number}",
             "category": "contacts", "kind": "Contact records", "count": number}
            for number in range(1, 16)
        ]
        rows.append({"id": "Export 16, file 1", "platform": "Uploaded reports", "category": "security",
                     "kind": "Report findings", "count": 1, "origin": "reported",
                     "signal": "Device identifiers or user agents"})
        review = analyze("", {"analyst_sources": rows}, automatic=True)
        self.assertEqual(len(review["claims"]), 16)
        self.assertTrue(all(item["fix"]["steps"] for item in review["claims"]))
        scores = [item["score"] for item in review["claims"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        reported = review["claims"][-1]
        self.assertTrue(reported["reported"])
        self.assertIn("device identifiers", reported["claim"])
        self.assertIn("Check the reported issue", reported["fix"]["steps"][0])
        self.assertIn("mask identifiers", reported["fix"]["steps"][1])

    def test_batch_rejects_unsafe_names_and_incomplete_bodies(self):
        for name in ("../contacts.json", "C:\\contacts.json", "NUL.zip"):
            data = batch([(name, b"{}")])
            with self.assertRaisesRegex(ValueError, "filename"):
                import_batch(io.BytesIO(data), len(data))
        data = batch([("contacts.json", b"{}")], "Instagram")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            import_batch(io.BytesIO(data[:-1]), len(data))
