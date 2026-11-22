# Azkaban

**See which companies your apps and browser send your data to, and block them. Everything runs on your own machine.**

Azkaban has three parts that work together:

| Part | Folder | Port | What it does |
|---|---|---|---|
| **Agent** | `azkaban-agent/` | 8787 (socket), 8080 (proxy) | Captures traffic, finds personal data (redacted), scores exposure, explains findings with NVIDIA Nemotron or local Ollama, stores 30 days of history |
| **Browser extension** ("The Trace") | `azkaban-extension/` | — | Sees every browser request, grades each site A–F, catches fingerprinting and form harvesting, blocks trackers and cookies (Patronus), streams requests live to the agent |
| **Website** (dashboard) | `dashboard/` | 5173 | Live view of everything: Leak Radar, privacy report, companies, legal guidance, evidence export |
| GhostPrint analyst | `ghostprint/` | 8765 | Linked accounts, breach checks, site policy checks, Q&A |

```
Chrome + extension ──► Agent (127.0.0.1:8787) ──► Website (127.0.0.1:5173)
Apps via proxy :8080 ──┘
```

## Quick start (Windows)

1. Put your NVIDIA key in `.env` (copy `.env.example`; `.env` is never committed):
   ```
   NVIDIA_API_KEY=nvapi-...
   ```
2. Double-click **`START.cmd`** (or run `.\START.cmd`). The first run installs everything. It starts the agent, GhostPrint and the website, and opens the website.
3. Load the extension: `chrome://extensions` → Developer mode → **Load unpacked** → `azkaban-extension\.output\chrome-mv3`.
4. In the extension popup, turn **Agent bridge** on. The dot turns green: "Connected to agent".
5. Browse. Your requests appear live on the website.

**Optional, for traffic from all apps (not only Chrome):** set Windows proxy to `127.0.0.1:8080`, then open `http://mitm.it` and install the certificate once. Turn the proxy off when you are done, or your internet stops when the agent stops.

## Privacy rules

- At runtime the agent talks only to `127.0.0.1` (plus the NVIDIA endpoint if you enable it). Every outbound call goes through `azkaban-agent/azkaban_agent/net.py`.
- Personal data is redacted before it is shown or stored. Cookie, query and header **values** are never sent to the website.
- Sign-in pages (Google, Microsoft, Apple, GitHub) are never touched or blocked by the extension.
- History lives in `evidence/history.db` (git-ignored). Clear it with `python -m azkaban_agent history --forget`.

## Useful commands

```powershell
python -m azkaban_agent nim-check          # which Nemotron models your key can use
python -m azkaban_agent history            # what is stored
python -m azkaban_agent history --forget   # delete all stored history
```

## Tests

```powershell
cd azkaban-agent;     python -m pytest tests -q        # agent
cd azkaban-extension; npm run typecheck; npm run test:sync; npm run test:signin
cd dashboard;         npm test
python azkaban-agent/scripts/security.py               # egress guard (run before pushing)
```

## Troubleshooting

| Problem | Fix |
|---|---|
| Popup says "Not linked: Agent bridge is off" | Popup → Agent bridge → Turn on |
| Popup says "Agent not running" | Run `START.cmd` |
| Website shows old data | `Ctrl+Shift+R` on the website tab |
| Port 8787 busy | Run `START.cmd` again; it stops the old agent |
| Nemotron 403 | Key not allowed for that model; `nim-check` shows which ones work |

## Branches

`main` is the integration branch. Feature branches (`Sachit`, `nirmit`, `yash`, `Chromium-extension`) merge into it.
