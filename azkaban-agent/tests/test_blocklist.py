from azkaban_agent.blocklist import Blocklist, host_blocked
from azkaban_agent.schema import Flow, PiiHit, Tracker


def flow(host, pii=True, tracker=True, sev=80, ip="1.2.3.4"):
    return Flow(id=host, ts=1, app="a", host=host, method="POST", path="/", ip=ip, company="Co",
                tracker=Tracker("T", "Ads") if tracker else None,
                pii=[PiiHit("adid", "x", 0.9)] if pii else [], severity=sev)


def test_generate_formats_and_recheck():
    bl = Blocklist()
    for h in ("graph.facebook.com", "graph.facebook.com", "app-measurement.com"):
        bl.observe(flow(h))
    bl.observe(flow("example.com", pii=False, tracker=False, sev=5))
    hosts = bl.generate()
    assert hosts[0] == "graph.facebook.com" and "example.com" not in hosts
    f = bl.formats()
    assert "0.0.0.0 graph.facebook.com" in f["hosts"]
    assert "app-measurement.com" in f["pihole"] and "app-measurement.com" in f["nextdns"]
    assert "<azkaban_patronus>" in f["pf"] and "1.2.3.4" in f["pf"]

    blocked = bl.apply(current_score=500)
    assert bl.recheck() == {"baseline": 3, "current": 0, "delta": -3}
    assert host_blocked("sub.graph.facebook.com", blocked) and not host_blocked("facebook.com", blocked)
    bl.observe(flow("other-tracker.net"))
    assert bl.recheck()["delta"] == -2
    msg = bl.message()
    assert msg["type"] == "blocklist" and msg["applied"] and set(msg["formats"]) == {"hosts", "pihole", "nextdns", "pf"}
