import json
from pathlib import Path

import numpy as np
import pytest

from azkaban_agent.config import DATA_DIR, Config
from azkaban_agent.session import read_session
from azkaban_agent.tracker_clf import TrackerClassifier, insight
from azkaban_agent.tracker_features import DEPLOYED, AVAILABILITY, group_key, lexical
from azkaban_agent.trackers import TrackerDB

DEMO = Path(__file__).resolve().parents[1] / "demo" / "demo.azk"
DATASET = Path(__file__).resolve().parents[2] / "train" / "data" / "tracker_dataset.parquet"
META = json.loads((DATA_DIR / "tracker_clf_meta.json").read_text())


def test_onnx_loads_and_predicts_probabilities():
    clf = TrackerClassifier()
    assert clf.available
    p, cat = clf.score("example-unlisted.com")
    assert 0.0 <= p <= 1.0 and cat in META["classes"]


def test_feature_contract_matches_runtime():
    assert META["features"] == DEPLOYED
    assert set(META["impute_medians"]) == set(DEPLOYED)
    assert all(AVAILABILITY[f] in ("browser", "agent") for f in DEPLOYED), "global-only stats must never be deployed"
    assert META["onnx_parity_max_abs_err"]["binary"] <= 1e-4
    assert META["onnx_parity_max_abs_err"]["category"] <= 1e-4


def test_lexical_features_are_deterministic():
    a, b = lexical("px.quietpixel.io"), lexical("cdn.quietpixel.io")
    assert a == b  # computed on the registrable domain


@pytest.mark.skipif(not DATASET.exists(), reason="dataset not built (python train/build_dataset.py)")
def test_groupkfold_split_is_leakage_free():
    import pandas as pd
    from sklearn.model_selection import GroupKFold
    df = pd.read_parquet(DATASET)
    real = df[df.is_real_behavior].reset_index(drop=True)
    groups = real.domain.map(group_key)
    assert real.domain.is_unique  # deduplicated to the registrable domain
    for tr, te in GroupKFold(n_splits=5).split(real, real.label, groups):
        assert not set(groups.iloc[tr]) & set(groups.iloc[te])


def _feed(clf: TrackerClassifier, host: str, rec: dict, n: int):
    db = TrackerDB()
    for i in range(n):
        r = {"host": host, "app": "T", "ts": i * 60_000, **rec}
        clf.observe(r, listed=db.lookup(host)[0] is not None)


def test_demo_unlisted_tracker_fires_once_with_exact_shape():
    clf = TrackerClassifier()
    db = TrackerDB()
    for r in read_session(DEMO):
        clf.observe(r, listed=db.lookup(r["host"])[0] is not None)
    cands = clf.candidates()
    doms = [c["domain"] for c in cands]
    assert "quietpixel.io" in doms, f"model did not flag the unlisted demo tracker (got {doms})"
    assert not any(db.lookup("x." + d)[0] for d in doms), "listed trackers must never be reported as unknown"
    assert clf.candidates() == []  # reported once
    msg = insight(next(c for c in cands if c["domain"] == "quietpixel.io"))
    assert set(msg) == {"type", "key", "kind", "level", "title", "detail", "data"}
    assert msg["kind"] == "unknown_tracker" and msg["level"] == "warn"
    assert msg["title"] == "Likely tracker not on any list: quietpixel.io"
    assert set(msg["data"]) == {"domain", "category", "confidence", "topFeatures"}
    assert "flagged by behaviour+structure, not a blocklist" in msg["detail"]


def test_benign_static_host_is_not_flagged():
    clf = TrackerClassifier()
    _feed(clf, "assets.mystaticfiles.net",
          {"method": "GET", "path": "/lib/app.css", "query": "", "resp_type": "text/css", "bytes": 48_000,
           "headers": {}, "status": 200}, n=5)
    _feed(clf, "assets.mystaticfiles.net",
          {"method": "GET", "path": "/fonts/a.woff2", "query": "", "resp_type": "font/woff2", "bytes": 90_000,
           "headers": {}, "status": 200}, n=5)
    p, _ = clf.score("mystaticfiles.net")
    assert p < clf.threshold, p


def test_missing_model_degrades_silently(tmp_path):
    clf = TrackerClassifier(path=tmp_path / "nope.onnx")
    assert not clf.available
    clf.observe({"host": "a.b.com", "ts": 1}, listed=False)
    assert clf.candidates() == []


def test_agent_emits_unknown_tracker_on_demo_replay():
    from azkaban_agent.agent import Agent
    agent = Agent(Config(), mode="replay")
    published = []
    agent.hub.publish = lambda m, keep=True: published.append(m)
    for r in read_session(DEMO):
        agent.on_raw(dict(r))
    msgs = agent._ml_insights()
    unk = [m for m in msgs if m.get("kind") == "unknown_tracker"]
    assert [m["data"]["domain"] for m in unk] == ["quietpixel.io"]
