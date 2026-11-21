"""IAB TCF v2 consent-string decoder (core segment only): vendor + purpose consents."""
from __future__ import annotations

import base64
import re

from .schema import Tcf

TCF_KEYS = re.compile(r"(^|[._])(gdpr_consent|euconsent-v2|euconsent|tcf_?string|tc_?string|consent_string|addtl_consent_tc)$", re.I)


class _Bits:
    def __init__(self, data: bytes):
        self.bits = "".join(f"{b:08b}" for b in data)
        self.pos = 0

    def take(self, n: int) -> int:
        if self.pos + n > len(self.bits):
            raise ValueError("truncated")
        v = int(self.bits[self.pos:self.pos + n], 2)
        self.pos += n
        return v


def decode(tc: str) -> Tcf | None:
    core = tc.split(".")[0].strip()
    if len(core) < 20:
        return None
    try:
        b = _Bits(base64.urlsafe_b64decode(core + "=" * (-len(core) % 4)))
        if b.take(6) != 2:
            return None
        b.take(36); b.take(36); b.take(12); b.take(12); b.take(6); b.take(12)
        b.take(12); b.take(6); b.take(1); b.take(1); b.take(12)
        purposes_bits = b.take(24)
        b.take(24); b.take(1); b.take(12)
        purposes = [i + 1 for i in range(24) if purposes_bits & (1 << (23 - i))]
        max_vendor = b.take(16)
        vendors: list[int] = []
        if b.take(1) == 0:
            vendors = [i + 1 for i in range(max_vendor) if b.take(1)]
        else:
            for _ in range(b.take(12)):
                if b.take(1):
                    s, e = b.take(16), b.take(16)
                    vendors.extend(range(s, e + 1))
                else:
                    vendors.append(b.take(16))
        return Tcf(vendors=vendors, purposes=purposes)
    except (ValueError, base64.binascii.Error):
        return None


def encode(purposes: list[int], vendors: list[int], cmp_id: int = 10) -> str:
    """Minimal TCF v2 core-segment encoder (bitfield vendors). Used for tests and demo data."""
    ds = 16_000_000_000 // 100  # deciseconds, fixed for determinism
    max_v = max(vendors) if vendors else 0
    fields = [
        (2, 6), (ds, 36), (ds, 36), (cmp_id, 12), (1, 12), (1, 6), (ord("E") - 65 << 6 | ord("N") - 65, 12),
        (100, 12), (2, 6), (1, 1), (0, 1), (0, 12),
        (sum(1 << (23 - (p - 1)) for p in purposes), 24), (0, 24), (0, 1), (ord("I") - 65 << 6 | ord("N") - 65, 12),
        (max_v, 16), (0, 1),
    ]
    bits = "".join(f"{v:0{n}b}" for v, n in fields)
    bits += "".join("1" if i + 1 in set(vendors) else "0" for i in range(max_v))
    bits += "0" * (-len(bits) % 8)
    raw = int(bits, 2).to_bytes(len(bits) // 8, "big")
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def find(pairs: list[tuple[str, str]]) -> Tcf | None:
    for k, v in pairs:
        if TCF_KEYS.search(k):
            t = decode(v)
            if t:
                return t
    return None
