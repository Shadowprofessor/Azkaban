"""IP -> country, fully offline.

Uses MaxMind GeoLite2-Country if AZK_GEOIP_DB points at it, otherwise the bundled
DB-IP Country Lite database (same .mmdb format, CC-BY 4.0, https://db-ip.com).
Fetch it with `azkaban fetch-geo`.
"""
from __future__ import annotations

import gzip
import ipaddress
import shutil
from datetime import date
from functools import lru_cache
from pathlib import Path

from .config import DATA_DIR

DBIP_PATH = DATA_DIR / "dbip-country-lite.mmdb"
DBIP_URL = "https://download.db-ip.com/free/dbip-country-lite-{ym}.mmdb.gz"


class Geo:
    def __init__(self, geoip_db: str = ""):
        self.reader = None
        self.source = ""
        try:
            import maxminddb
        except ImportError:
            return
        for p in (Path(geoip_db) if geoip_db else None, DBIP_PATH):
            if p and p.is_file():
                try:
                    self.reader = maxminddb.open_database(str(p))
                    self.source = p.name
                    break
                except Exception:
                    continue
        self.country = lru_cache(maxsize=8192)(self._country)

    @property
    def available(self) -> bool:
        return self.reader is not None

    def _country(self, ip: str) -> str:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return "ZZ"
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            return "ZZ"
        if not self.reader:
            return "ZZ"
        try:
            rec = self.reader.get(ip) or {}
            return (rec.get("country") or rec.get("registered_country") or {}).get("iso_code", "ZZ")
        except Exception:
            return "ZZ"

    def country(self, ip: str) -> str:  # replaced per-instance by the cached version
        return self._country(ip)


def fetch_dbip(dest: Path = DBIP_PATH) -> Path:
    import requests
    today = date.today()
    tried = []
    for y, m in ((today.year, today.month), (today.year - (today.month == 1), (today.month - 2) % 12 + 1)):
        url = DBIP_URL.format(ym=f"{y}-{m:02d}")
        tried.append(url)
        r = requests.get(url, timeout=120, stream=True)
        if r.status_code == 200:
            tmp = dest.with_suffix(".gz")
            with open(tmp, "wb") as f:
                shutil.copyfileobj(r.raw, f)
            with gzip.open(tmp) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            tmp.unlink()
            return dest
    raise RuntimeError(f"could not download DB-IP lite from {tried}")
