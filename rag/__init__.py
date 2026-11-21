"""Azkaban retrieval layer.

Two local corpora, one BM25 engine, optional model reranking:

    from rag.query import retrieve            # DPDP statute sections for a flow
    from rag.guides import remediate          # steps to fix a finding
    from rag.rerank import rerank_law         # optional Nemotron reordering

azkaban_agent/legal.py imports `rag.query.retrieve` automatically when this package is
importable from the repo root, and falls back to azkaban_agent/rag_stub.py otherwise.
Nothing here opens a socket; reranking is handed a client by the caller.
"""
from .query import retrieve

__all__ = ["retrieve"]
__version__ = "1.0.0"
