"""Turn a raw capture record into (key, value) pairs for scanning."""
from __future__ import annotations

import json
from urllib.parse import parse_qsl

MAX_FIELDS = 2000


def _flatten(obj, prefix: str, out: list[tuple[str, str]]) -> None:
    if len(out) >= MAX_FIELDS:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _flatten(v, f"{prefix}[{i}]", out)
    elif obj is not None:
        out.append((prefix, str(obj)))


def parse_text(text: str, prefix: str = "") -> list[tuple[str, str]]:
    """Best-effort structured parse: JSON, then form-encoding, else the whole string."""
    out: list[tuple[str, str]] = []
    t = text.strip()
    if not t:
        return out
    if t[:1] in "{[":
        try:
            _flatten(json.loads(t), prefix, out)
            return out
        except ValueError:
            pass
    if "=" in t and "\n" not in t and " " not in t[:200]:
        pairs = parse_qsl(t, keep_blank_values=False)
        if pairs:
            for k, v in pairs:
                key = f"{prefix}.{k}" if prefix else k
                sub = parse_text(v, key) if v[:1] in "{[" else []
                out.extend(sub or [(key, v)])
            return out
    out.append((prefix or "body", t))
    return out


def record_fields(raw: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if raw.get("query"):
        out += parse_text(raw["query"], "")
    for k, v in (raw.get("headers") or {}).items():
        if k.lower() == "cookie":
            for part in v.split(";"):
                if "=" in part:
                    ck, cv = part.split("=", 1)
                    out.append((f"cookie.{ck.strip()}", cv.strip()))
        else:
            out.append((f"header.{k.lower()}", v))
    if raw.get("body"):
        out += parse_text(raw["body"], "")
    if raw.get("path"):
        out.append(("path", raw["path"]))
    return out[:MAX_FIELDS]
