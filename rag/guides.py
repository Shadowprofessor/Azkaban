"""Remediation retrieval: turn a finding into steps the user can actually follow.

The agent is good at saying what leaked. On its own that leaves the user with a verdict
and nothing to do about it. This module answers the next question — "so what do I change?"
— from a corpus of public, platform-specific privacy guides (ported from the `yash`
branch), falling back to generic steps when no guide covers the destination.

Everything here is public reference text. The only input is a company or host name and a
category, both of which the agent already shows on screen.
"""
from __future__ import annotations

from .bm25 import BM25Index, tokens
from .corpus import guide_text, guides

#: Destination company (as the tracker DB names it) -> guide platform.
#: The tracker DB speaks in corporate owners; the guides speak in products.
PLATFORM_OF: dict[str, str] = {
    "google": "Google", "alphabet": "Google", "youtube": "Google", "doubleclick": "Google",
    "google analytics": "Google", "admob": "Google", "firebase": "Google",
    "meta": "Instagram", "facebook": "Instagram", "instagram": "Instagram",
    "spotify": "Spotify",
}

#: Category of a finding -> guide category. Insight kinds and PII types both land here.
CATEGORY_OF: dict[str, str] = {
    "gps": "location", "contact": "contacts", "email": "security", "phone": "security",
    "adid": "interests", "imei": "security", "clipboard": "activity",
    "advertising": "interests", "analytics": "activity", "social": "connections",
    "unknown_tracker": "interests", "hashed_pii": "interests", "cross_app": "interests",
    "idle_beacons": "activity", "honeytoken": "security", "beacon_anomaly": "activity",
}

#: Always-available steps, so a finding about an unrecognised destination is still
#: actionable. Deliberately generic: these claim nothing about a specific company.
GENERIC: dict[str, tuple[str, list[str]]] = {
    "location": ("Review stored location history", [
        "Open the app's privacy or location settings and review its location history.",
        "Delete records you no longer need and set the shortest retention the app offers.",
        "In the OS settings, downgrade the app's location permission to 'while using' or deny it.",
    ]),
    "contacts": ("Remove unnecessary contact access", [
        "Review which apps have contacts permission and revoke it where it is not needed.",
        "Where the app uploaded an address book, use its controls to delete the imported copy.",
        "Turn off continuous contact sync so the upload does not repeat.",
    ]),
    "interests": ("Reduce ad profiling", [
        "Open the platform's ad settings and review the inferred interests or ad topics listed.",
        "Turn off ad personalisation and clear the stored interest list.",
        "Reset your device advertising ID, which breaks the link to the profile built against it.",
    ]),
    "activity": ("Limit activity history", [
        "Review the service's saved activity and delete entries you no longer need.",
        "Switch on auto-delete with the shortest window the service offers.",
    ]),
    "security": ("Review devices and app access", [
        "Review active sessions and connected third-party apps on the account.",
        "Sign out of sessions you do not recognise and revoke access you no longer use.",
        "Where the account email is exposed, check whether the service offers a no-reply alias.",
    ]),
    "connections": ("Limit connection visibility", [
        "Review who can see your followers, connections and contact list.",
        "Restrict visibility to the narrowest audience that still works for you.",
    ]),
    "messages": ("Review retained conversations", [
        "Review sensitive conversations and use the service's deletion controls.",
        "Remember that recipients keep their own copies; deletion on your side is not enough.",
    ]),
}
DEFAULT_CATEGORY = "interests"

#: Findings where the MECHANISM decides the remedy, not the data type. A hashed email sent
#: to an ad network is an ad-matching problem, so the fix lives in ad settings, not in
#: account security. For a tripped honeytoken the data type does decide, so it is absent here.
KIND_WINS = frozenset({"hashed_pii", "cross_app", "unknown_tracker", "beacon_anomaly",
                       "idle_beacons"})

#: PII types with a dedicated, specific control the user can go and change. These outrank
#: the mechanism: a GPS leak is fixed in location settings even when the mechanism that
#: surfaced it was cross-app ad-ID profiling. Identifiers (adid, email, phone, imei) have
#: no such control, so for those the mechanism decides.
TYPE_WINS = frozenset({"gps", "contact", "clipboard"})

_index: BM25Index | None = None


def index() -> BM25Index:
    global _index
    if _index is None:
        _index = BM25Index(guides(), guide_text)
    return _index


def platform_for(company_or_host: str) -> str | None:
    """Best-effort map from a traffic destination to a guide platform."""
    s = (company_or_host or "").lower()
    for needle, platform in PLATFORM_OF.items():
        if needle in s:
            return platform
    return None


def category_for(kind_or_type: str) -> str:
    return CATEGORY_OF.get((kind_or_type or "").lower(), DEFAULT_CATEGORY)


def search(query: str, *, platform: str | None = None, category: str | None = None,
           k: int = 5) -> list[dict]:
    """BM25 over the guide corpus, optionally pinned to a platform and/or category."""
    def where(d: dict) -> bool:
        return ((platform is None or d["platform"] == platform)
                and (category is None or d["category"] == category))

    hits = index().search(query, k=k, where=where, tie_key=lambda d: d["id"])
    out = [dict(d, score=round(s, 4)) for s, d in hits]
    if not out and category is not None:
        # Category pinned but nothing matched the words: return the category's guides anyway,
        # since the category itself is evidence of relevance.
        out = [dict(d, score=0.0) for d in guides() if where(d)][:k]
    return out


def remediate(*, company: str = "", host: str = "", kind: str = "",
              pii_types: list[str] | None = None) -> dict:
    """One remediation block for a finding. Always returns something usable.

    `source` says where the steps came from: "guide" when a public guide matched the
    destination, "generic" when the steps are category defaults. The UI should show that
    distinction rather than implying a vendor-specific instruction that was never found.
    """
    target = company or host
    platform = platform_for(target)
    first = (pii_types or [""])[0]
    if first in TYPE_WINS:
        primary = first                     # a specific setting exists; go there
    elif kind in KIND_WINS or not first:
        primary = kind                      # mechanism decides
    else:
        primary = first
    category = category_for(primary)
    query = " ".join(filter(None, [target, kind, category, *(pii_types or [])]))

    hits = search(query, platform=platform, category=category, k=1) if platform else []
    if not hits and platform:
        # This platform has no guide in that category. Its other guides still beat generic
        # steps, so let word overlap choose one; the guide reports its own category.
        hits = search(query, platform=platform, k=1)
    if not hits:
        hits = search(query, category=category, k=1)
    if hits and platform and hits[0]["platform"] == platform:
        g = hits[0]
        return {"title": f"{g['platform']}: {g['title']}", "steps": list(g["steps"]),
                "url": g.get("url", ""), "category": g["category"], "guideId": g["id"],
                "platform": g["platform"], "source": "guide"}
    title, steps = GENERIC.get(category, GENERIC[DEFAULT_CATEGORY])
    return {"title": title, "steps": list(steps), "url": "", "category": category,
            "guideId": "", "platform": "", "source": "generic"}
