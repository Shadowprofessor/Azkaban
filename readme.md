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

- **Landing and setup:** introduces account linking, asks users to confirm they own or may review the device and accounts, then opens the app-linking workspace.
- **Live Leak Radar:** virtualized flow stream, PII/severity filters, metadata-only vs decrypted labels, score gauge, category bars, and Shadow Map.
- **Flow drawer:** destination, jurisdiction, timing, size, PII signal confidence, and the streamed legal verdict. The frozen Flow contract contains redacted PII values only, so the UI cannot reveal raw values.
- **Findings & Next Steps:** evidence, source citations, a practical review guide, proportionate options, actions to avoid, a complaint draft, and evidence export.
- **Link your apps:** provider authorization cards, linked-state tracking, disconnect actions, HIBP proxy form, and a local-only Takeout ZIP selection state. OAuth start/callback/disconnect routes still need provider credentials and backend implementation.

## App authorization integration

The app cards start OAuth through `POST /api/oauth/{provider}/start` for `instagram`, `reddit`, `spotify`, `google`, or `github`. The same-origin endpoint must create and validate OAuth state (and PKCE where supported), keep client secrets server-side, and return `{ "authorizationUrl": "https://..." }`. After the provider callback is verified server-side, redirect to the frontend with `?oauth=connected&provider={provider}`. Disconnect uses `POST /api/oauth/{provider}/disconnect` and must revoke the provider grant when supported. The frontend records only the provider name in session storage; it never stores access tokens. A teammate React integration can instead expose `window.GhostPrintIntegrations.connectApp({ provider })` and `disconnectApp({ provider })`, resolving only after the server confirms the operation.

Provider client IDs, redirect URIs, scopes, callback verification, token storage, disconnect/revocation, and provider review requirements must be configured by the account-connector backend. The UI does not report a connection as successful until the connector completes.

## Agent fields for advanced privacy features

The existing core messages remain accepted. Advanced screens consume optional, additive agent telemetry; without it they show an unavailable state instead of estimating or inventing measurements.

- **Idle activity:** each flow may include `idle: { state: "idle" | "active", sessionId }`. The agent must determine device or monitored-app inactivity and distinguish suspend/resume. Optional `traffic.uploadBytes`, `traffic.downloadBytes`, `traffic.protocol`, `traffic.durationMs`, and `process.pid` / `process.name` populate their corresponding details. Optional `status.idleMonitoring` and `status.idleThresholdMs` report agent capability and acknowledged configuration. The frontend sends optional `configure_idle` with `inactivityMs`; agents that do not support it can ignore the message.
- **Cross-app identity links:** a PII signal may include `correlation: { scheme: "hmac-sha256", pseudonymized: true, fingerprint, confidence? }`. The fingerprint must be a stable keyed HMAC generated locally from the normalized value, using a protected key. Never send or store the raw identifier for correlation. The dashboard links only exact matching 64-character fingerprints and does not infer sharing between companies.
- **Evidence vault:** an export may include `chain: { expectedCount, records: [{ recordId, record, previousHash, hash }], checkpoint?: { lastHash } }`. Each record hash is SHA-256 of canonical JSON for `{ recordId, record, previousHash }`, with recursively sorted object keys and preserved array order. The browser can check record hashes, link continuity, expected count and an optional final hash. A plain checkpoint is not a signature; signed checkpoints and protected key storage must be implemented by the agent.
- **Legal intelligence:** curated primary material is bundled in `src/legalReferences.js`, with official links and source-check dates. Findings returned by an agent remain observations, not legal determinations. The DPDP Act and Rules use phased commencement; the library calls out the applicable schedule and directs users to verify the original Gazette text.

These fields do not make the existing agent produce data it does not collect. OS idle detection, process attribution, traffic byte direction, keyed identifier extraction, append-only storage, signatures, and complete evidence exports require corresponding local-agent work. Keep optional extensions coordinated with the agent team.

## Build

```powershell
npm run build
```

Run the privacy feature unit checks with:

```powershell
npm test
```

The production dashboard is still a Vite app at this stage. Migrating it to Next.js App Router and wiring OAuth/HIBP API routes are follow-up items from the TRD. The frontend can be served from any laptop; the capture agent remains local to the audited device.
