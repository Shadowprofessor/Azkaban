# Security — Azkaban

Azkaban inspects network traffic, so its own behaviour has to be beyond suspicion. This document
states what it guarantees, how those guarantees are enforced in code, and how to verify them yourself.

## Threat model

**In scope — the operator's own device and network.** Azkaban is a forensic tool for a person examining
traffic from hardware and accounts they own.

| Concern | Control |
|---|---|
| Used to intercept someone else's traffic | Proxy and WebSocket bind to `127.0.0.1` only (`safety.require_loopback`); capture refuses to start without `--i-own-this-device`. No promiscuous mode, no remote bind. Phones connect over USB with `adb reverse`, never over the LAN. |
| The tool itself leaks what it captures | Egress guard (below). PII is redacted inside the agent before anything is emitted. Recording and evidence export are explicit opt-ins. |
| A malicious website reads the dashboard socket | WebSocket accepts only `localhost`/`127.0.0.1` origins (`wsserver.LOCAL_ORIGINS`). |
| Hostile traffic attacks the parser | Bounded decompression (256 KB), JSON nesting and recursion limits, per-field size caps, linear-time regexes, per-flow error isolation (`tests/test_hostile_input.py`). |
| Evidence is altered after the fact | SHA-256 hash chain; `azkaban verify-evidence` detects any edited, removed or reordered entry. |
| LLM invents law | Only retrieved statute sections may be cited; anything else is stripped and flagged. |

**Out of scope:** a compromised operating system or Python environment on the operator's machine, and
attackers with local admin rights (they can read the agent's memory anyway).

## The localhost-only guarantee

At runtime, user data goes to exactly two places, both on the same machine:

- `ws://127.0.0.1:8787` — the agent → dashboard socket
- `http://127.0.0.1:11434` — local Ollama for legal verdicts

Enforcement:

1. **`azkaban_agent/net.py` is the only module that opens outbound connections.** It allows loopback
   addresses (and `localhost` only if it resolves to loopback), refuses redirects, and raises
   `EgressDenied` for anything else before a socket exists.
2. **Static check:** `azkaban-agent/scripts/check_egress.sh` fails the build if any other agent module
   imports an HTTP or socket client.
3. **Dashboard CSP:** production pages send `connect-src 'self' ws://127.0.0.1:8787`, so the browser
   itself blocks any other connection. Fonts are self-hosted at build time; there is no analytics,
   telemetry or CDN.

Not covered, by design: mitmproxy forwarding your own traffic to the destination your app asked for.
That is your traffic continuing on its way, not data the agent originates.

### Setup-only downloads

`azkaban fetch-geo` downloads the DB-IP Lite country database from `download.db-ip.com`
(`net.http_get(..., allow_setup=True)`). It runs only when you invoke it and sends no user data.
The tracker lists and DPDP text are bundled at build time by scripts under `azkaban-agent/scripts/`.

## The one optional external call: NVIDIA NIM

Off by default (`AZK_NIM_ENABLED=0`). When you turn it on:

- it is allowed only to the configured NIM host over HTTPS;
- it sends **structured facts only** — PII *types* (e.g. `"email"`), company, country, consent flag,
  app category — plus the retrieved statute text. Never a PII value, redacted or not;
- the agent prints the **exact JSON payload** to stderr before sending it.

## Verify it yourself

```bash
make security                                   # egress grep + full agent test suite
python azkaban-agent/scripts/security.py        # same, without make (Windows)
```

### "Pull the cable" demo proof

`tests/test_egress.py` replays the full demo session through the real agent: WebSocket server and
client, pipeline, legal worker, blocklist apply and evidence export. It runs with the network
"unplugged": `getaddrinfo`, `socket.connect` and `connect_ex` are patched to refuse and record any
non-loopback target. The test asserts **zero** recorded attempts. A control test proves the patch
really catches an external connection.

`tests/test_no_raw_pii_emitted.py` replays the same session and asserts that no demo identifier
(email, phone in three formats, ad ID, IMEI, GPS, contact numbers, canary token, even the SHA-256 of
the email) appears in any published message, on the WebSocket, or in the exported evidence chain. It
also asserts the redacted findings *are* there, so it cannot pass vacuously.

For a live demo: disconnect Wi-Fi, run
`python -m azkaban_agent replay azkaban-agent/demo/demo.azk`, and the dashboard works exactly the same.

## Reporting

This is a hackathon project. Report issues privately to the repository owner rather than in a public issue.
