"""Synthetic demo session generator. All identities are fake (azkaban.test / 555 numbers).

    azkaban demo-session azkaban-agent/demo/demo.azk

The story: a "Flashlight" app ships contacts + GPS to Meta, the same advertising ID
shows up from three apps, a shopping app sends the SHA-256 of your email to an
attribution SDK, a banking app pins its certificate, and trackers keep beaconing
while you're idle.
"""
from __future__ import annotations

import base64
import hashlib
import json
import random
import time
import uuid
from pathlib import Path

from .tcf import encode as tcf_encode

IDENTITY = {
    "emails": ["hermione.demo@azkaban.test"],
    "phones": ["+919876500042"],
    "adids": ["6f1c2a9e-4b7d-4e21-9c3a-5d8e7f0a1b2c"],
}
EMAIL = IDENTITY["emails"][0]
PHONE = IDENTITY["phones"][0]
ADID = IDENTITY["adids"][0]
IMEI = "490154203237518"
LAT, LNG = "12.971599", "77.594566"
# Consent for storage/ads/measurement purposes; vendor 755 = Google Advertising Products.
TCF = tcf_encode([1, 2, 3, 4, 7, 9, 10], [755, 793])


def _sha256(s: str) -> str:
    return hashlib.sha256(s.strip().lower().encode()).hexdigest()


def _md5(s: str) -> str:
    return hashlib.md5(s.strip().lower().encode()).hexdigest()


def _rec(ts: int, app: str, host: str, ip: str, method="POST", path="/", body="", query="",
         headers=None, decrypted=True, nbytes=None, tsi=5.0) -> dict:
    return {
        "id": uuid.uuid4().hex, "ts": ts, "app": app, "host": host, "method": method,
        "path": path, "ip": ip, "bytes": nbytes if nbytes is not None else len(body) + len(query) + 900,
        "decrypted": decrypted, "headers": headers or {"user-agent": f"{app}/3.2 (Android 14)"},
        "query": query, "body": body, "note": "" if decrypted else "certificate pinned (client rejected CA)",
        "tsi": tsi,
    }


def generate(seed: int = 7) -> list[dict]:
    rnd = random.Random(seed)
    t = int(time.time() * 1000)
    out: list[dict] = []

    def at(dt_ms: int) -> int:
        nonlocal t
        t += dt_ms
        return t

    # 1. User opens Flashlight Pro. It phones Meta with GPS, contacts and the ad ID.
    out.append(_rec(at(400), "Flashlight Pro", "graph.facebook.com", "157.240.16.35",
                    path="/v17.0/activities", tsi=1.2,
                    body=json.dumps({"advertiser_id": ADID, "event": "app_open",
                                     "loc": {"lat": LAT, "lng": LNG},
                                     "contacts": [{"name": "Ron", "phone": "+15555550101"},
                                                  {"name": "Ginny", "phone": "+15555550102"},
                                                  {"name": "Luna", "phone": "+15555550103"}]})))
    out.append(_rec(at(700), "Flashlight Pro", "app-measurement.com", "142.250.193.142",
                    path="/a", tsi=1.9,
                    body=f"gmp_version=1&app_instance_id={uuid.uuid4().hex}&adid={ADID}&imei={IMEI}"))

    # 2. Shopping app: hashed email to AppsFlyer, base64'd phone to Branch.
    out.append(_rec(at(1500), "InstaShop", "launches.appsflyer.com", "18.66.122.51",
                    path="/api/v6.9/androidevent", tsi=3.0,
                    body=json.dumps({"advertiserId": ADID, "af_events": "purchase",
                                     "user_emails": [_sha256(EMAIL)], "em_md5": _md5(EMAIL)})))
    out.append(_rec(at(800), "InstaShop", "api2.branch.io", "104.18.11.37", path="/v2/event/standard", tsi=3.8,
                    body=json.dumps({"user_data": {"aaid": ADID,
                                                   "developer_identity": base64.b64encode(PHONE.encode()).decode()}})))
    out.append(_rec(at(600), "InstaShop", "graph.facebook.com", "157.240.16.35", path="/v17.0/app/activities",
                    tsi=4.1, body=f"advertiser_id={ADID}&event=fb_mobile_purchase&ud[em]={_sha256(EMAIL)}"))

    # 3. Fitness app: GPS trail to its own backend + Firebase, ad ID again.
    out.append(_rec(at(2000), "FitTrack", "api.fittrack.example", "35.154.20.11", path="/v1/run",
                    tsi=2.0, body=json.dumps({"route": [{"lat": "12.9716", "lng": "77.5946"}], "email": EMAIL})))
    out.append(_rec(at(500), "FitTrack", "app-measurement.com", "142.250.193.142", path="/a",
                    tsi=2.4, body=f"gaid={ADID}&ev=workout_end"))
    out.append(_rec(at(300), "FitTrack", "graph.facebook.com", "157.240.16.35", path="/v17.0/activities",
                    tsi=2.6, body=f"advertiser_id={ADID}&event=workout"))

    # 4. News app with a TCF consent string to Google ads.
    out.append(_rec(at(1200), "NewsDaily", "securepubads.g.doubleclick.net", "142.250.77.66", method="GET",
                    path="/gampad/ads", tsi=1.0, query=f"gdpr=1&gdpr_consent={TCF}&rdid={ADID}&is_lat=0"))

    # 5. Banking app pins its certificate: metadata only.
    out.append(_rec(at(900), "SecureBank", "netbanking.securebank.example", "13.235.1.20", method="CONNECT",
                    path="", decrypted=False, nbytes=0, tsi=0.8))

    # 6. User puts the phone down. Trackers keep beaconing.
    idle = 30.0
    for i in range(24):
        app, host, ip = rnd.choice([
            ("Flashlight Pro", "graph.facebook.com", "157.240.16.35"),
            ("Flashlight Pro", "settings.crashlytics.com", "142.250.183.3"),
            ("NewsDaily", "securepubads.g.doubleclick.net", "142.250.77.66"),
            ("InstaShop", "launches.appsflyer.com", "18.66.122.51"),
            ("FitTrack", "app-measurement.com", "142.250.193.142"),
        ])
        idle += rnd.uniform(15, 40)
        body = f"adid={ADID}&hb=1" if "crashlytics" not in host else json.dumps({"session": uuid.uuid4().hex})
        if i % 6 == 0 and app == "Flashlight Pro":
            body += f"&lat={LAT}&lng={LNG}"
        out.append(_rec(at(rnd.randint(1500, 4000)), app, host, ip, path="/beacon", body=body, tsi=round(idle, 1)))
    return out


def write(path: str | Path) -> int:
    recs = generate()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"azk": 1, "created": recs[0]["ts"], "source": "synthetic",
                            "identity": IDENTITY}) + "\n")
        for r in recs:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    return len(recs)
