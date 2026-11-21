"""Retrieval layer: BM25 core, statute ranking, remediation routing, rerank grounding."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag import corpus, guides, query  # noqa: E402
from rag.bm25 import BM25Index, tokens  # noqa: E402
from rag.rerank import RerankFailed, _parse, rerank_law  # noqa: E402


def facts(**kw) -> dict:
    base = dict(pii_types=[], company="Acme", tracker_category=None, is_tracker=False,
                jurisdiction="IN", cross_border=False, consent=True, app="App",
                app_category="other", pii_unexpected_for_app_category=[],
                hashed_identifier=False, same_adid_across_apps=0, while_user_idle=False,
                decrypted=True)
    base.update(kw)
    return base


# ------------------------------------------------------------------ corpora
def test_both_corpora_load_and_validate():
    assert len(corpus.law()) >= 9
    assert len(corpus.guides()) >= 14
    assert all(d["section"] and d["text"] for d in corpus.law())
    assert all(g["id"] and g["steps"] for g in corpus.guides())


def test_guide_ids_are_unique():
    ids = [g["id"] for g in corpus.guides()]
    assert len(ids) == len(set(ids))


# ------------------------------------------------------------------ bm25
def test_tokens_drops_stopwords_and_casing():
    assert tokens("The Consent of a Data Principal") == ["consent", "data", "principal"]


def test_bm25_ranks_the_matching_document_first():
    docs = [{"id": "a", "t": "consent notice"}, {"id": "b", "t": "cross border transfer abroad"}]
    ix = BM25Index(docs, lambda d: d["t"])
    assert ix.search("cross border transfer")[0][1]["id"] == "b"


def test_bm25_returns_nothing_for_an_unrelated_query():
    ix = BM25Index([{"t": "consent notice"}], lambda d: d["t"])
    assert ix.search("quantum chromodynamics") == []


def test_bm25_is_deterministic_under_ties():
    docs = [{"id": "b", "t": "same words"}, {"id": "a", "t": "same words"}]
    ix = BM25Index(docs, lambda d: d["t"])
    got = [d["id"] for _, d in ix.search("same words", tie_key=lambda d: d["id"])]
    assert got == ["a", "b"]


def test_bm25_handles_an_empty_corpus():
    assert BM25Index([], lambda d: "").search("anything") == []


# ------------------------------------------------------------------ statute retrieval
def test_consent_section_is_always_returned():
    for f in (facts(), facts(is_tracker=True), facts(consent=False)):
        assert "Section 6" in [d["section"] for d in query.retrieve(f)]


def test_cross_border_triggers_section_16():
    assert "Section 16" in [d["section"] for d in query.retrieve(facts(cross_border=True))]
    assert "Section 16" not in [d["section"] for d in query.retrieve(facts(), k=3)]


def test_tracker_triggers_processor_obligations():
    assert "Section 8" in [d["section"] for d in query.retrieve(facts(is_tracker=True))]


def test_children_section_only_for_a_children_app():
    assert "Section 9" in [d["section"] for d in query.retrieve(facts(child_app=True))]
    assert "Section 9" not in [d["section"] for d in query.retrieve(facts(), k=4)]


def test_k_never_drops_a_legally_required_section():
    f = facts(cross_border=True, is_tracker=True, child_app=True)
    got = [d["section"] for d in query.retrieve(f, k=1)]
    assert set(got) >= {"Section 6", "Section 16", "Section 8", "Section 9"}


def test_retrieve_returns_the_fields_the_legal_engine_needs():
    # legal.py filters on section+text and renders source+url.
    d = query.retrieve(facts())[0]
    assert {"source", "section", "text", "url"} <= set(d)
    assert d["text"].strip()


def test_no_duplicate_sections_are_returned():
    got = [d["section"] for d in query.retrieve(facts(cross_border=True, is_tracker=True), k=9)]
    assert len(got) == len(set(got))


def test_hashed_identifier_surfaces_the_personal_data_definition():
    # "Is a hash still personal data?" is answered by Section 2(t).
    got = [d["section"] for d in query.retrieve(facts(hashed_identifier=True), k=6)]
    assert "Section 2(t)" in got


def test_retrieve_accepts_a_plain_string_query():
    assert query.retrieve("cross border transfer outside india", k=3)


def test_explain_names_every_returned_section():
    text = query.explain(facts(cross_border=True), k=4)
    for d in query.retrieve(facts(cross_border=True), k=4):
        assert d["section"] in text


# ------------------------------------------------------------------ remediation
@pytest.mark.parametrize("target,expected", [
    ("doubleclick.net", "Google"), ("google-analytics.com", "Google"),
    ("Meta", "Instagram"), ("Spotify", "Spotify"), ("quietpixel.io", None),
])
def test_platform_mapping(target, expected):
    assert guides.platform_for(target) == expected


def test_a_specific_pii_type_outranks_the_mechanism():
    # GPS has a location setting to change, even when found via ad-ID profiling.
    r = guides.remediate(company="Google", kind="cross_app", pii_types=["gps"])
    assert r["category"] == "location"
    assert r["source"] == "guide"


def test_an_identifier_leak_routes_to_ad_settings():
    r = guides.remediate(company="Google", kind="hashed_pii", pii_types=["email"])
    assert r["category"] == "interests"


def test_unknown_destination_still_gets_actionable_steps():
    r = guides.remediate(host="quietpixel.io", kind="unknown_tracker")
    assert r["source"] == "generic"
    assert len(r["steps"]) >= 2
    assert not r["guideId"]


def test_every_remediation_has_steps_and_a_title():
    for kind in ("unknown_tracker", "hashed_pii", "cross_app", "honeytoken", "idle_beacons"):
        for target in ("Google", "Meta", "Spotify", "weird-domain.example"):
            r = guides.remediate(company=target, kind=kind, pii_types=["adid"])
            assert r["title"] and r["steps"], (kind, target)


def test_guide_sourced_remediation_carries_a_url():
    r = guides.remediate(company="Meta", kind="honeytoken", pii_types=["contact"])
    assert r["source"] == "guide"
    assert r["url"].startswith("http")


# ------------------------------------------------------------------ rerank grounding
def test_rerank_accepts_a_valid_ordering():
    assert _parse('{"ids": ["Section 8", "Section 6"]}', {"Section 6", "Section 8"}) == \
        ["Section 8", "Section 6"]


def test_rerank_strips_a_code_fence():
    assert _parse('```json\n{"ids": ["Section 6"]}\n```', {"Section 6"}) == ["Section 6"]


@pytest.mark.parametrize("raw", [
    '{"ids": ["Section 99"]}',            # outside the retrieved context
    '{"ids": ["Section 6", "Section 6"]}',  # duplicate
    '{"ids": "Section 6"}',               # not a list
    '{"ids": [6]}',                       # not strings
    "not json at all",
    '{"other": []}',
])
def test_rerank_rejects_ungrounded_output(raw):
    with pytest.raises(RerankFailed):
        _parse(raw, {"Section 6", "Section 8"})


class _Client:
    """Stand-in for NimClient: no network."""
    configured = True

    def __init__(self, reply):
        self.reply = reply

    def chat(self, *a, **kw):
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_rerank_reorders_on_a_good_reply():
    docs = [{"section": "Section 6", "text": "x"}, {"section": "Section 8", "text": "y"}]
    out = rerank_law(facts(), docs, _Client('{"ids": ["Section 8", "Section 6"]}'))
    assert [d["section"] for d in out] == ["Section 8", "Section 6"]


def test_rerank_keeps_bm25_order_when_the_model_misbehaves():
    docs = [{"section": "Section 6", "text": "x"}, {"section": "Section 8", "text": "y"}]
    for reply in ('{"ids": ["Section 99"]}', RuntimeError("endpoint down"), "garbage"):
        out = rerank_law(facts(), docs, _Client(reply))
        assert [d["section"] for d in out] == ["Section 6", "Section 8"]


def test_rerank_never_drops_a_required_section():
    docs = [{"section": "Section 6", "text": "x"}, {"section": "Section 16", "text": "y"},
            {"section": "Section 5", "text": "z"}]
    # Model returns only one section; the trigger must survive.
    out = rerank_law(facts(cross_border=True), docs, _Client('{"ids": ["Section 5"]}'),
                     keep={"Section 6", "Section 16"})
    got = [d["section"] for d in out]
    assert {"Section 6", "Section 16"} <= set(got)
    assert len(got) == 3


def test_rerank_is_a_no_op_without_a_client():
    docs = [{"section": "Section 6", "text": "x"}, {"section": "Section 8", "text": "y"}]
    assert rerank_law(facts(), docs, None) == docs
