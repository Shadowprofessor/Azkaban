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


def find(pairs: list[tuple[str, str]]) -> Tcf | None:
    for k, v in pairs:
        if TCF_KEYS.search(k):
            t = decode(v)
            if t:
                return t
    return None
