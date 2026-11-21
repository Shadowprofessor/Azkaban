"""No demo identifier ever leaves the agent in raw form: not on the WebSocket, not in
any published message, not in the exported evidence chain."""
import hashlib

from azkaban_agent.demo import HONEYTOKEN, IDENTITY, IMEI, LAT, LNG

from replay_harness import run_demo

RAW = [
    *IDENTITY["emails"], *IDENTITY["phones"], *IDENTITY["adids"],
    IDENTITY["phones"][0].lstrip("+"),             # digits-only phone
    IDENTITY["phones"][0][-10:],                   # national number
    IMEI, LAT, LNG,
    "+15555550101", "+15555550102", "+15555550103",  # contact list numbers
    HONEYTOKEN["token"],
    hashlib.sha256(IDENTITY["emails"][0].encode()).hexdigest(),  # the hash sent is itself an identifier
]


def test_no_raw_identifier_in_any_output():
    res = run_demo()
    outputs = {
        "published": "\n".join(res["published"]),
        "websocket": "\n".join(res["received"]),
        "evidence": "\n".join(res["evidence"]),
    }
    assert all(outputs.values()), "every channel must have produced output"
    for channel, text in outputs.items():
        low = text.lower()
        for raw in RAW:
            assert raw.lower() not in low, f"raw identifier {raw!r} leaked via {channel}"


def test_redacted_forms_are_present():
    """Guard against a vacuous pass: findings must be there, just redacted."""
    text = "\n".join(run_demo()["published"])
    for marker in ('"type": "email"', '"type": "adid"', '"type": "gps"', "sha256(", "[base64]"):
        assert marker in text, marker
