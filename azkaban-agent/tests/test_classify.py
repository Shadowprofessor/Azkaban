import json

from azkaban_agent import pii, tcf
from azkaban_agent.config import Config
from azkaban_agent.fields import record_fields
from azkaban_agent.pipeline import Pipeline


def raw(**kw):
    base = {"id": "x", "ts": 1, "app": "t", "host": "example.com", "method": "POST", "path": "/",
            "ip": "8.8.8.8", "bytes": 10, "decrypted": True, "headers": {}, "query": "", "body": ""}
    base.update(kw)
    return base


def types(findings):
    return sorted({f.type for f in findings})


def test_email_phone_imei_adid_gps():
    body = json.dumps({
        "user": {"email": "Jane.Doe@gmail.com", "mobile": "9876543210"},
        "device": {"imei": "490154203237518", "gaid": "38400000-8cf0-11bd-b23e-10b96e40000d"},
        "loc": {"lat": "12.971599", "lng": "77.594566"},
    })
    f = pii.scan(record_fields(raw(body=body)))
    assert types(f) == ["adid", "email", "gps", "imei", "phone"]
    hits = {h.type: h.redacted for h in (x.hit() for x in f)}
    assert "Jane" not in hits["email"] and hits["email"].endswith(".com")
    assert hits["phone"].endswith("210") and "98765" not in hits["phone"]
    assert "38400000-8cf0" not in hits["adid"]
    assert hits["gps"].startswith("13.0,77.6")


def test_no_false_adid_without_key():
    f = pii.scan(record_fields(raw(query="request_id=38400000-8cf0-11bd-b23e-10b96e40000d")))
    assert not f


def test_contacts_and_clipboard():
    body = json.dumps({"contacts": [{"n": "a", "phone": "+14155550101"}, {"n": "b", "phone": "+14155550102"},
                                    {"n": "c", "phone": "+14155550103"}], "clipboard_text": "secret"})
    t = types(pii.scan(record_fields(raw(body=body))))
    assert "contact" in t and "clipboard" in t and "phone" in t


def test_redaction_never_leaks_raw_in_flow():
    p = Pipeline(Config())
    e = p.process(raw(host="app-measurement.com", body="email=alice.smith@example.org&adid=38400000-8cf0-11bd-b23e-10b96e40000d"))
    s = json.dumps(e.flow.to_dict())
    assert "alice.smith" not in s and "38400000-8cf0-11bd" not in s
    assert e.flow.tracker and e.flow.tracker.name == "Google Firebase Analytics"
    assert e.flow.company


def test_tracker_suffix_and_company():
    p = Pipeline(Config())
    e = p.process(raw(host="stats.g.doubleclick.net"))
    assert e.flow.tracker is not None and e.flow.company


def test_pinned_flow_has_no_pii_scan():
    p = Pipeline(Config())
    e = p.process(raw(decrypted=False, body="email=a@b.com"))
    assert e.flow.pii == [] and e.flow.decrypted is False


def test_tcf_decode():
    s = tcf.encode([1, 2, 3, 4, 7, 10], [1, 2, 755, 793])
    t = tcf.decode(s)
    assert t is not None
    assert t.purposes == [1, 2, 3, 4, 7, 10]
    assert t.vendors == [1, 2, 755, 793]


def test_contact_array_reported_once_and_advertiser_id():
    body = json.dumps({"advertiser_id": "6f1c2a9e-4b7d-4e21-9c3a-5d8e7f0a1b2c",
                       "contacts": [{"name": "a", "phone": "+15555550101"}, {"name": "b", "phone": "+15555550102"},
                                    {"name": "c", "phone": "+15555550103"}]})
    f = pii.scan(record_fields(raw(body=body)))
    assert [x.type for x in f].count("contact") == 1
    assert "adid" in types(f)
