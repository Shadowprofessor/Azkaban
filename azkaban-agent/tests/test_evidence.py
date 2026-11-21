import base64
import json

from azkaban_agent.config import Config
from azkaban_agent.evidence import EvidenceChain, verify
from azkaban_agent.honeytoken import Canary
from azkaban_agent.pipeline import Pipeline

TOK = {"token": "azk0123456789abcdef", "label": "contact Dobby"}


def test_chain_export_verify_and_tamper(tmp_path):
    ch = EvidenceChain("live", True)
    for i in range(3):
        ch.add_flow({"id": str(i), "ts": 1, "app": "a", "host": "h", "severity": 50, "decrypted": True,
                     "pii": [{"type": "email", "redacted": "j***@g***.com", "confidence": 0.9}]})
    ch.add_verdict({"flowId": "1", "status": "violation", "reasoning": "r",
                    "citations": [{"source": "DPDP", "section": "Section 6", "url": "u"}]})
    res = ch.export(tmp_path)
    assert res["path"].endswith(".pdf") and (tmp_path / res["path"].split("\\")[-1].split("/")[-1]).exists()
    ok, msg = verify(res["jsonl"])
    assert ok and res["rootHash"] in msg

    lines = open(res["jsonl"], encoding="utf-8").read().splitlines()
    e = json.loads(lines[2])
    e["data"]["host"] = "innocent.example"
    lines[2] = json.dumps(e, sort_keys=True, separators=(",", ":"))
    bad = tmp_path / "bad.jsonl"
    bad.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, msg = verify(bad)
    assert not ok and "entry 2" in msg

    del lines[1]
    bad.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert not verify(bad)[0]


def test_honeytoken_plain_encoded_hashed():
    p = Pipeline(Config())
    p.canary = Canary([TOK])
    base = {"ts": 1, "app": "Flashlight", "host": "graph.facebook.com", "method": "POST", "path": "/",
            "ip": "", "bytes": 1, "decrypted": True, "headers": {}, "query": ""}
    e = p.process({**base, "id": "1", "body": json.dumps({"contacts": [{"note": TOK["token"]}]})})
    assert e.honey and e.honey[0]["label"] == "contact Dobby" and e.flow.severity >= 95
    b64 = base64.b64encode(f"n={TOK['token']}".encode()).decode()
    e = p.process({**base, "id": "2", "body": f"d={b64}"})
    assert e.honey and "base64" in e.honey[0]["via"]
    import hashlib
    e = p.process({**base, "id": "3", "body": "h=" + hashlib.sha256(TOK["token"].encode()).hexdigest()})
    assert e.honey and e.honey[0]["via"] == "sha256"
    assert TOK["token"] not in json.dumps(e.honey)
