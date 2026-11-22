# Azkaban — project rules for AI assistants

- Never add AI attribution to commit messages or PRs (no "Co-Authored-By", "Claude-Session",
  "Generated with" lines). Conventional-commit message only.
- Privacy is absolute: at runtime the agent may only talk to 127.0.0.1 (WebSocket 8787, Ollama 11434).
  All outbound connections go through `azkaban-agent/azkaban_agent/net.py`; run `make security`
  (or `python azkaban-agent/scripts/security.py`) before pushing agent changes.
- Emit only redacted PII. Never write user traffic to disk except opt-in recording and evidence export.
- Contracts `lib/schema.ts` and `lib/live/protocol.ts` are frozen; changes must be additive.
- `main` is the integration branch: everything ships from it. Feature branches (Sachit /
  Chromium-extension / nirmit / yash) are merged into main. Never force-push main.
