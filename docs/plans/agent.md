# Plan — azkaban-agent (Sachit)

Single Python process, one asyncio loop:

```
mitmproxy DumpMaster (127.0.0.1:8080)
   └─ CaptureAddon ── raw record ──► Pipeline (pii, tracker, geo, hashed-pii, severity, score)
                                         ├─► Recorder (.azk, only with --record)
                                         └─► Hub ──► WebSocket server (127.0.0.1:8787) ──► dashboard
Replay (.azk) ──────── raw record ──► Pipeline (same path, no proxy)
```

- Contracts: `lib/schema.ts`, `lib/live/protocol.ts` (frozen). Python mirror: `azkaban_agent/schema.py`, guarded by `tests/test_contract.py`.
- Boundary: loopback-only binds + `--i-own-this-device` (`azkaban_agent/safety.py`).
- Pinning fallback: `tls_failed_client` emits a metadata-only flow (`decrypted=false`), host goes to passthrough so the app keeps working.
- Legal: `rag.query.retrieve` (teammate) with structured facts only → Ollama qwen2.5:7b. Degrades to "law unavailable" / no verdicts.

## Status
- [x] P0 contracts  - [x] P1 capture  - [x] P2 websocket  - [x] P3 classify  - [x] P4 replay
- [x] P5 hashed-pii - [x] P6 xgboost  - [x] P7 idle/dns  - [x] P8 legal     - [x] P9 blocklist
- [ ] P10 evidence  - [ ] P11 stretch

## Contract for the RAG teammate — `rag/query.py`
The agent imports `from rag.query import retrieve` (repo root on `sys.path`) and falls back to
`azkaban_agent/rag_stub.py` when it is missing. Call shape:

```python
retrieve(facts: dict, k: int = 4) -> list[dict]   # each: {"source", "section", "url", "text"}
```
`facts` is structured only — never PII values: `pii_types, company, tracker_category, is_tracker,
jurisdiction, cross_border, consent, consent_signal, app, app_category, pii_unexpected_for_app_category,
hashed_identifier, same_adid_across_apps, while_user_idle, decrypted`.
`section` must be a label like `"Section 6"` / `"Section 2(t)"`; the agent only accepts citations whose
label is in the returned set. Raise any exception when the index is down → verdict says "Law unavailable".
