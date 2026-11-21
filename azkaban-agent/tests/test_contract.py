"""Guards the frozen contract: Python dataclasses must serialise to lib/schema.ts field names."""
import re
from pathlib import Path

from azkaban_agent.schema import Citation, Flow, PiiHit, Score, ScoreCategory, Tracker, Verdict, PII_TYPES

SCHEMA_TS = Path(__file__).resolve().parents[2] / "lib" / "schema.ts"


def _ts_fields(iface: str) -> set[str]:
    src = SCHEMA_TS.read_text(encoding="utf-8")
    body = re.search(r"interface %s \{(.*?)\n\}" % iface, src, re.S).group(1)
    body = re.sub(r"/\*.*?\*/|//[^\n]*", "", body, flags=re.S)
    return set(re.findall(r"^\s{2}(\w+)\s*:", body, re.M))


def test_flow_fields():
    f = Flow(id="1", ts=0, app="a", host="h", method="GET", path="/", ip="1.1.1.1",
             tracker=Tracker("x", "ads"), pii=[PiiHit("email", "j***@x.com", 0.9)])
    d = f.to_dict()
    assert set(d) == _ts_fields("Flow")
    assert set(d["pii"][0]) == _ts_fields("PiiHit")
    assert set(d["tracker"]) == {"name", "category"}


def test_verdict_and_score_fields():
    v = Verdict("1", "violation", "r", [Citation("DPDP", "s6", "u")]).to_dict()
    assert set(v) == _ts_fields("Verdict")
    assert set(v["citations"][0]) == _ts_fields("Citation")
    s = Score(10, [ScoreCategory("x", 1)]).to_dict()
    assert set(s) == _ts_fields("Score")


def test_pii_types_match():
    src = SCHEMA_TS.read_text(encoding="utf-8")
    ts_types = set(re.findall(r"\|\s*'(\w+)'", src.split("export interface PiiHit")[0]))
    assert ts_types == set(PII_TYPES)
