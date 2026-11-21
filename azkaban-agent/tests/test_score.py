from azkaban_agent.config import Config
from azkaban_agent.pipeline import Pipeline
from azkaban_agent.score import ExposureScore, Fact


def F(host, company, tracker=True, pii=(), xb=True, consent=False, hashed=0):
    return Fact(host, company, tracker, frozenset(pii), xb, consent, hashed)


def test_score_bounds_and_remediation_order():
    s = ExposureScore()
    assert s.score().total == 0
    s.add(F("graph.facebook.com", "Meta", pii=("contact", "gps", "adid")))
    s.add(F("app-measurement.com", "Google", pii=("adid",)))
    s.add(F("x.appsflyer.com", "AppsFlyer", pii=("email",), hashed=1))
    sc = s.score()
    assert 0 < sc.total <= 1000
    assert {c.name for c in sc.categories} == {"tracker_breadth", "pii_sensitivity", "consent_violations",
                                              "cross_border", "hashed_pii"}
    rem = s.remediation()
    assert rem[0]["target"] in ("Meta", "AppsFlyer")
    assert all(rem[i]["reduction"] >= rem[i + 1]["reduction"] for i in range(len(rem) - 1))


def test_severity_ranks_bad_flow_above_benign():
    p = Pipeline(Config())
    base = {"ts": 1, "method": "POST", "path": "/", "ip": "157.240.16.35", "bytes": 2000, "decrypted": True,
            "headers": {}, "query": ""}
    bad = p.process({**base, "id": "1", "app": "Flashlight Pro", "host": "graph.facebook.com",
                     "body": "advertiser_id=6f1c2a9e-4b7d-4e21-9c3a-5d8e7f0a1b2c&lat=12.971599&lng=77.594566"})
    benign = p.process({**base, "id": "2", "app": "curl", "host": "example.com", "ip": "", "body": "q=hello"})
    assert p.severity.available
    assert bad.flow.severity > 60 > benign.flow.severity
