"""Host -> tracker -> parent company, from bundled Exodus Privacy + DDG Tracker Radar data."""
from __future__ import annotations

import json
from functools import lru_cache

from .config import DATA_DIR
from .schema import Tracker


class TrackerDB:
    def __init__(self, path=DATA_DIR / "trackers.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {"trackers": {}, "owners": {}}
        self.trackers: dict[str, list[str]] = data.get("trackers", {})
        self.owners: dict[str, str] = data.get("owners", {})
        self.lookup = lru_cache(maxsize=4096)(self._lookup)

    @staticmethod
    def _suffixes(host: str):
        parts = host.lower().rstrip(".").split(".")
        for i in range(len(parts) - 1):
            yield ".".join(parts[i:])

    def _lookup(self, host: str) -> tuple[Tracker | None, str]:
        """Returns (tracker or None, company). Longest matching suffix wins."""
        tracker = None
        company = ""
        for suf in self._suffixes(host):
            if tracker is None and suf in self.trackers:
                name, cat, owner = self.trackers[suf]
                tracker = Tracker(name=name, category=cat)
                company = company or owner
            if not company and suf in self.owners:
                company = self.owners[suf]
            if tracker and company:
                break
        # Prefer the legal entity from DDG owners over the SDK-level owner string.
        for suf in self._suffixes(host):
            if suf in self.owners:
                company = self.owners[suf]
                break
        return tracker, company
