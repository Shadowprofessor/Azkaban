# GhostPrint v2 - Live Privacy Forensics

GhostPrint audits a device and network you own. It connects a local-first dashboard to a local capture agent, shows outbound flows and reported personal-data signals, and presents agent-generated scores, verdicts, and remediation.

The frontend follows the scope in `GhostPrint_Frontend_PRD_TRD.pdf`: dashboard only. It does not implement traffic capture, PII classification, tracker attribution, GeoIP, legal reasoning, or blocklist generation. Those are responsibilities of the local agent and reasoning workstream.

## Run the frontend and mock agent

Install Node.js, then use two terminals in this folder:

```powershell
npm install
npm run mock
```

```powershell
npm run dev
```

Open the Vite URL shown in the second terminal (normally `http://localhost:5173`). The mock agent listens on `ws://127.0.0.1:8787` and streams the frozen protocol at roughly 250 ms intervals (at least 200 flows per minute). On the consent screen, choose the device, confirm you own the device and network, then start capture.

## Connect the real local agent

The default browser socket is `ws://localhost:8787`, matching the PRD. The dashboard automatically reconnects with backoff capped at five seconds, flushes flow messages every 100 ms, and retains the newest 2,000 flows in memory. If the agent is unavailable, the dashboard shows an offline state and keeps the current in-memory view.

To change the WebSocket address, open **Connection settings** from the consent screen or sidebar. A Vite build can also use:

```env
VITE_AGENT_WS_URL=ws://localhost:8787
```

For a VS Code forwarded agent port, enter the corresponding `wss://...` WebSocket address in settings. The local agent should remain bound to loopback (`127.0.0.1`) per the security boundary in the full plan. Forward only a port you intend to expose, and keep the consent gate enabled.

## Screens

- **Consent gate:** identifies the device, requires explicit ownership confirmation, and waits until agent connectivity is known.
- **Live Leak Radar:** virtualized flow stream, PII/severity filters, metadata-only vs decrypted labels, score gauge, category bars, and Shadow Map.
- **Flow drawer:** destination, jurisdiction, timing, size, PII signal confidence, and the streamed legal verdict. The frozen Flow contract contains redacted PII values only, so the UI cannot reveal raw values.
- **Legal & Remediation:** streamed verdicts with citations, blocklist requests and preview, capture re-run controls, editable complaint draft. Apply copied blocklist rules on the audited device before comparing a new capture, and evidence export on an agent evidence response.
- **Stored Footprint:** OAuth connector UI, HIBP proxy form, and a local-only Takeout ZIP selection state. OAuth and `/api/hibp` server routes still need their backend work.

## Frozen WebSocket messages

Inbound `status`, `flow`, `verdict`, `score`, `blocklist`, `evidence`, and `error`, plus outbound `start`, `stop`, `analyze`, `blocklist`, and `export_evidence` follow the PRD message shapes. Do not silently rename or extend contract fields; agree across workstreams before changing the frozen contract.

## Build

```powershell
npm run build
```

The production dashboard is still a Vite app at this stage. Migrating it to Next.js App Router and wiring OAuth/HIBP API routes are follow-up items from the TRD. The frontend can be served from any laptop; the capture agent remains local to the audited device.
