"""Okapi BM25 over a small in-memory corpus. Pure stdlib, no network, no model files.

Ported from the retrieval core on the `yash` branch (ghostprint/retrieval.py) and
generalised so one implementation serves both corpora in this repo: the DPDP statute
sections the legal engine cites, and the remediation guides the insights link to.

Why BM25 and not embeddings: the corpora are tens of documents of dense legal or
procedural prose, the agent must work with no network and no model download, and a
citation has to be auditable. BM25 is deterministic and explains itself through term
overlap, which matters more here than semantic recall over a corpus this size.

k1 = 1.2, b = 0.75 (the defaults the ghostprint implementation used).
"""
from __future__ import annotations

import math
import re
from collections import Counter

K1 = 1.2
B = 0.75

#: Function words carry no signal at this corpus size. The first group is the
#: ghostprint stoplist; the second is statute boilerplate that otherwise dominates
#: every DPDP section and flattens the ranking.
STOP = frozenset(
    "a an the from in to on of for can i my what how do is it some want about and or as at by be "
    "with this that these those any such shall may must not no if then than there their them her "
    "his its which who whom been were was are also per".split()
)

_WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall((text or "").lower()) if t not in STOP]


class BM25Index:
    """Rank documents by BM25 against a bag-of-words query.

    `docs` is a list of dicts. `text_of` extracts the indexable string from one document;
    everything else about the document is left untouched so callers get their own records
    back, not a reduced copy.
    """

    def __init__(self, docs: list[dict], text_of):
        self.docs = list(docs)
        self.bags: list[Counter] = [Counter(tokens(text_of(d))) for d in self.docs]
        self.lengths = [sum(b.values()) for b in self.bags]
        n = len(self.bags) or 1
        self.avg_len = (sum(self.lengths) / n) or 1.0
        self.df = Counter(term for bag in self.bags for term in bag)
        self.n = len(self.bags)

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log1p((self.n - df + 0.5) / (df + 0.5))

    def score(self, query: set[str], i: int) -> float:
        bag, dl = self.bags[i], self.lengths[i]
        norm = K1 * (1 - B + B * dl / self.avg_len)
        return sum(
            self.idf(term) * bag[term] * (K1 + 1) / (bag[term] + norm)
            for term in query & bag.keys()
        )

    def search(self, query: str | set[str], *, k: int = 5, where=None,
               boost=None, tie_key=None) -> list[tuple[float, dict]]:
        """Top-k (score, doc), highest first.

        `where(doc)` filters before scoring. `boost(doc, query)` adds a domain-specific
        bonus to the BM25 score — used to lift documents a fact directly implicates.
        `tie_key(doc)` makes equal scores order deterministically, which keeps citations
        stable across runs.
        """
        q = query if isinstance(query, set) else set(tokens(query))
        ranked: list[tuple[float, dict]] = []
        for i, doc in enumerate(self.docs):
            if where is not None and not where(doc):
                continue
            s = self.score(q, i)
            if boost is not None:
                s += boost(doc, q)
            if s > 0:
                ranked.append((s, doc))
        key = (lambda item: (-item[0], tie_key(item[1]))) if tie_key else (lambda item: -item[0])
        ranked.sort(key=key)
        return ranked[:k]
