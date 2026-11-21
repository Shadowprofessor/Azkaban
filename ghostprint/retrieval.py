import json
import math
import re
from collections import Counter
from pathlib import Path


GUIDES = json.loads(Path(__file__).with_name("guides.json").read_text(encoding="utf-8"))
BY_ID = {guide["id"]: guide for guide in GUIDES}
STOP = set("a an the from in to on of for can i my what how do is it some want about".split())
TOPICS = {
    "location": "gps coordinates location whereabouts geographic travel route trip trips commute movements",
    "contacts": "vcard addressbook contacts phonebook directory synced upload imported",
    "connections": "followers following network relationships social graph circle audience",
    "interests": "ads advertisers profiling inferred interests personalization targeting topics tailored marketing segments",
    "activity": "activity searches watches listens tracks clicks history listening behavior habit",
    "security": "security sessions devices password login authentication sign-in unauthorized access ip",
    "messages": "messages inbox conversation chats dm texts private communication",
}


def tokens(text):
    return [term for term in re.findall(r"[a-z0-9]+", text.lower()) if term not in STOP]


DOCUMENTS = {
    guide["id"]: Counter(tokens(" ".join([
        guide["platform"], guide["title"], guide["keywords"], guide["summary"]
    ])))
    for guide in GUIDES
}
AVERAGE_LENGTH = sum(doc.total() for doc in DOCUMENTS.values()) / len(DOCUMENTS)
FREQUENCIES = Counter(term for doc in DOCUMENTS.values() for term in doc)
TOPIC_TERMS = {topic: set(tokens(terms)) for topic, terms in TOPICS.items()}
PLATFORMS = {guide["platform"].lower(): guide["platform"] for guide in GUIDES}


def bm25(query, document):
    normalization = 1.2 * (0.25 + 0.75 * document.total() / AVERAGE_LENGTH)
    return sum(
        math.log1p((len(DOCUMENTS) - FREQUENCIES[term] + 0.5) / (FREQUENCIES[term] + 0.5))
        * document[term] * 2.2 / (document[term] + normalization)
        for term in query & document.keys()
    )


def retrieve(query, *, platform=None, category=None, k=5, baseline=False):
    """Retrieve public guides. Audit callers pass only controlled metadata."""
    words = set(tokens(query))
    inferred_platforms = words & PLATFORMS.keys()
    if not baseline and platform is None and len(inferred_platforms) == 1:
        platform = PLATFORMS[next(iter(inferred_platforms))]
    if not baseline:
        words -= PLATFORMS.keys()
    topic_matches = {topic: len(words & terms) for topic, terms in TOPIC_TERMS.items()}
    ranked = []
    for guide in GUIDES:
        if platform and guide["platform"] != platform:
            continue
        if category and guide["category"] != category:
            continue
        score = bm25(words, DOCUMENTS[guide["id"]])
        if not baseline:
            score += 1.6 * topic_matches[guide["category"]]
        if score > 0 or category is not None:
            ranked.append((score, guide))
    ranked.sort(key=lambda item: (-item[0], item[1]["id"]))
    return [guide for _, guide in ranked[:k]]
