import json

from azkaban_agent.config import Config
from azkaban_agent.legal import LegalEngine, build_facts
from azkaban_agent.pipeline import Pipeline
from azkaban_agent.rag_stub import retrieve


def enriched():
    p = Pipeline(Config())
    return p.process({"id": "f1", "ts": 1, "app": "Flashlight Pro", "host": "graph.facebook.com", "method": "POST",
                      "path": "/", "ip": "157.240.16.35", "bytes": 900, "decrypted": True, "headers": {},
                      "query": "", "body": "email=jane.doe@gmail.com&lat=12.971599&lng=77.594566", "tsi": 0})


def test_facts_are_structured_only():
    f = build_facts(enriched(), "IN")
    s = json.dumps(f)
    assert "jane" not in s and "12.97" not in s and "j***" not in s
    assert f["pii_types"] == ["email", "gps"] and f["cross_border"] is True and f["app_category"] == "utility"


def test_stub_retrieves_consent_and_cross_border():
    docs = retrieve({"consent": False, "cross_border": True, "is_tracker": True, "pii_types": ["gps"]})
    secs = [d["section"] for d in docs]
    assert "Section 6" in secs and "Section 16" in secs


def test_validate_drops_invented_sections():
    law = [{"section": "Section 6", "source": "DPDP", "url": "u", "text": "..."}]
    r = LegalEngine._validate(json.dumps({"status": "violation", "reasoning": "Breaches Section 6 and Section 99.",
                                          "citations": ["Section 6", "Section 99"]}), law)
    assert [c["section"] for c in r["citations"]] == ["Section 6"]
    assert "section 99" in r["reasoning"].lower() and "removed" in r["reasoning"]
    r2 = LegalEngine._validate('{"status": "violation", "reasoning": "bad", "citations": []}', law)
    assert r2["status"] == "questionable"


def test_rag_down_says_law_unavailable():
    eng = LegalEngine(Config())
    eng.retrieve = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("index offline"))
    v = eng.verdict("f1", build_facts(enriched(), "IN"))
    assert v.status == "questionable" and v.reasoning.startswith("Law unavailable") and v.citations == []


def test_llm_down_returns_none():
    eng = LegalEngine(Config(ollama_url="http://127.0.0.1:9"))
    assert eng.verdict("f1", build_facts(enriched(), "IN")) is None


def test_subsection_references_map_to_parent():
    law = [{"section": "Section 6", "source": "DPDP", "url": "u", "text": "..."},
           {"section": "Section 2(t)", "source": "DPDP", "url": "u", "text": "..."}]
    r = LegalEngine._validate(json.dumps({"status": "violation", "reasoning": "Per Section 6(1) and Section 2(t).",
                                          "citations": []}), law)
    assert sorted(c["section"] for c in r["citations"]) == ["Section 2(t)", "Section 6"]
    assert "removed" not in r["reasoning"] and r["status"] == "violation"


def test_hedged_violation_downgraded():
    law = [{"section": "Section 6", "source": "DPDP", "url": "u", "text": "..."}]
    r = LegalEngine._validate(json.dumps({"status": "violation", "citations": ["Section 6"],
                                          "reasoning": "Consent is questionable (Section 6(1))."}), law)
    assert r["status"] == "questionable"
