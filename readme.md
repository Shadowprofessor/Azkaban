# Azkaban

**Find out which companies your apps and browser send your data to, see exactly what they take, and block them. Everything runs on your own machine.**

Azkaban watches your network traffic in two places: inside Chrome (through the extension) and for every app on your computer (through a local proxy). It finds personal data being sent out, such as advertising IDs, emails, phone numbers, location and device IDs. It names the company receiving it, scores how exposed you are, explains whether that looks lawful, and lets you block it. Nothing is uploaded anywhere: all of this runs on `127.0.0.1`.

---

## Contents
1. [How it works](#how-it-works)
2. [Components](#components)
3. [Features](#features)
4. [Quick start (Windows)](#quick-start-windows)
5. [Configuration (.env)](#configuration-env)
6. [Agent commands](#agent-commands)
7. [Privacy and security model](#privacy-and-security-model)
8. [Project structure](#project-structure)
9. [Tests](#tests)
10. [Troubleshooting](#troubleshooting)
11. [Team and branches](#team-and-branches)

---

## How it works

```
 ┌──────────────────────┐   browser_flows / detections   ┌──────────────────────────┐   flows, insights,   ┌─────────────────────┐
 │ Chrome + extension   │ ─────────────────────────────► │ Agent                    │ ───────────────────► │ Website (dashboard) │
 │ "The Trace"          │   ws://127.0.0.1:8787/ws/ext   │ 127.0.0.1:8787 socket    │   verdicts, score    │ 127.0.0.1:5173      │
 └──────────────────────┘   (send-only)                  │ 127.0.0.1:8080 proxy     │   ws://…:8787/ws     └─────────────────────┘
 ┌──────────────────────┐   HTTP(S) via proxy            │ PII scan · trackers · ML │                               │
 │ Every other app      │ ─────────────────────────────► │ Nemotron / Ollama legal  │                               ▼  /api/*
 └──────────────────────┘                                │ history.db (30 days)     │                      ┌─────────────────────┐
                                                         └──────────────────────────┘                      │ GhostPrint 127.0.0.1:8765 │
                                                                                                           └─────────────────────┘
```

1. **Capture.** The extension records every request Chrome makes. The proxy, if you point Windows at it, records requests from all other apps.
2. **Analyse.** The agent works out who receives each request (tracker list plus an ML classifier for unlisted trackers) and which country it goes to. It also finds personal data, including base64, gzip and hashed copies of it, and scores how severe each request is.
3. **Explain.** High-severity flows go to the legal engine, which uses retrieval (RAG) plus **NVIDIA Nemotron**, or local **Ollama** if Nemotron is unavailable. It returns a verdict (compliant / questionable / violation) with citations.
4. **Show.** The website receives everything live over a WebSocket. History survives restarts.
5. **Act.** Block trackers or cookies in the browser (Patronus), generate a blocklist, or export signed evidence.

---

## Components

| Part | Folder | Port | Stack | Owner branch |
|---|---|---|---|---|
| **Agent** | `azkaban-agent/` | 8787 WebSocket, 8080 proxy | Python 3.10+, mitmproxy, websockets, onnxruntime | `Sachit` |
| **Extension** ("The Trace") | `azkaban-extension/` | — | TypeScript, WXT, Chrome MV3, onnxruntime-web | `Chromium-extension` |
| **Website** (dashboard) | `dashboard/` | 5173 | React, Vite, Zustand | `nirmit` |
| **GhostPrint** analyst | `ghostprint/`, `browser-companion/` | 8765 | Python | `yash` |
| RAG / legal corpus | `rag/` | — | Python | `yash` |
| Model training | `train/` | — | Python | `Sachit` |

Shared contracts: `lib/schema.ts` and `lib/live/protocol.ts`. They are **frozen**: changes may only add fields.

---

## Features

### Agent
- **Traffic capture** through mitmproxy, with the process name and PID behind each connection, plus traffic direction, protocol, status code and duration.
- **PII detection** for email, phone, IMEI, advertising ID, GPS, contacts and clipboard. It also finds these when they are URL-encoded, base64, gzip or hashed, and recognises your own identifiers via `AZK_KNOWN_*`.
- **Tracker attribution** using a bundled tracker list, plus an ONNX classifier that flags trackers on no list.
- **Severity model** that scores each flow 0–100, and an **exposure score** from 0 to 1000.
- **Insights**: the same ID sent across apps, beacons sent while you were away (idle detection), apps that bypass the proxy (DNS bypass), and honeytoken leaks.
- **Legal engine**: retrieval plus Nemotron, falling back to Ollama, with cached verdicts and citations.
- **Durable history**: 30 days in `evidence/history.db`, replayed to the website on connect. Only live capture is stored.
- **Evidence export**: a hash-chained JSONL file plus a PDF report, which can be checked with `verify-evidence`.
- **Blocklist generation** in hosts and other formats.

### Extension
- Every request with its method, path, status, type, timing, whether it is third-party, whether a cookie was sent, the names of cookies set, and whether it was blocked. Requests are **streamed live** to the agent, and backfilled if the agent was down.
- **Site safety grade A–F** from trackers, unknown trackers, third parties, cookies and fingerprinting.
- **Fingerprinting detection** across canvas, WebGL, audio, fonts, device and screen.
- **Form harvesting detection**: data a page sends before you press submit.
- **Cookie and storage audit**: supercookies (the same ID in a cookie and in localStorage) and ID syncing between companies.
- **Patronus** blocks trackers (with a per-company Block button), blocks a domain's cookies, or strips cookies from every third-party request.
- On-page alerts and an offline queue, so nothing is lost while the agent is down.
- **Sign-in safe**: Google, Microsoft, Apple, GitHub and Yahoo login pages are never touched or blocked.

### Website
- **Privacy report**, **Leak Radar** (live flows with a Burp-style request detail view), **While away**, **Insights**, **Shadow Map**, **Same ID across apps**, **Legal**, **Actions**, **Proof & records** and **Link apps**.
- The **Open Dashboard** link in the extension goes straight to Leak Radar.

---

## Quick start (Windows)

**Requirements:** Python 3.10+, Node 20+, Chrome.

1. **Set your key.** Copy `.env.example` to `.env` and fill in:
   ```
   NVIDIA_API_KEY=nvapi-...
   ```
   `.env` is git-ignored. Never put a key in `.env.example`.
2. **Start everything.** Double-click `START.cmd`, or run `.\START.cmd` from any folder. It:
   - installs the agent and website dependencies on the first run, and repairs a broken `node_modules`;
   - rebuilds the extension if its source changed;
   - stops old Azkaban processes still holding ports 8787, 8080, 8765 or 5173;
   - checks Nemotron (`nim-check`);
   - starts the agent, GhostPrint and the website, writes logs to `logs\`, and opens `http://127.0.0.1:5173`.
3. **Load the extension.** Go to `chrome://extensions`, turn on **Developer mode**, click **Load unpacked**, and pick `azkaban-extension\.output\chrome-mv3`. After any update, press **Reload** on its card.
4. **Link it.** In the popup, click **Agent bridge → Turn on**. The header should show a green dot and **Connected to agent**.
5. **Browse.** Requests appear live in Leak Radar.

**Optional, for all apps and not only Chrome:**
1. Windows Settings → Network → Proxy → Manual: `127.0.0.1`, port `8080`.
2. Open `http://mitm.it` and install the Windows certificate (once).
3. ⚠️ **Turn the proxy off when you finish**, or your internet stops when the agent stops.

---

## Configuration (.env)

| Key | Default | Meaning |
|---|---|---|
| `AZK_WS_PORT` / `AZK_PROXY_PORT` | 8787 / 8080 | Agent socket and proxy ports |
| `AZK_NIM_ENABLED` | 1 | Use NVIDIA NIM for legal reasoning |
| `AZK_NIM_URL` | `https://integrate.api.nvidia.com/v1` | Base URL or the full `/chat/completions` URL (both work) |
| `AZK_NIM_MODEL` | `nvidia/nemotron-3-ultra-550b-a55b` | Preferred model. The agent switches to the best one your key is allowed to use |
| `NVIDIA_API_KEY` | — | Your key. The `.env` value wins over a Windows environment variable |
| `AZK_NIM_FALLBACK_OLLAMA` | — | Fall back to local Ollama |
| `AZK_OLLAMA_URL` / `AZK_OLLAMA_MODEL` | `http://127.0.0.1:11434` / `qwen2.5:7b` | Local model |
| `AZK_HISTORY` / `AZK_HISTORY_DAYS` / `AZK_HISTORY_REPLAY` | on / 30 / 500 | History store, retention in days, and flows replayed on connect |
| `AZK_GEOIP_DB` | bundled path | GeoLite2 country database |
| `AZK_HOME_COUNTRY` | `IN` | Used to judge cross-border transfers |
| `AZK_KNOWN_EMAILS` / `_PHONES` / `_ADIDS` | — | Your own identifiers, so leaks of them are flagged. They are hashed and never stored raw |
| `GOOGLE_OAUTH_*`, `GITHUB_OAUTH_*` | — | Optional, for Link apps in GhostPrint (redirect URI `http://127.0.0.1:8765/`) |
| `HIBP_API_KEY` | — | Optional, for the breach scan |

---

## Agent commands

```powershell
python -m azkaban_agent capture --i-own-this-device   # live capture (START.cmd runs this)
python -m azkaban_agent replay <file>                 # replay a recording (never written to history)
python -m azkaban_agent demo-session                  # synthetic demo
python -m azkaban_agent nim-check                     # which Nemotron models your key can use
python -m azkaban_agent history                       # what is stored
python -m azkaban_agent history --forget              # delete all stored history
python -m azkaban_agent export-evidence               # hash-chained evidence + PDF
python -m azkaban_agent verify-evidence <file>        # check an export has not been altered
python -m azkaban_agent honeytoken add|list           # plant tokens and detect their leaks
python -m azkaban_agent rag-check                     # check the legal corpus
python -m azkaban_agent fetch-geo                     # download the GeoIP database
python -m azkaban_agent train                         # retrain the severity model
```

---

## Privacy and security model

- **Loopback only.** At runtime the agent talks only to `127.0.0.1` (WebSocket 8787, Ollama 11434), plus the NVIDIA endpoint if you enable it. Every outbound connection goes through `azkaban-agent/azkaban_agent/net.py`, and `scripts/security.py` fails the build otherwise. The extension's CSP allows only loopback connections.
- **Redaction.** Personal data is redacted before it is shown or stored. The extension never sends query values, header values, cookie values or request bodies to the agent, only names and sizes. Cookie and authorization headers are shown as "N bytes, not shown". Referers are reduced to their domain.
- **Producer-only extension channel.** The extension can send to the agent but can never read flows back. Extension origins are refused on the dashboard socket.
- **Consent.** Capture requires `--i-own-this-device`, and the website asks once per session.
- **Storage.** `evidence/` and `.env` are git-ignored. User traffic is written to disk only to history (live capture only), to opt-in recordings, and to evidence you export.
- **Sign-in safety.** Identity-provider pages get no content scripts, and their domains have a DNR allow rule that outranks every block.

---

## Project structure

```
azkaban-agent/          Python agent
  azkaban_agent/        capture, pipeline, pii, trackers, tracker_clf, severity, legal, nim,
                        history, evidence, extbridge, wsserver, insights, netwatch, idle, …
  tests/                pytest suite
  scripts/security.py   egress guard
azkaban-extension/      Chrome MV3 extension (WXT)
  entrypoints/          background, popup, content scripts (probe, bridge, toast)
  lib/                  scoring, pii, audit, cookies, dnr, signin, agentBridge, store
  e2e/                  Playwright end-to-end tests (phase7–phase14)
dashboard/              React website (src/main.jsx, adapter.js = protocol adapter)
ghostprint/             GhostPrint analyst server
rag/                    legal retrieval corpus and tests
lib/                    frozen shared contracts (schema.ts, live/protocol.ts)
scripts/                start.ps1, check-extension-egress.mjs, packaging
START.cmd               one-click launcher
```

---

## Tests

```powershell
# agent (pytest-asyncio required: pip install -e "azkaban-agent[dev]")
cd azkaban-agent; python -m pytest tests -q

# extension
cd azkaban-extension
npm run typecheck
npm run build
npm run test:sync      # browser → extension → agent → website, plus cookie blocking
npm run test:signin    # login pages are never touched or blocked
npm run test:bridge    # wire format against the real agent
npm run test:queue     # nothing lost while the agent is down

# website
cd dashboard; npm test

# privacy guards: run before pushing
python azkaban-agent/scripts/security.py
node scripts/check-extension-egress.mjs
```

End-to-end tests run their own agent on spare ports and never connect to your real agent.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Popup: **"Not linked: Agent bridge is off"** | Popup → Agent bridge → **Turn on** |
| Popup: **"Agent not running"** | Run `START.cmd` |
| Website shows old data | Press `Ctrl+Shift+R` on the website tab. If that doesn't help, restart with `START.cmd` |
| `Errno 10048` / port 8787 busy | An old agent is still running. `START.cmd` stops it |
| `'vite' is not recognized` | Broken `node_modules`. `START.cmd` reinstalls it |
| `scripts\start.ps1` not found | You are in a subfolder. Use `START.cmd`, which works from any folder |
| Nemotron **403 Authorization failed** | Your key isn't allowed to use that model. `nim-check` lists the ones that work, and the agent picks one automatically |
| Wrong key being used | An old `NVIDIA_API_KEY` in Windows env. `.env` now wins; `nim-check` shows where the key came from |
| Google login fails | Reload the extension. Sign-in pages are excluded from the current build |
| No internet after stopping | The Windows proxy is still set to 8080. Turn it off |

---

## Team and branches

`main` is the integration branch, and everything ships from it. Feature branches are merged into `main`: `Sachit` (agent, ML), `Chromium-extension` (extension), `nirmit` (website), `yash` (GhostPrint, RAG). Never force-push `main`.
