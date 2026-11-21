"""Encoding-aware unwrapping: URL-decode, base64, hex and gzip layers (depth-limited)."""
from __future__ import annotations

import base64
import binascii
import re
import zlib
from urllib.parse import unquote_plus

from .fields import parse_text

B64 = re.compile(r"^[A-Za-z0-9+/_-]{12,}={0,2}$")
HEX = re.compile(r"^(?:[0-9a-fA-F]{2}){8,}$")
HASH_LENS = {32, 40, 64}
MAX_DEPTH = 2
MAX_LEN = 16384
MAX_DECOMPRESSED = 256 * 1024  # bomb guard: never inflate beyond this


def _printable(b: bytes) -> str | None:
    try:
        s = b.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not s:
        return None
    ok = sum(ch.isprintable() or ch in "\r\n\t" for ch in s)
    return s if ok / len(s) > 0.9 else None


def _bounded_inflate(b: bytes, wbits: int) -> bytes | None:
    """Inflate at most MAX_DECOMPRESSED bytes: a bomb is truncated, never fully expanded."""
    try:
        return zlib.decompressobj(wbits).decompress(b, MAX_DECOMPRESSED)
    except zlib.error:
        return None


def _maybe_gunzip(b: bytes) -> bytes | None:
    if b[:2] == b"\x1f\x8b":
        return _bounded_inflate(b, 16 + zlib.MAX_WBITS)  # gzip container
    if b[:1] == b"\x78":
        return _bounded_inflate(b, zlib.MAX_WBITS)  # zlib container
    return None


def unwrap(value: str) -> list[tuple[str, str]]:
    """Returns [(via, decoded_text)] for every layer that decodes to readable text."""
    out: list[tuple[str, str]] = []
    v = value.strip()[:MAX_LEN]
    if "%" in v:
        u = unquote_plus(v)
        if u != v:
            out.append(("url", u))
    if B64.match(v) and len(v) not in HASH_LENS:
        try:
            raw = base64.b64decode(v + "=" * (-len(v) % 4), altchars=b"-_" if ("-" in v or "_" in v) else None)
            gz = _maybe_gunzip(raw)
            if gz is not None and (t := _printable(gz)):
                out.append(("base64+gzip", t))
            elif t := _printable(raw):
                if len(t) >= 4:
                    out.append(("base64", t))
        except (binascii.Error, ValueError):
            pass
    if HEX.match(v) and len(v) not in HASH_LENS:
        raw = bytes.fromhex(v)
        gz = _maybe_gunzip(raw)
        if t := _printable(gz if gz is not None else raw):
            out.append(("hex+gzip" if gz is not None else "hex", t))
    return out


def expand(pairs: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    """Original pairs (via='') plus decoded layers, each re-parsed into fields."""
    result: list[tuple[str, str, str]] = [(k, v, "") for k, v in pairs]
    frontier = [(k, v, "") for k, v in pairs]
    for _ in range(MAX_DEPTH):
        nxt = []
        for k, v, via in frontier:
            for layer, text in unwrap(v):
                tag = f"{via}>{layer}" if via else layer
                for k2, v2 in parse_text(text, k):
                    nxt.append((k2, v2, tag))
        result.extend(nxt)
        frontier = nxt
        if not frontier:
            break
    return result
