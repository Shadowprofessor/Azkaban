"""DPDP Act 2023 verdicts grounded by retrieved statute text.

Privacy rules enforced here:
  * Only STRUCTURED FACTS go to retrieval and to the LLM (pii types, company,
    jurisdiction, consent, app category). Never raw or redacted PII values.
  * The LLM must use only the provided law and cite a section for every claim.
    Citations not in the retrieved set are dropped; any uncited "Section N"
    mentioned in the reasoning is flagged.
Degradation: LLM down -> no verdict (caller keeps flows + severity).
             RAG down -> verdict with status 'questionable' and "law unavailable".
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .config import REPO_ROOT, Config
from .features import UNEXPECTED, app_category
from .net import http_get, http_post
from .nim import NimClient, clean
from .schema import Citation, Verdict

SYSTEM = (
    "You are a legal analyst applying India's Digital Personal Data Protection Act, 2023 (DPDP) to one "
    "observed network flow from the user's own device. RULES: (1) Use ONLY the law excerpts provided in "
    "LAW. Do not rely on outside knowledge of any law. (2) Every legal claim must cite a section label "
    "exactly as given in LAW (e.g. \"Section 6\"). (3) Never cite or mention a section that is not in LAW. "
    "(4) If the provided law does not cover a question, say explicitly: \"The provided law does not cover "
    "this.\" (5) For each claim, quote the operative words from LAW in double quotes, and do not infer "
    "duties or prohibitions the quoted words do not state. (6) The facts are observations from traffic, not proof of the company's internal practices; "
    "say 'questionable' when the outcome depends on facts not observed (e.g. whether a valid notice was shown). "
    "Respond with JSON only: {\"status\": \"compliant\"|\"questionable\"|\"violation\", "
    "\"reasoning\": \"<=150 words, plain English, with short quotes\", \"citations\": [\"Section N\", ...]}"
)


# Faithful restatements of the verbatim text, to stop known small-model misreadings.
READING_NOTES = {
    "Section 16": "Section 16(1) lets the Central Government restrict transfers to countries it NOTIFIES. "
                  "A transfer abroad is not, by itself, unlawful; it is restricted only if that country has "
                  "been notified. This tool has no list of notified countries, so do not call a transfer "
                  "unlawful under Section 16.",
    "Section 6": "Section 6(1) requires consent to be limited to personal data \"necessary for such specified "
                 "purpose\". Whether consent was obtained in the app UI is NOT visible in network traffic: "
                 "'no consent signal observed' is not proof that consent was absent.",
}


class LawUnavailable(Exception):
    pass


def _load_retrieve():
    """Teammate's retriever if present (rag/query.py at repo root), else the bundled stub."""
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from rag.query import retrieve  # type: ignore  # owned by the RAG teammate
        return retrieve, "rag"
    except Exception:
        from .rag_stub import retrieve
        return retrieve, "stub"


def build_facts(e, home_country: str) -> dict:
    f = e.flow
    types = sorted({h.type for h in f.pii})
    return {
        "pii_types": types,
        "company": f.company or f.host,
        "tracker_category": f.tracker.category if f.tracker else None,
        "is_tracker": f.tracker is not None,
        "jurisdiction": f.country,
        "cross_border": f.country not in ("ZZ", "", home_country),
        "consent": bool(f.tcf and f.tcf.purposes),
        "consent_signal": "TCF string present" if f.tcf else "none observed",
        "app": f.app,
        "app_category": app_category(f.app),
        "pii_unexpected_for_app_category": sorted(set(types) & UNEXPECTED.get(app_category(f.app), set())),
        "hashed_identifier": e.hashed_hits > 0,
        "same_adid_across_apps": e.adid_reuse,
        "while_user_idle": e.tsi >= 60,
        "decrypted": f.decrypted,
    }


def facts_key(facts: dict) -> str:
    k = {x: facts[x] for x in facts if x not in ("app",)}
    return json.dumps(k, sort_keys=True)


