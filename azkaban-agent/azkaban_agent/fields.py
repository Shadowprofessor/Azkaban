"""Turn a raw capture record into (key, value) pairs for scanning."""
from __future__ import annotations

import json
from urllib.parse import parse_qsl

MAX_FIELDS = 2000
MAX_DEPTH = 32               # JSON nesting we flatten
MAX_BODY = 64 * 1024         # same cap as live capture; replayed records are re-capped here
MAX_QUERY = 16 * 1024
MAX_HEADER = 8 * 1024


def _too_deep(t: str, limit: int = 64) -> bool:
    """Cheap pre-check so json.loads never recurses on hostile nesting."""
    depth = 0
    for ch in t:
        if ch in "[{":
            depth += 1
            if depth > limit:
                return True
        elif ch in "]}":
            depth -= 1
    return False


def _flatten(obj, prefix: str, out: list[tuple[str, str]], depth: int = 0) -> None:
    if len(out) >= MAX_FIELDS:
        return
    if depth > MAX_DEPTH:
        out.append((prefix, json.dumps(obj)[:2000]))
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(v, f"{prefix}.{k}" if prefix else str(k), out, depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _flatten(v, f"{prefix}[{i}]", out, depth + 1)
    elif obj is not None:
        out.append((prefix, str(obj)))


def parse_text(text: str, prefix: str = "", _depth: int = 0) -> list[tuple[str, str]]:
    """Best-effort structured parse: JSON, then form-encoding, else the whole string."""
    out: list[tuple[str, str]] = []
    t = text.strip()
    if not t:
        return out
    if _depth > 4:  # form values that themselves look structured: bounded recursion
        return [(prefix or "body", t)]
    if t[:1] in "{[" and not _too_deep(t):
        try:
            _flatten(json.loads(t), prefix, out)
            return out
        except (ValueError, RecursionError):
            pass
    if "=" in t and "\n" not in t and " " not in t[:200]:
        pairs = parse_qsl(t, keep_blank_values=False)
        if pairs:
            for k, v in pairs:
                key = f"{prefix}.{k}" if prefix else k
                sub = parse_text(v, key, _depth + 1) if v[:1] in "{[" else []
                out.extend(sub or [(key, v)])
            return out
    out.append((prefix or "body", t))
    return out


def _s(v, cap: int) -> str:
    return v[:cap] if isinstance(v, str) else ""


def record_fields(raw: dict) -> list[tuple[str, str]]:
    """Untrusted input: every field is type-checked and size-capped before parsing."""
    out: list[tuple[str, str]] = []
    query, body, path = _s(raw.get("query"), MAX_QUERY), _s(raw.get("body"), MAX_BODY), _s(raw.get("path"), 2048)
    headers = raw.get("headers") if isinstance(raw.get("headers"), dict) else {}
    if query:
        out += parse_text(query, "")
    for k, v in list(headers.items())[:100]:
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        v = v[:MAX_HEADER]
        if k.lower() == "cookie":
            for part in v.split(";"):
                if "=" in part:
                    ck, cv = part.split("=", 1)
                    out.append((f"cookie.{ck.strip()}", cv.strip()))
        else:
            out.append((f"header.{k.lower()}", v))
    if body:
        out += parse_text(body, "")
    if path:
        out.append(("path", path))
    return out[:MAX_FIELDS]
