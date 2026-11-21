# Azkaban Browser Extension

Privacy forensics inside the browser. Detects known trackers, likely trackers that are on
no blocklist (on-device ML), fingerprinting, pre-submit form harvesting, supercookies and
ID syncing — and blocks what you tell it to.

Works entirely on its own. The agent is optional.

## Install (developer mode)

    npm install
    npm run build
    # chrome://extensions -> Developer mode -> Load unpacked
    # -> select azkaban-extension/.output/chrome-mv3/

Or build a zip: `npm run package` → `dist/azkaban-extension-v*.zip`.

Chromium only (Chrome, Edge, Brave, Opera): MV3 + declarativeNetRequest.

## What it does

- **Patronus blocking** — declarativeNetRequest rules over the tracker list, with a
  per-site pause for when blocking breaks a page.
- **On-device ML** — the same XGBoost→ONNX classifier the agent uses, run in the service
  worker with onnxruntime-web (WASM, single-threaded). Flags unlisted domains from
  behaviour and structure after it has seen a domain on three page loads. No data leaves
  the browser to do it.
- **Site safety score** — trackers, model-flagged unknowns, third parties, cookies and
  fingerprinting collapsed into 0-100 and an A–F grade, with the breakdown shown so the
  grade explains itself. Badge colour follows the grade.
- **On-page alerts** — toasts for findings worth interrupting for: a flagged domain above
  0.85 confidence, fingerprinting, or more than 20 third-party requests on one page. One
  per subject per page, three per page maximum. Toggle in the popup.
- **Cookie and storage audit** — third-party, long-lived and tracking-named cookies, plus
  supercookies (the same ID in several storage backends) and cross-domain ID syncing.
- **Agent bridge** — optional link to the local agent for a combined browser + network view.

## Agent bridge

Off-by-default would make the combined view invisible, so it is on and silent: if no agent
is running, the extension says "Standalone mode" and works exactly as before. The popup
shows the state and lets you turn it off.

It is **producer-only**. The extension sends findings and site scores to
`ws://127.0.0.1:8787/ws/extension` and receives only a handshake ack — never flows, PII or
scores. The agent enforces this as well, and refuses an extension origin on the dashboard
path. See `azkaban_agent/extbridge.py` for why that is the design.

Reconnection runs on `browser.alarms`, not `setTimeout`, because an MV3 service worker is
evicted when idle and takes its timers with it.

## Privacy

- All analysis is local. The only outbound connection is to `127.0.0.1:8787`, and only
  when the bridge is on.
- The CSP in `wxt.config.ts` restricts `connect-src` to loopback, so the browser itself
  blocks anything else — including from a compromised dependency.
- Raw request bodies are never stored. Only redacted findings are.
- Typed form values stay in the page's memory for the comparison and are never sent.
- A site score sends a bare hostname, never a URL, because a URL is browsing history.
- `storage.session` holds per-tab state and is wiped when the browser closes.

## Layout

| Path | What |
|---|---|
| `entrypoints/background.ts` | Service worker: request observation, audits, routing |
| `entrypoints/probe.content.ts` | MAIN world: fingerprinting and XHR/fetch probes |
| `entrypoints/bridge.content.ts` | Isolated world: validates probe events, form harvest detection |
| `entrypoints/toast.content.ts` | On-page alerts, in a closed shadow root |
| `entrypoints/popup/` | Popup UI |
| `lib/clf.ts`, `lib/trackerFeatures.ts` | ONNX classifier and feature parity with the agent |
| `lib/scoring.ts` | Site safety score |
| `lib/alerts.ts` | When to toast, and what to say |
| `lib/agentBridge.ts`, `lib/bridgeProtocol.ts` | Agent link and its wire format |
| `lib/dnr.ts` | Patronus blocking rules |
| `lib/audit.ts` | Cookie, storage, supercookie and ID-sync audit |

## Tests

    npm run typecheck
    npm run test:score     # scoring curve, caps, allowances
    npm run test:alerts    # alert thresholds, dedupe, caps
    npm run test:bridge    # interop against the real Python agent

`e2e/phase1..7.mjs` and `e2e/phase8.mjs` drive a real Chromium through Playwright and need
`npx playwright install chromium` first.
