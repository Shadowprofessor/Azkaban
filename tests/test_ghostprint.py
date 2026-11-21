import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile

from ghostprint import model, server
from ghostprint.audit import audit
from ghostprint.evaluation import evaluate
from ghostprint.retrieval import retrieve as public_retrieve


class AuditTest(unittest.TestCase):
    def test_synthetic_archive_and_retrieval(self):
        results = evaluate()
        self.assertTrue(all(results["archive_smoke_test"].values()))
        metrics = results["retrieval"]["Holdout metadata"]
        self.assertGreaterEqual(metrics["top_1"], 0.9)
        self.assertEqual(metrics["recall_at_5"], 1.0)
        self.assertEqual(metrics["correct_abstentions"], metrics["negative_count"])

    def test_archive_values_do_not_enter_retrieval(self):
        private = "person@example.invalid"
        with TemporaryDirectory() as root:
            directory = Path(root) / "input"
            directory.mkdir()
            path = directory / "export.zip"
            with ZipFile(path, "w") as archive:
                archive.writestr("instagram/message_1.json", json.dumps({"messages": [{"content": private}]}))
                archive.writestr("instagram/message_2.json", "[")
                archive.writestr("../escape.txt", private)
            with patch("ghostprint.audit.retrieve", wraps=public_retrieve) as retrieve:
                report = audit([(path, None), (path, None)])
            retrieve.assert_called_once_with("Instagram messages", platform="Instagram", category="messages", k=1)
            self.assertFalse((Path(root) / "escape.txt").exists())
        self.assertNotIn(private, json.dumps(report))
        self.assertEqual(report["coverage"][0]["unreadable_files"], 1)
        self.assertEqual(len(report["coverage"]), 1)

    def test_directory_and_platform_hint(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "contacts.json"
            path.write_text('{"contacts": [{"name": "Fictional"}]}')
            report = audit([(root, "Instagram")])
        self.assertEqual(report["findings"][0]["guide"]["id"], "instagram-contacts")


class ModelTest(unittest.TestCase):
    def test_model_citations_are_allowlisted(self):
        def response(id_):
            content = json.dumps({"ids": [id_]})
            return {"choices": [{"message": {"content": content}}]}

        with patch.dict("os.environ", {"NVIDIA_API_KEY": "test-token"}):
            with patch("ghostprint.model.post", return_value=response("google-timeline")) as post:
                self.assertEqual(model.rank("g5")["ids"], ["google-timeline"])
                self.assertEqual(post.call_args.args[0], model.NVIDIA_URL + "/chat/completions")
            with patch("ghostprint.model.post", return_value=response("invented-id")):
                with self.assertRaisesRegex(RuntimeError, "outside"):
                    model.rank("g5")

    def test_bridge_accepts_only_synthetic_case_ids(self):
        original_server = server.ThreadingHTTPServer
        with original_server(("127.0.0.1", 0), server.Handler) as httpd:
            def start(handler, host, port):
                httpd.RequestHandlerClass = handler
                httpd.serve_forever(poll_interval=0.01)

            with patch("ghostprint.server.run", side_effect=start):
                with patch("ghostprint.server.rank", return_value={"ids": ["google-timeline"]}) as rank:
                    thread = threading.Thread(target=server.bridge, args=("127.0.0.1", 0, "test"),
                                              kwargs={"base": model.NVIDIA_URL, "model": model.MODEL}, daemon=True)
                    thread.start()
                    url = f"http://127.0.0.1:{httpd.server_port}/v1/benchmark"

                    def send(body, key="test"):
                        req = Request(url, json.dumps(body).encode(),
                                      {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
                        return urlopen(req, timeout=3)

                    try:
                        for body, key, status in [
                            ({"case": "g5"}, "wrong", 401),
                            ({"case": "g5", "archive": "fictional export"}, "test", 400),
                            ({"case": "unknown"}, "test", 400),
                        ]:
                            with self.assertRaises(HTTPError) as error:
                                send(body, key)
                            self.assertEqual(error.exception.code, status)
                            error.exception.close()
                        with send({"case": "g5"}) as response:
                            self.assertEqual(json.load(response)["ids"], ["google-timeline"])
                        rank.assert_called_once_with("g5", base=model.NVIDIA_URL, model=model.MODEL)
                    finally:
                        httpd.shutdown()
                        thread.join(timeout=3)
