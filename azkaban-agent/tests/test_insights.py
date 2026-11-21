import hashlib

from azkaban_agent.config import Config
from azkaban_agent.insights import InsightEngine
from azkaban_agent.pipeline import Pipeline

ADID = "6f1c2a9e-4b7d-4e21-9c3a-5d8e7f0a1b2c"


def raw(app, host, body, tsi=0.0, nbytes=1000):
    return {"id": app + host, "ts": 1, "app": app, "host": host, "method": "POST", "path": "/", "ip": "",
            "bytes": nbytes, "decrypted": True, "headers": {}, "query": "", "body": body, "tsi": tsi}


def test_idle_bandwidth_hashed_crossapp():
    p = Pipeline(Config(known_emails=["a@b.test"]))
    ie = InsightEngine()
    msgs = []
    msgs += ie.on_flow(p.process(raw("Flashlight", "graph.facebook.com", f"advertiser_id={ADID}", tsi=300)))
    msgs += ie.on_flow(p.process(raw("Shop", "graph.facebook.com",
                                     f"advertiser_id={ADID}&em={hashlib.sha256(b'a@b.test').hexdigest()}")))
    msgs += ie.periodic()
    kinds = {m["kind"] for m in msgs}
    assert {"idle_beacons", "bandwidth", "hashed_pii", "cross_app"} <= kinds
    idle = next(m for m in msgs if m["kind"] == "idle_beacons")
    assert idle["data"]["count"] == 1 and "phoned home 1 time while" in idle["title"]
    assert all(m["type"] == "insight" and m["key"] for m in msgs)
    assert "a@b.test" not in str(msgs)
