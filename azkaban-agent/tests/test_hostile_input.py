"""The agent parses traffic it does not control. One hostile flow must never crash the
pipeline, hang it, or exhaust memory."""
import base64
import gzip
import json
import time
import zlib

import pytest

from azkaban_agent.config import Config
from azkaban_agent.decode import MAX_DECOMPRESSED, unwrap
from azkaban_agent.pipeline import Pipeline

BUDGET_S = 2.0


def raw(**kw):
    base = {"id": "h", "ts": 1, "app": "evil", "host": "graph.facebook.com", "method": "POST", "path": "/",
            "ip": "", "bytes": 1, "decrypted": True, "headers": {}, "query": "", "body": ""}
    base.update(kw)
    return base


@pytest.fixture(scope="module")
def pipe():
    return Pipeline(Config())


def gzip_bomb_b64() -> str:
    # ~16 KB on the wire, ~64 MB when inflated.
    return base64.b64encode(gzip.compress(b"a" * (64 * 1024 * 1024), 9)).decode()


CASES = {
    "gzip_bomb": lambda: raw(body=f"d={gzip_bomb_b64()}"),
    "zlib_bomb_hex": lambda: raw(query="x=" + zlib.compress(b"\x00" * (16 * 1024 * 1024), 9).hex()),
    "deep_json": lambda: raw(body="[" * 200_000 + "]" * 200_000),
    "deep_object": lambda: raw(body='{"a":' * 50_000 + "1" + "}" * 50_000),
    "huge_body": lambda: raw(body="email=" + "x" * (40 * 1024 * 1024)),
    "many_fields": lambda: raw(body="&".join(f"k{i}=v{i}" for i in range(200_000))),
    "email_backtrack": lambda: raw(body="a@" + "a." * 30_000 + "1"),
    "email_many_ats": lambda: raw(body="@a" * 60_000),
    "phone_backtrack": lambda: raw(body="phone=" + "+1 " + "1 " * 30_000),
    "hex_digest_flood": lambda: raw(body="f" * 200_000),
    "b64_nested": lambda: raw(body="d=" + base64.b64encode(base64.b64encode(b"A" * 400_000)).decode()),
    "binary_garbage": lambda: raw(body=bytes(range(256)).decode("latin-1") * 1000),
    "form_in_json_recursion": lambda: raw(body="x=" + "{a=" * 20_000),
    "huge_header": lambda: raw(headers={"cookie": "a=" + "b" * 5_000_000}),
    "bad_types": lambda: {"id": "h", "ts": "nope", "host": None, "bytes": "x", "decrypted": True, "body": {"not": "str"}},
}


@pytest.mark.parametrize("name", list(CASES))
def test_hostile_payload_is_bounded(pipe, name):
    rec = CASES[name]()
    t0 = time.perf_counter()
    try:
        pipe.process(rec)
    except (ValueError, TypeError) as e:
        # Only schema-level rejection of a malformed record is acceptable, never a crash deeper in.
        assert name == "bad_types", f"{name}: {e!r}"
    elapsed = time.perf_counter() - t0
    assert elapsed < BUDGET_S, f"{name} took {elapsed:.2f}s"


def test_decompression_is_capped():
    out = unwrap(gzip_bomb_b64()[:16384])
    assert all(len(t) <= MAX_DECOMPRESSED for _, t in out)


def test_pipeline_keeps_working_after_hostile_flow(pipe):
    pipe.process(raw(body="[" * 200_000))
    e = pipe.process(raw(body=json.dumps({"email": "still.works@example.org"})))
    assert [h.type for h in e.flow.pii] == ["email"]
