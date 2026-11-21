"""Optional Nemotron reranking of retrieved documents.

BM25 decides which documents are candidates; the model only decides their order. That
split is the point: the model can never introduce a document that retrieval did not
return, so a citation can always be traced back to the corpus.

Grounding is enforced, not requested (ported from the `yash` branch's model.py):
  * the reply must be a JSON object with an `ids` array;
  * every id must be one of the candidates;
  * no duplicates.
Any breach raises RerankFailed and the caller keeps the BM25 order. A model that cites
something it was not given is a model whose output is discarded, not patched.

What leaves the machine: the structured facts the legal engine already sends, plus the
section labels, titles and summaries of PUBLIC statute text. Never a PII value.
"""
from __future__ import annotations

import json

SYSTEM = (
    "Rank the supplied law sections by how directly each one governs the described data flow. "
    "Return ONLY a JSON object of the form {\"ids\": [\"Section 6\", ...]} listing section "
    "labels in rank order, most relevant first. Use only the labels given. Omit sections that "
    "do not bear on the flow. Return an empty ids array if none of them do. No prose."
)
MAX_SUMMARY = 400


class RerankFailed(RuntimeError):
    pass


def _candidates(docs: list[dict]) -> list[dict]:
    return [{"id": d["section"], "title": d.get("title", ""),
             "summary": d.get("text", "")[:MAX_SUMMARY]} for d in docs]


def _parse(raw: str, allowed: set[str]) -> list[str]:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        ids = json.loads(raw)["ids"]
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        raise RerankFailed("model did not return an ids array") from None
    if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids):
        raise RerankFailed("ids is not a list of strings")
    if any(i not in allowed for i in ids):
        raise RerankFailed("model cited a section outside the retrieved context")
    if len(ids) != len(set(ids)):
        raise RerankFailed("model returned duplicate section ids")
    return ids


def rerank_law(facts: dict, docs: list[dict], client, *, keep: set[str] | None = None) -> list[dict]:
    """Reorder `docs` with the model. Falls back to the given order on any failure.

    `keep` names sections that must stay in the result whatever the model says — the
    trigger sections, which are required by the facts rather than by relevance.
    """
    if len(docs) < 2 or client is None or not getattr(client, "configured", False):
        return docs
    by_id = {d["section"]: d for d in docs}
    try:
        raw = client.chat(
            [{"role": "system", "content": SYSTEM},
             {"role": "user", "content": json.dumps({"flow_facts": facts,
                                                     "law_sections": _candidates(docs)})}],
            max_tokens=256, temperature=0.0, json_object=True, log_payload=False)
        order = _parse(raw, set(by_id))
    except Exception:
        return docs
    ranked = [by_id[i] for i in order]
    # Anything the model dropped goes after, trigger sections first: retrieval's job is to
    # be complete, the model's job is only to put the most relevant first.
    tail = [d for d in docs if d["section"] not in set(order)]
    required = [d for d in tail if keep and d["section"] in keep]
    rest = [d for d in tail if not (keep and d["section"] in keep)]
    return required + ranked + rest if required else ranked + rest
