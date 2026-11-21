import base64
import gzip
import hashlib
import json

from azkaban_agent.config import Config
from azkaban_agent.pipeline import Pipeline

EMAIL = "Harry.Potter@Hogwarts.test"
ADID = "6f1c2a9e-4b7d-4e21-9c3a-5d8e7f0a1b2c"


def raw(app="a", host="graph.facebook.com", **kw):
    base = {"id": "x", "ts": 1, "app": app, "host": host, "method": "POST", "path": "/", "ip": "",
            "bytes": 10, "decrypted": True, "headers": {}, "query": "", "body": ""}
    base.update(kw)
    return base


def pipe():
    cfg = Config(known_emails=[EMAIL], known_phones=["+91 98765 00042"])
    return Pipeline(cfg)


def test_sha256_md5_sha1_of_email_detected():
    p = pipe()
    for algo in ("sha256", "md5", "sha1"):
        h = hashlib.new(algo, EMAIL.lower().encode()).hexdigest()
        e = p.process(raw(body=json.dumps({"em": h})))
        assert e.hashed_hits == 1, algo
        assert e.flow.pii[0].type == "email"
        assert e.flow.pii[0].redacted.startswith(f"{algo}(")
        assert EMAIL.lower() not in json.dumps(e.flow.to_dict())


def test_uppercase_hash_and_phone_variant():
    p = pipe()
    h = hashlib.sha256(b"9876500042").hexdigest().upper()
    e = p.process(raw(query=f"ph={h}"))
    assert e.hashed_hits == 1 and e.flow.pii[0].type == "phone"


def test_base64_and_gzip_wrapped_identifiers():
    p = pipe()
    b64 = base64.b64encode(json.dumps({"email": "secret.person@mail.test"}).encode()).decode()
    e = p.process(raw(body=json.dumps({"payload": b64})))
    assert any(h.type == "email" and "[base64]" in h.redacted for h in e.flow.pii)

    gz = base64.b64encode(gzip.compress(f"advertising_id={ADID}".encode())).decode()
    e = p.process(raw(body=f"d={gz}"))
    assert any(h.type == "adid" and "base64+gzip" in h.redacted for h in e.flow.pii)

    hx = "phone=+14155550123".encode().hex()
    e = p.process(raw(query=f"blob={hx}"))
    assert any(h.type == "phone" and "[hex]" in h.redacted for h in e.flow.pii)


def test_hash_inside_base64():
    p = pipe()
    h = hashlib.sha256(EMAIL.lower().encode()).hexdigest()
    b64 = base64.b64encode(json.dumps({"uid": h}).encode()).decode()
    e = p.process(raw(body=f"x={b64}"))
    assert e.hashed_hits == 1 and "base64>sha256" in e.findings[0].via


def test_cross_app_correlation():
    p = pipe()
    p.process(raw(app="Flashlight", body=f"advertiser_id={ADID}"))
    e = p.process(raw(app="InstaShop", body=f"advertiser_id={ADID}"))
    assert e.adid_reuse == 2
    assert "same ID from 2 apps" in e.flow.pii[0].redacted
    links = p.correlator.links()
    assert links and set(links[0]["apps"]) == {"Flashlight", "InstaShop"}