class LegalEngine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.retrieve, self.rag_source = _load_retrieve()
        self.cache: dict[str, dict] = {}
        self.nim = NimClient(cfg)
        self.engine = "none"        # which engine answered last: nim | ollama | none

    # ------------------------------------------------------------- health
    def llm_available(self) -> bool:
        if self.nim.configured and self.nim.available():
            return True
        if self.cfg.nim_enabled and not self.cfg.nim_fallback_ollama:
            return False
        try:
            r = http_get(f"{self.cfg.ollama_url}/api/tags", cfg=self.cfg, timeout=1.5)
            names = [m.get("name", "") for m in r.json().get("models", [])]
            return r.ok and any(n.startswith(self.cfg.ollama_model.split(":")[0]) for n in names)
        except Exception:
            return False

    # ------------------------------------------------------------- retrieval
    def _law(self, facts: dict) -> list[dict]:
        try:
            try:
                docs = self.retrieve(facts, k=4)
            except TypeError:
                docs = self.retrieve(facts)
        except Exception as ex:
            raise LawUnavailable(str(ex)) from ex
        docs = [d for d in (docs or []) if d.get("section") and d.get("text")]
        if not docs:
            raise LawUnavailable("retriever returned no law")
        return docs

    # ------------------------------------------------------------- llm
    def _ollama(self, messages: list[dict]) -> str:
        r = http_post(f"{self.cfg.ollama_url}/api/chat", cfg=self.cfg, timeout=120, json={
            "model": self.cfg.ollama_model, "messages": messages, "stream": False, "format": "json",
            "options": {"temperature": 0, "num_ctx": 8192},
        })
        r.raise_for_status()
        return r.json()["message"]["content"]

    def _nim(self, messages: list[dict]) -> str:
        return self.nim.chat(messages, max_tokens=700, temperature=0.0, json_object=True)

    def _complete(self, messages: list[dict]) -> str:
        """Nemotron first, local Ollama as the offline fallback.

        A NIM failure is not fatal when Ollama is up: the verdict is the product, not the
        vendor. `self.engine` records which one answered so status can show it.
        """
        if self.nim.configured:
            try:
                out = self._nim(messages)
                if out.strip():
                    self.engine = "nim"
                    return out
            except Exception as ex:
                if not self.cfg.nim_fallback_ollama:
                    raise
                print(f"[azkaban] NIM unavailable ({type(ex).__name__}: {ex}); trying local Ollama",
                      file=sys.stderr, flush=True)
        out = self._ollama(messages)
        self.engine = "ollama"
        return out

    # ------------------------------------------------------------- verdict
    def verdict(self, flow_id: str, facts: dict) -> Verdict | None:
        key = facts_key(facts)
        if key in self.cache:
            return self._to_verdict(flow_id, self.cache[key])
        try:
            law = self._law(facts)
        except LawUnavailable as ex:
            return Verdict(flowId=flow_id, status="questionable",
                           reasoning=f"Law unavailable: the legal index could not be reached ({ex}). "
                                     "No legal assessment was made.", citations=[])
        law_block = "\n\n".join(f"[{d['section']}] ({d.get('source', 'DPDP Act 2023')})\n{d['text'][:2500]}" for d in law)
        notes = "\n".join(f"- {n}" for sec, n in READING_NOTES.items() if any(d["section"] == sec for d in law))
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"LAW:\n{law_block}\n\nREADING NOTES (restating the text above):\n{notes}\n\n"
                                        f"FACTS (observed, structured):\n{json.dumps(facts, indent=1)}\n\n"
                                        "Assess this flow. Use 'violation' only when the quoted law plus the "
                                        "observed facts establish it without assumptions."},
        ]
        try:
            content = self._complete(messages)
        except Exception:
            self.engine = "none"
            return None   # LLM down: caller still has flows + severity
        result = self._validate(content, law)
        self.cache[key] = result
        return self._to_verdict(flow_id, result)

    @staticmethod
    def _validate(content: str, law: list[dict]) -> dict:
        by_section = {d["section"].lower(): d for d in law}
        try:
            data = json.loads(content)
        except ValueError:
            m = re.search(r"\{.*\}", content, re.S)
            data = json.loads(m.group(0)) if m else {}
        status = str(data.get("status", "")).lower()
        if status not in ("compliant", "questionable", "violation"):
            status = "questionable"
        reasoning = clean(str(data.get("reasoning", ""))) or "The model returned no reasoning."
        cites = []
        for c in data.get("citations", []) or []:
            d = by_section.get(str(c).strip().lower())
            if d and d not in cites:
                cites.append(d)
        # Any section named in the reasoning must be one we provided.
        # "Section 6(1)(a)" is fine if Section 6 was provided; "Section 2(t)" is its own entry.
        mentioned = set()
        for full, base in re.findall(r"[Ss]ection\s+((\d+)(?:\(\w+\))*)", reasoning):
            full_k, base_k = f"section {full}".lower(), f"section {base}".lower()
            mentioned.add(full_k if full_k in by_section else base_k)
        invented = sorted(m for m in mentioned if m not in by_section)
        if invented:
            reasoning += f" [Note: reference(s) to {', '.join(invented)} removed from citations — not in the retrieved law.]"
        for m in mentioned:
            if m in by_section and by_section[m] not in cites:
                cites.append(by_section[m])
        hedged = re.search(r"\bquestionable\b|cannot be (confirmed|determined)|unclear|may be|potentially", reasoning, re.I)
        if status == "violation" and hedged:
            status = "questionable"
        if not cites:
            status = "questionable"
            reasoning += " [No citation to the provided law — treat as unverified.]"
        return {"status": status, "reasoning": reasoning,
                "citations": [{"source": d.get("source", "DPDP Act 2023"), "section": d["section"],
                               "url": d.get("url", "")} for d in cites]}

    @staticmethod
    def _to_verdict(flow_id: str, r: dict) -> Verdict:
        return Verdict(flowId=flow_id, status=r["status"], reasoning=r["reasoning"],
                       citations=[Citation(**c) for c in r["citations"]])
