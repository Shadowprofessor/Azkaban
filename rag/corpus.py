"""Corpus loading for the retrieval layer.

Two corpora, both local files, both lazily loaded and cached:

  law     — verbatim DPDP Act 2023 sections. Shipped with the agent package because the
            legal engine must be able to cite the statute with no network and no setup.
            Built by azkaban-agent/scripts/build_dpdp.py.
  guides  — public, platform-specific privacy how-to guides (ported from the `yash`
            branch), used to turn a finding into steps the user can actually follow.

Nothing here reads user traffic. Both corpora are public reference text.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

RAG_DIR = Path(__file__).resolve().parent
REPO_ROOT = RAG_DIR.parent
LAW_PATH = REPO_ROOT / "azkaban-agent" / "azkaban_agent" / "data" / "dpdp_sections.json"
GUIDES_PATH = RAG_DIR / "data" / "guides.json"

LAW_REQUIRED = ("section", "text")
GUIDE_REQUIRED = ("id", "platform", "category", "title", "steps")


def _load(path: Path, required: tuple[str, ...], label: str) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} corpus missing at {path}")
    docs = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(docs, list) or not docs:
        raise ValueError(f"{label} corpus at {path} is not a non-empty list")
    bad = [d for d in docs if not all(d.get(f) for f in required)]
    if bad:
        raise ValueError(f"{label} corpus has {len(bad)} record(s) missing {required}")
    return docs


@lru_cache(maxsize=1)
def law() -> list[dict]:
    return _load(LAW_PATH, LAW_REQUIRED, "law")


@lru_cache(maxsize=1)
def guides() -> list[dict]:
    return _load(GUIDES_PATH, GUIDE_REQUIRED, "guides")


def law_text(d: dict) -> str:
    """Indexable text for a statute section: title and tags carry as much signal as the body."""
    return " ".join([d.get("section", ""), d.get("title", ""), " ".join(d.get("tags", [])),
                     d.get("text", "")])


def guide_text(d: dict) -> str:
    return " ".join([d.get("platform", ""), d.get("title", ""), d.get("keywords", ""),
                     d.get("summary", ""), d.get("category", "")])
