"""Honeytoken canaries: unique planted values. Any outbound appearance is hard proof
that a NAMED app exfiltrated that exact value.

Tokens are stored in ~/.azkaban/honeytokens.json (your config, not traffic).
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path

STORE = Path.home() / ".azkaban" / "honeytokens.json"


def load(path: Path = STORE) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def add(label: str, path: Path = STORE) -> dict:
    tokens = load(path)
    tok = {"token": f"azk{secrets.token_hex(8)}", "label": label, "created": int(time.time() * 1000)}
    tokens.append(tok)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tokens, indent=1), encoding="utf-8")
    return tok


class Canary:
    def __init__(self, tokens: list[dict] | None = None):
        self.tokens: dict[str, dict] = {}
        self.digests: dict[str, tuple[dict, str]] = {}
        for t in tokens or []:
            self.register(t)

    def register(self, t: dict) -> None:
        tok = t["token"]
        self.tokens[tok.lower()] = t
        for algo in ("md5", "sha1", "sha256"):
            self.digests[hashlib.new(algo, tok.encode()).hexdigest()] = (t, algo)

    def __len__(self) -> int:
        return len(self.tokens)

    def scan(self, layers: list[tuple[str, str, str]]) -> list[dict]:
        """layers: (key, value, via) from decode.expand. Returns hits (no raw payload)."""
        if not self.tokens:
            return []
        hits, seen = [], set()
        for key, value, via in layers:
            low = value.lower()
            for tok, t in self.tokens.items():
                if tok in low and tok not in seen:
                    seen.add(tok)
                    hits.append({"label": t["label"], "token": t["token"][:9] + "…", "field": key, "via": via or "plain"})
            if len(value) >= 32:
                for d, (t, algo) in self.digests.items():
                    if d in low and t["token"].lower() not in seen:
                        seen.add(t["token"].lower())
                        hits.append({"label": t["label"], "token": t["token"][:9] + "…", "field": key,
                                     "via": f"{via}>{algo}" if via else algo})
        return hits
