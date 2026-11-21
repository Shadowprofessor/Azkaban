# azkaban-agent

Captures **your own device's** traffic, decrypts it, finds PII leaks, scores them, explains them under the
DPDP Act 2023, and streams everything to the dashboard over `ws://127.0.0.1:8787` (`lib/live/protocol.ts`).

## Setup
```bash
pip install -e "azkaban-agent[dev]"          # from the repo root
python -m azkaban_agent fetch-geo            # offline IP->country DB (DB-IP Lite, CC-BY 4.0)
ollama pull qwen2.5:7b                       # legal verdicts (optional; agent runs without it)
```
`azkaban` is installed as a script too; on Windows use `python -m azkaban_agent ...` if Scripts isn't on PATH.

## Run
| Command | What it does |
|---|---|
| `python -m azkaban_agent replay azkaban-agent/demo/demo.azk --speed 2x` | **Demo insurance.** Synthetic story, same protocol. No proxy needed. |
| `python -m azkaban_agent capture --i-own-this-device` | Live: proxy on `127.0.0.1:8080`. Refuses to start without the flag or on a non-loopback bind. |
| `... capture --i-own-this-device --record s.azk` | Also record (contains **unredacted** traffic — keep it private). |
| `python -m azkaban_agent honeytoken add "Dobby contact card"` | Make a canary to plant; any outbound appearance trips a critical alert. |
| `python -m azkaban_agent export-evidence` | Ask the running agent for the hash-chained PDF + JSONL evidence pack (`evidence/`). |
| `python -m azkaban_agent verify-evidence evidence/<file>.jsonl` | Detects any edited, removed or reordered entry. |
| `python -m azkaban_agent train` | Retrain the severity model (XGBoost -> ONNX). |

**Laptop:** set the system/browser proxy to `127.0.0.1:8080`, open `http://mitm.it` to install the CA.
**Android phone (USB):** `adb reverse tcp:8080 tcp:8080`, set the phone's Wi-Fi proxy to `127.0.0.1:8080`,
install the CA from `http://mitm.it`. Traffic arrives attributed as `android-device`.

## Dashboard commands (UI -> agent)
`{"type":"start"}` `{"type":"stop"}` `{"type":"analyze","flowId":"..."}`
`{"type":"blocklist","action":"generate"|"apply"|"clear"}` `{"type":"export_evidence"}`

## What each message means
- `flow` — one request. `pii[].redacted` only (raw values never leave the agent). `severity` 0-100 from the ONNX model.
  Pinned apps still appear with `decrypted:false`.
- `score` — Exposure Score 0-1000 + subscores; `remediation` ranked by marginal score reduction.
- `verdict` — DPDP assessment; every citation is a section that was actually retrieved.
- `blocklist` — hosts/Pi-hole/NextDNS/pf rules; after `apply`, `recheck` = leaks before vs after.
- `insight` (additive) — idle beacons, hashed PII, cross-app ID reuse, proxy bypass, bandwidth, honeytoken,
  recheck, beacon anomalies, unlisted trackers. Replace by `key`.

## Degradation
Ollama down -> flows + severity continue, no verdicts (`error: llm_unavailable` once).
RAG down -> verdict `questionable`, "Law unavailable". No GeoIP DB -> country `ZZ`. No model -> rubric fallback.

## Model notes (for judges)
See **[MODELS.md](../MODELS.md)** for datasets, protocol and exact held-out numbers.
- **Unknown-tracker classifier:** XGBoost trained on the GPU, ONNX at runtime. Labels come from public
  blocklists; behaviour is real WhoTracks.me data. Held-out real domains under GroupKFold give
  **F1 0.822 / PR-AUC 0.871** (target was 0.93 — not reached, reported as-is). The same model runs in
  the agent and the extension.
- **Severity:** XGBoost fitted to a synthetic rubric. R² 0.986 is circular and only shows it reproduces
  the rubric; it is not real-world accuracy.
- **Beacon anomaly:** IsolationForest, unsupervised.
