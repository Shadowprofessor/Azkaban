from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from .audit import audit
from .cases import CASES, HOLDOUT
from .demo import write_demo
from .model import bridge_rank
from .retrieval import retrieve


def evaluate(model_server=None):
    results = {}
    runs = [("BM25", CASES), ("Metadata + BM25", CASES),
            ("Holdout BM25", HOLDOUT), ("Holdout metadata", HOLDOUT)]
    if model_server:
        runs.append(("Nemotron bridge", CASES))
    for mode, cases in runs:
        rows = []
        for case, question, expected in cases:
            started = perf_counter()
            ids = [guide["id"] for guide in retrieve(question, baseline=mode in {"BM25", "Holdout BM25"})]
            error = None
            if mode == "Nemotron bridge":
                try:
                    ids = bridge_rank(model_server, case)
                except (RuntimeError, ValueError) as exc:
                    error = str(exc)
                    ids = []
            rows.append({
                "case": case, "expected": expected, "ids": ids,
                "rank": ids.index(expected) + 1 if expected in ids else 0,
                "latency_ms": round((perf_counter() - started) * 1000, 3),
                "error": error,
            })
        positives = [row for row in rows if row["expected"]]
        negatives = [row for row in rows if not row["expected"]]
        results[mode] = {
            "top_1": sum(row["rank"] == 1 for row in positives) / len(positives),
            "recall_at_5": sum(row["rank"] > 0 for row in positives) / len(positives),
            "mrr_at_5": sum(1 / row["rank"] for row in positives if row["rank"]) / len(positives),
            "correct_abstentions": sum(not row["ids"] and not row["error"] for row in negatives),
            "negative_count": len(negatives),
            "positive_count": len(positives),
            "median_ms": round(median(row["latency_ms"] for row in rows), 3),
            "errors": sum(row["error"] is not None for row in rows),
            "cases": rows,
        }
    with TemporaryDirectory() as directory:
        demo = Path(directory) / "demo.zip"
        write_demo(demo)
        report = audit([(demo, None)])
    expected_findings = {
        ("Google", "location"): (12, "google-timeline"),
        ("Google", "activity"): (10, "google-activity"),
        ("Google", "contacts"): (4, "google-contacts"),
        ("Instagram", "connections"): (8, "instagram-network"),
        ("Instagram", "contacts"): (3, "instagram-contacts"),
        ("Instagram", "messages"): (5, "instagram-messages"),
        ("Instagram", "interests"): (1, "instagram-ads"),
        ("Spotify", "activity"): (6, "spotify-listening"),
        ("Spotify", "location"): (6, "spotify-location"),
        ("Spotify", "security"): (6, "spotify-security"),
        ("Spotify", "interests"): (1, "spotify-ads"),
    }
    observed = {(row["platform"], row["category"]): (row["count"], (row["guide"] or {}).get("id"))
                for row in report["findings"]}
    checks = {
        "findings_and_sources": observed == expected_findings,
        "location_ranked_first": report["findings"][0]["category"] == "location",
        "activity_hour_peak": report["activity_utc"]["Spotify"][18] == 3,
        "repeat_artist_inference": report["interest_signals"][0] == {"artist": "Juniper Circuit", "plays": 3},
    }
    return {"retrieval": results, "archive_smoke_test": checks}
