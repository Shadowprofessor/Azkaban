"""Build azkaban_agent/data/trackers.json from Exodus Privacy + DuckDuckGo Tracker Radar (TDS).

    curl -o exodus.json https://reports.exodus-privacy.eu.org/api/trackers
    curl -o tds.json https://staticcdn.duckduckgo.com/trackerblocking/v5/current/extension-tds.json
    python -I build_trackers.py exodus.json tds.json out/trackers.json

Output:
    {"trackers": {domain: [name, category, company]}, "owners": {domain: company}, "sources": {...}}
"""
import json
import re
import sys
from datetime import date

DOMAIN = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$")


# Gaps in both lists that matter for mobile demos.
EXTRA = {
    "app-measurement.com": ["Google Firebase Analytics", "Analytics", "Google LLC"],
    "crashlytics.com": ["Google Crashlytics", "Crash reporting", "Google LLC"],
    "firebaselogging-pa.googleapis.com": ["Google Firebase Analytics", "Analytics", "Google LLC"],
    "graph.facebook.com": ["Facebook Graph API", "Advertising", "Meta Platforms, Inc."],
}


def exodus_domains(sig: str) -> list[str]:
    out = []
    for part in (sig or "").split("|"):
        d = part.replace("\\.", ".").strip().strip("^$").lstrip(".").lower()
        d = d.replace("\\", "")
        if DOMAIN.match(d):
            out.append(d)
    return out


def exodus_owner(desc: str) -> str:
    m = re.search(r"## Ownership\s*\r?\n+([^\r\n#]+)", desc or "")
    return m.group(1).strip().strip("_*") if m else ""


def main(exodus_path: str, tds_path: str, out_path: str) -> None:
    trackers: dict[str, list[str]] = {}
    owners: dict[str, str] = {}

    tds = json.load(open(tds_path, encoding="utf-8"))
    for dom, t in tds.get("trackers", {}).items():
        owner = (t.get("owner") or {}).get("displayName") or (t.get("owner") or {}).get("name") or ""
        cats = t.get("categories") or []
        trackers[dom.lower()] = [owner or dom, (cats[0] if cats else "Tracker"), owner]
    for dom, ent in tds.get("domains", {}).items():
        owners[dom.lower()] = ent

    ex = json.load(open(exodus_path, encoding="utf-8"))["trackers"]
    for t in ex.values():
        owner = exodus_owner(t.get("description", "")) or t["name"]
        cat = (t.get("categories") or ["Tracker"])[0]
        for d in exodus_domains(t.get("network_signature", "")):
            # Exodus names the SDK (e.g. "Google Firebase Analytics"); prefer it over DDG's owner name.
            prev = trackers.get(d)
            trackers[d] = [t["name"], cat, (prev[2] if prev and prev[2] else owner)]

    trackers.update(EXTRA)

    out = {
        "sources": {
            "exodus": "https://reports.exodus-privacy.eu.org/api/trackers",
            "ddg_tds": "https://staticcdn.duckduckgo.com/trackerblocking/v5/current/extension-tds.json",
            "built": date.today().isoformat(),
        },
        "trackers": dict(sorted(trackers.items())),
        "owners": dict(sorted(owners.items())),
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    print(f"trackers={len(trackers)} owners={len(owners)} -> {out_path}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
