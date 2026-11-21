"""Insight enrichment: remediation is attached where it helps and nowhere else."""
from __future__ import annotations

from azkaban_agent import remediate
from azkaban_agent.tracker_clf import insight as tracker_insight


def ins(kind: str, **data) -> dict:
    return {"type": "insight", "key": "k", "kind": kind, "level": "warn",
            "title": "t", "detail": "d", "data": data}


def test_retrieval_layer_is_importable_from_the_repo_root():
    assert remediate.available()


def test_unknown_tracker_insight_gets_remediation():
    msg = tracker_insight({"domain": "quietpixel.io", "category": "advertising",
                           "confidence": 0.92, "topFeatures": []})
    out = remediate.enrich(msg)
    r = out["data"]["remediation"]
    assert r["steps"] and r["title"]
    assert r["source"] in ("guide", "generic")


def test_known_company_gets_a_real_guide_with_a_url():
    out = remediate.enrich(ins("hashed_pii", company="Google", host="google-analytics.com",
                               type="email"))
    r = out["data"]["remediation"]
    assert r["source"] == "guide"
    assert r["url"].startswith("http")


def test_non_remediable_kinds_pass_through_untouched():
    for kind in ("recheck", "bandwidth", "dns_bypass"):
        out = remediate.enrich(ins(kind, company="Google"))
        assert "remediation" not in out["data"]


def test_messages_without_a_subject_are_left_alone():
    assert "remediation" not in remediate.enrich(ins("unknown_tracker"))["data"]


def test_non_insight_messages_are_untouched():
    msg = {"type": "flow", "flow": {"host": "x"}}
    assert remediate.enrich(msg) is msg


def test_enrich_does_not_mutate_the_input():
    msg = ins("unknown_tracker", domain="quietpixel.io")
    before = dict(msg["data"])
    out = remediate.enrich(msg)
    assert msg["data"] == before            # original untouched
    assert "remediation" in out["data"]     # copy enriched


def test_existing_remediation_is_not_overwritten():
    msg = ins("unknown_tracker", domain="quietpixel.io", remediation={"title": "mine"})
    assert remediate.enrich(msg)["data"]["remediation"] == {"title": "mine"}


def test_pii_types_are_read_from_either_spelling():
    for key in ("piiTypes", "pii_types"):
        out = remediate.enrich(ins("cross_app", company="Google", **{key: ["gps"]}))
        assert out["data"]["remediation"]["category"] == "location"


def test_remediation_carries_no_raw_values():
    # Only structured labels may travel with an insight.
    out = remediate.enrich(ins("hashed_pii", company="Google", type="email"))
    blob = repr(out["data"]["remediation"]).lower()
    assert "@" not in blob


def test_honeytoken_field_infers_the_data_type():
    # The canary insight names the field it leaked from but carries no PII type, and the
    # field is what tells us which control to send the user to.
    cases = {"contacts[3].note": "contacts", "clipboard": "activity",
             "loc.latlng": "location", "user.email": "security"}
    for field, category in cases.items():
        out = remediate.enrich(ins("honeytoken", company="Facebook, Inc.",
                                   host="graph.facebook.com", field=field))
        assert out["data"]["remediation"]["category"] == category, field


def test_a_leaked_contact_card_routes_to_contact_controls():
    out = remediate.enrich(ins("honeytoken", company="Facebook, Inc.", field="contacts[3].note"))
    r = out["data"]["remediation"]
    assert r["category"] == "contacts"
    assert "contact" in r["title"].lower()


def test_an_unrecognised_platform_never_borrows_another_vendors_guide():
    # A Facebook leak must not be answered with a Spotify page.
    out = remediate.enrich(ins("honeytoken", company="Facebook, Inc.", field="loc.latlng"))
    r = out["data"]["remediation"]
    assert r["source"] == "generic"
    assert r["platform"] == ""
