# dashboard — Azkaban audit UI

React + Vite front end for the local agent. Ported from the `nirmit` branch
(GhostPrint front end) and wired to the real agent protocol.

## It speaks the frozen protocol now

The front end was written against the frontend PRD, which wrapped every message in a
`data` envelope. The agent implements `lib/live/protocol.ts`, which is FROZEN and names
each payload after its type:

| PRD (what the UI expected) | Agent (what actually arrives) |
|---|---|
| `{type:'flow', data:{…}}` | `{type:'flow', flow:{…}}` |
| `{type:'verdict', data:{…}}` | `{type:'verdict', verdict:{…}}` |
| `{type:'score', data:{…}}` | `{type:'score', score:{…}, remediation:[…]}` |
| `{type:'status', data:{…}}` | flat: `{type:'status', capturing, mode, engines, …}` |
| `flow.ts` string | number, Unix epoch ms |
| `flow.tcf.purposes` string[] | number[] (TCF purpose IDs) |
| `evidence.sha256` | `rootHash` |
| `blocklist.content` | `formats.{hosts,pihole,nextdns,pf}` |
| outbound `blocklist(format)` | `{action:'generate'\|'apply'\|'clear'}` |

Connected directly, `validateInbound` rejected every message and the UI stayed empty.
The agent owns the frozen contract, so the front end adapts: all of it is converted in
`src/adapter.js`, in one place, rather than spread through the components.

`npm run verify:protocol` replays a real captured session through the adapter and the
validator and reports what the UI would hold. On the last run: 65/65 messages accepted,
0 dropped.

## Findings and remediation

`insight` messages are cross-flow findings. Each carries the remediation steps
`rag/guides.py` retrieved for it, rendered on the Insights page by `AgentFindings`. The
`source` badge distinguishes a vendor-specific guide from generic category steps, because
those are not the same claim.

## Real data only

There is no mock server. The UI renders what the agent sends and nothing else; with no
agent running it shows its waiting state rather than sample data. The dev server binds
127.0.0.1 — the agent accepts localhost origins only, and a privacy audit UI should not be
on the LAN by default.

## Running it

    npm install
    npm run dev            # http://127.0.0.1:5173

Point it elsewhere with `VITE_AGENT_WS_URL`, or from the UI's settings panel (stored in
`localStorage` under `ghostprint-agent-url`). Default is `ws://127.0.0.1:8787`.
