# rag — Azkaban retrieval layer

Grounds the agent's output in text the user can check: statute sections for the legal
verdict, public how-to guides for the fix.

Merged from the `yash` branch (`ghostprint/retrieval.py`, `ghostprint/model.py`,
`ghostprint/guides.json`). The BM25 core and the guide corpus come from there; the
statute retrieval and the agent wiring are new.

## Layout

| File | What it does |
|---|---|
| `bm25.py` | Okapi BM25 (k1=1.2, b=0.75), pure stdlib. One engine for both corpora. |
| `corpus.py` | Loads and validates the two corpora. Lazy + cached. |
| `query.py` | `retrieve(facts, k)` → DPDP sections. The interface `legal.py` auto-detects. |
| `guides.py` | `remediate(...)` → steps to fix a finding, with a generic fallback. |
| `rerank.py` | Optional Nemotron reordering, with grounding enforced. |
| `data/guides.json` | 14 public platform guides (Google, Instagram/Meta, Spotify). |

## How the agent uses it

`azkaban_agent/legal.py` tries `rag.query.retrieve` at import and falls back to
`azkaban_agent/rag_stub.py` if this package is not importable. When it loads, the status
message reports `engines.rag: true`. `azkaban_agent/remediate.py` attaches
`data.remediation` to actionable insights, reported as `engines.remediation: true`.

## Why BM25 and not embeddings

Tens of documents of dense legal prose; must work offline with no model download; a
citation has to be auditable. BM25 is deterministic and explains itself through term
overlap. At this corpus size semantic recall buys little and costs the audit trail.

## Statute ranking is hybrid, on purpose

Some facts implicate a section as a matter of law, not of word overlap: any processing
engages Section 6, a transfer abroad engages Section 16, a tracker engages Section 8, a
children's app engages Section 9. Those are returned always, in a fixed order, and `k`
never drops them. Everything else is BM25 plus a tag boost.

Sections gated behind a fact are *demoted* when the fact is absent (`GATED` in
`query.py`). Handing the model Section 9 for an adult app invites a misapplied citation,
because `legal.py` instructs it to cite only the law it was given.

## The model may reorder, never add

`rerank.py` sends the structured facts plus section labels, titles and public summaries,
and takes back an ordering. Every returned id must be one of the candidates, with no
duplicates, or `RerankFailed` is raised and the BM25 order stands. Retrieval decides
*which* sections are in play; the model only decides what to read first.

## Privacy

Both corpora are public reference text. The only input is the structured facts the legal
engine already builds (PII *types*, company, jurisdiction, consent flags, app category) —
never a raw or redacted PII value, never a URL or body from the user's traffic. Nothing
here opens a socket; `rerank.py` is handed a client by the caller, and that client goes
through `azkaban_agent/net.py` like everything else.

## Checking it

    azkaban rag-check --tracker --cross-border --no-consent --pii gps,adid --company Google
    python -m pytest rag/tests -q
