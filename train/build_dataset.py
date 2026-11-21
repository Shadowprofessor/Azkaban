"""Build the tracker-classifier dataset from PUBLIC sources (setup-time only, no user data).

    python train/build_dataset.py [--months 12] [--tranco 50000]

Labels come from independent public lists — never from our own rubric:
  positives  DDG Tracker Radar (default=block), Exodus, EasyList, EasyPrivacy, AdGuard Base +
             Tracking Protection, Disconnect (tracking categories), Peter Lowe's list
  negatives  Tranco + Cisco Umbrella popular domains that appear on NO positive list
Real behaviour: WhoTracks.me monthly per-domain aggregates (top-2000 third parties per month,
trackers AND non-trackers). Rows with real behaviour carry is_real_behavior=True.

Everything is deduplicated to the registrable domain. Output: train/data/tracker_dataset.parquet
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "azkaban-agent"))
sys.path.insert(0, str(ROOT / "train"))
from azkaban_agent.net import http_get  # noqa: E402  (egress guard, allow_setup=True)
from features import registrable  # noqa: E402

CACHE = ROOT / "train" / "cache"
OUT = ROOT / "train" / "data" / "tracker_dataset.parquet"

SOURCES = {
    "easylist": "https://easylist.to/easylist/easylist.txt",
    "easyprivacy": "https://easylist.to/easylist/easyprivacy.txt",
    "adguard_base": "https://filters.adtidy.org/extension/chromium/filters/2.txt",
    "adguard_tracking": "https://filters.adtidy.org/extension/chromium/filters/3.txt",
    "disconnect": "https://raw.githubusercontent.com/disconnectme/disconnect-tracking-protection/master/services.json",
    "peterlowe": "https://pgl.yoyo.org/adservers/serverlist.php?hostformat=nohtml&showintro=0&mimetype=plaintext",
    "ddg_tds": "https://staticcdn.duckduckgo.com/trackerblocking/v5/current/extension-tds.json",
    "exodus": "https://reports.exodus-privacy.eu.org/api/trackers",
    "tranco": "https://tranco-list.eu/download/daily/top-1m.csv.zip",
    "umbrella": "https://s3-us-west-1.amazonaws.com/umbrella-static/top-1m.csv.zip",
    "trackerdb": "https://raw.githubusercontent.com/whotracksme/whotracks.me/master/whotracksme/data/assets/trackerdb.sql",
}
WTM = "https://s3.amazonaws.com/data.whotracks.me/{month}/global/domains.csv"

DOMAIN = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$")
# EasyList/AdGuard domain-anchored rule that blocks the WHOLE domain: ||example.com^ (optionally
# $third-party / $all / $script etc. — but not restricted to specific first-party domains).
ABP_DOMAIN_RULE = re.compile(r"^\|\|([a-z0-9.-]+\.[a-z]{2,})\^(?:\$(.*))?$")

# Map every source's category vocabulary onto four classes.
CATEGORY_MAP = {
    "advertising": "advertising", "advertisement": "advertising", "ad motivated tracking": "advertising",
    "adult_advertising": "advertising", "ad fraud": "advertising",
    "analytics": "analytics", "site_analytics": "analytics", "audience measurement": "analytics",
    "third-party analytics marketing": "analytics", "session replay": "analytics", "action pixels": "analytics",
    "social": "social", "social_media": "social", "social network": "social", "social - share": "social",
    "social - comment": "social", "federated login": "social",
    "fingerprintinginvasive": "fingerprinting", "fingerprintinggeneral": "fingerprinting",
    "fingerprinting": "fingerprinting", "cryptomining": "fingerprinting", "malware": "fingerprinting",
}
CLASSES = ["advertising", "analytics", "social", "fingerprinting"]
BULK = {"easylist", "easyprivacy", "adguard_base", "adguard_tracking", "peterlowe"}


def fetch(name: str, url: str) -> bytes:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (name + Path(url.split("?")[0]).suffix.replace(".php", ".txt"))
    if path.exists() and path.stat().st_size > 0:
        return path.read_bytes()
    r = http_get(url, allow_setup=True, timeout=180)
    r.raise_for_status()
    path.write_bytes(r.content)
    return r.content


def norm(d: str) -> str | None:
    d = d.strip().lower().lstrip(".").rstrip(".")
    if not DOMAIN.match(d):
        return None
    return registrable(d)


def abp_domains(text: str) -> set[str]:
    out = set()
    for line in text.splitlines():
        m = ABP_DOMAIN_RULE.match(line.strip())
        if not m:
            continue
        opts = (m.group(2) or "").split(",")
        # Skip rules limited to particular sites (domain=) or exceptions/no-op options.
        if any(o.startswith(("domain=", "~third-party", "badfilter", "removeparam", "redirect", "csp", "cookie")) for o in opts):
            continue
        if d := norm(m.group(1)):
            out.add(d)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--tranco", type=int, default=50000)
    a = ap.parse_args()

    pos: dict[str, set[str]] = defaultdict(set)       # domain -> sources
    cat_votes: dict[str, list[str]] = defaultdict(list)
    fetched, skipped = [], []

    def add(d: str | None, source: str, category: str | None = None) -> None:
        if not d:
            return
        pos[d].add(source)
        if category and (c := CATEGORY_MAP.get(category.lower().strip())):
            # Category-specific sources outvote bulk blocklists that only say "ad" / "privacy".
            cat_votes[d].extend([c] * (1 if source in BULK else 3))

    def source(name: str, fn) -> None:
        try:
            fn(fetch(name, SOURCES[name]))
            fetched.append(name)
        except Exception as e:  # floor: skip what won't fetch
            skipped.append(f"{name}: {type(e).__name__}: {e}"[:160])

    source("ddg_tds", lambda b: [
        add(norm(d), "ddg_tds", (t.get("categories") or [None])[0])
        for d, t in json.loads(b)["trackers"].items() if t.get("default") == "block"
    ])

    def exodus(b: bytes) -> None:
        for t in json.loads(b)["trackers"].values():
            cat = (t.get("categories") or [None])[0]
            for part in (t.get("network_signature") or "").split("|"):
                add(norm(part.replace("\\.", ".").replace("\\", "").strip("^$")), "exodus", cat)
    source("exodus", exodus)

    for name, cat in (("easylist", "advertising"), ("easyprivacy", "analytics"),
                      ("adguard_base", "advertising"), ("adguard_tracking", "analytics")):
        source(name, lambda b, n=name, c=cat: [add(d, n, c) for d in abp_domains(b.decode("utf-8", "replace"))])

    def disconnect(b: bytes) -> None:
        cats = json.loads(b)["categories"]
        for cat, entries in cats.items():
            if cat in ("Content", "Email", "EmailStrict", "EmailAggressive"):
                continue
            for entry in entries:
                for _org, urls in entry.items():
                    for _site, doms in urls.items():
                        if isinstance(doms, list):
                            for d in doms:
                                add(norm(d), "disconnect", "social" if cat == "Disconnect" else cat)
    source("disconnect", disconnect)
    source("peterlowe", lambda b: [add(norm(l), "peterlowe", "advertising") for l in b.decode().splitlines()])

    # WhoTracks.me TrackerDB categories (CC-BY-NC-SA-4.0) as extra category votes only.
    def trackerdb(b: bytes) -> None:
        sql = b.decode("utf-8", "replace")
        tracker_cat = {m.group(1): m.group(2) for m in re.finditer(r"INSERT INTO trackers VALUES\('([^']+)','[^']*',(\d+|NULL)", sql)}
        cat_name = {m.group(1): m.group(2) for m in re.finditer(r"INSERT INTO categories VALUES\((\d+),'([^']+)'", sql)}
        for m in re.finditer(r"INSERT INTO tracker_domains VALUES\('([^']+)','([^']+)'", sql):
            d = norm(m.group(2))
            c = cat_name.get(tracker_cat.get(m.group(1), ""), "")
            if d and d in pos and c:
                if CATEGORY_MAP.get(c):
                    cat_votes[d].extend([CATEGORY_MAP[c]] * 3)
    source("trackerdb", trackerdb)

    # Negatives: popular domains on no positive list.
    neg: dict[str, set[str]] = defaultdict(set)

    def toplist(name: str, take: int):
        def fn(b: bytes) -> None:
            with zipfile.ZipFile(io.BytesIO(b)) as z:
                rows = csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8"))
                n = 0
                for row in rows:
                    if len(row) < 2:
                        continue
                    d = norm(row[1])
                    if d and d not in pos:
                        neg[d].add(name)
                    n += 1
                    if n >= take:
                        break
        return fn
    source("tranco", toplist("tranco", a.tranco))
    source("umbrella", toplist("umbrella", a.tranco))

    # Real behaviour: WhoTracks.me per-domain monthly stats, latest months first.
    behaviour: dict[str, dict] = {}
    today = date.today()
    months = []
    y, m = today.year, today.month
    for _ in range(a.months + 1):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        months.append(f"{y}-{m:02d}")
    wtm_months = []
    for mo in months:
        try:
            raw = fetch(f"wtm_{mo}", WTM.format(month=mo))
        except Exception as e:
            skipped.append(f"whotracks {mo}: {type(e).__name__}")
            continue
        wtm_months.append(mo)
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
            d = norm(row["host_tld"])
            if d and d not in behaviour:  # keep the most recent month's aggregate
                behaviour[d] = {k: row[k] for k in row if k not in ("", "country", "host_tld")}
    if wtm_months:
        fetched.append(f"whotracks({len(wtm_months)} months)")

    rows = []
    for d in sorted(set(pos) | set(neg) | set(behaviour)):
        label = int(d in pos)
        votes = cat_votes.get(d, [])
        category = max(CLASSES, key=votes.count) if label and votes else ("advertising" if label else "none")
        srcs = sorted(pos.get(d, set()) | neg.get(d, set()) | ({"whotracks"} if d in behaviour else set()))
        b = behaviour.get(d, {})
        rows.append({
            "domain": d, "label": label, "category": category, "n_positive_sources": len(pos.get(d, ())),
            "source": ",".join(srcs), "is_real_behavior": d in behaviour,
            **{f"wtm_{k}": pd.to_numeric(v, errors="coerce") if v != "" else None for k, v in b.items() if k != "month"},
            "wtm_month": b.get("month"),
        })
    df = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)

    real = df[df.is_real_behavior]
    info = {"built": date.today().isoformat(), "sources_fetched": fetched, "sources_skipped": skipped,
            "whotracks_months": sorted(wtm_months), "rows": len(df), "positives": int(df.label.sum()),
            "negatives": int((1 - df.label).sum()), "real_behavior_rows": len(real),
            "real_positives": int(real.label.sum()), "real_negatives": int((1 - real.label).sum()),
            "real_categories": real.category.value_counts().to_dict(),
            "label_policy": "positive = registrable domain blocked domain-wide by >=1 public list; "
                            "negative = Tranco/Umbrella top domain on no list"}
    (OUT.parent / "dataset_info.json").write_text(json.dumps(info, indent=1))
    print(f"fetched: {fetched}")
    if skipped:
        print("skipped:", *skipped, sep="\n  ")
    print(f"rows={len(df)}  positives={int(df.label.sum())}  negatives={int((1 - df.label).sum())}")
    print(f"REAL-behaviour rows={len(real)}  positives={int(real.label.sum())}  negatives={int((1 - real.label).sum())}")
    print("categories (positives):", df[df.label == 1].category.value_counts().to_dict())
    print("real-behaviour categories:", real.category.value_counts().to_dict())
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
