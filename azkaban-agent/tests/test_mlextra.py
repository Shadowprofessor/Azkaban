from azkaban_agent.mlextra import BeaconAnomaly


def test_isolation_forest_flags_odd_series_and_suspects_unlisted():
    b = BeaconAnomaly()
    # 9 ordinary app/host pairs: a few irregular, user-driven requests
    for i in range(9):
        for t in (0, 7_000, 31_000, 33_000):
            b.observe(f"app{i}", f"api{i}.example.com", t + i * 13, 2000, 2.0, set(), 0, listed=False)
    # one regular idle beacon carrying an ad ID to an unlisted host
    for n in range(30):
        b.observe("Flashlight", "t.newsdk-metrics.io", n * 60_000, 300, 600.0, {"adid"}, 0, listed=False)
    flagged = {(a["app"], a["host"]) for a in b.detect()}
    assert ("Flashlight", "t.newsdk-metrics.io") in flagged
    sus = b.suspected()
    assert [s["host"] for s in sus] == ["t.newsdk-metrics.io"]
    assert b.suspected() == []   # reported once
