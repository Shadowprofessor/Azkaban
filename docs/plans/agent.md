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
- [x] P0 contracts  - [x] P1 capture  - [x] P2 websocket  - [ ] P3 classify  - [ ] P4 replay
- [ ] P5 hashed-pii - [ ] P6 xgboost  - [ ] P7 idle/dns  - [ ] P8 legal     - [ ] P9 blocklist
- [ ] P10 evidence  - [ ] P11 stretch
