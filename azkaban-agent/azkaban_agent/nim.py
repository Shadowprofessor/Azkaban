"""NVIDIA NIM client — Nemotron 3 Ultra 550B-A55B on the free prototyping endpoint.

This is the agent's reasoning engine. Everything it sends goes through net.py, so the
egress guard still decides whether the request may leave the machine at all: the NIM host
is reachable only when cfg.nim_enabled is set, and nothing else ever is.

What leaves the machine: aggregated, structured metadata and public statute/guide text.
Never a raw or redacted PII value, never a URL or body from the user's traffic. The caller
builds the payload; `log_payload` prints the exact JSON first so it is auditable.

Output discipline: Nemotron is a reasoning model and by default emits a thinking trace plus
Markdown. Both are switched off (`enable_thinking: false`) and anything that slips through
is stripped by `clean()`, because these verdicts are rendered as plain text in the
dashboard and the extension popup, where asterisks and fences are noise.
"""
from __future__ import annotations

import json
import re
import sys
import time

from .net import http_get, http_post

#: Model id on https://integrate.api.nvidia.com/v1 (free prototyping endpoint).
NEMOTRON_ULTRA = "nvidia/nemotron-3-ultra-550b-a55b"
BASE_URL = "https://integrate.api.nvidia.com/v1"

#: Preference order when the configured model is refused. A key can be valid (GET /models
#: works) yet not entitled to a particular model, which NVIDIA reports as HTTP 403
#: "Authorization failed". Strongest reasoning first. Ids the endpoint does not list are
#: skipped, and any other nemotron model it lists is tried after these.
FALLBACK_MODELS = (
    "nvidia/nemotron-3-ultra-550b-a55b",
    "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "nvidia/llama-3.3-nemotron-super-49b-v1",
    "nvidia/nvidia-nemotron-nano-9b-v2",
    "nvidia/llama-3.1-nemotron-70b-instruct",
)
PROBE_TTL_S = 60.0

_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\n?")
_BOLD_ITALIC = re.compile(r"(\*{1,3}|_{2,3})(?=\S)(.+?)(?<=\S)\1", re.S)
_STRAY_EMPHASIS = re.compile(r"[*_]{1,3}")
_BULLET = re.compile(r"^[ \t]*[*\-•–]+[ \t]+", re.M)
_HEADER = re.compile(r"^[ \t]*#{1,6}[ \t]*", re.M)
_NUMBERED = re.compile(r"^[ \t]*(\d+)[.)][ \t]+", re.M)
_THINK = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.S | re.I)
_OPEN_THINK = re.compile(r"<(think|thinking|reasoning)>.*", re.S | re.I)
_WS = re.compile(r"[ \t]{2,}")
_BLANKS = re.compile(r"\n{3,}")
_INDENT = re.compile(r"^[ \t]+", re.M)


def clean(text: str) -> str:
    """Markdown and thinking traces out, readable plain text in.

    Emphasis markers are removed rather than escaped: `**Section 6**` becomes `Section 6`.
    Quotation marks are preserved, because the legal prompt requires the model to quote the
    operative words of the statute and those quotes are checked downstream.
    """
    if not text:
        return ""
    t = _THINK.sub(" ", text)
    t = _OPEN_THINK.sub(" ", t)          # unterminated trace: drop the tail
    t = _FENCE.sub("", t).replace("`", "")
    t = _BOLD_ITALIC.sub(r"\2", t)
    # Bullets before stray emphasis, or "* item" leaves a leading space behind.
    t = _HEADER.sub("", t)
    t = _BULLET.sub("", t)
    t = _NUMBERED.sub(r"\1. ", t)
    t = _STRAY_EMPHASIS.sub("", t)
    t = _INDENT.sub("", t)
    t = _WS.sub(" ", t)
    t = _BLANKS.sub("\n\n", t)
    return t.strip()


def is_nemotron(model: str) -> bool:
    return "nemotron" in (model or "").lower()


def _content(data: dict) -> str:
    """Assistant text from an OpenAI-shaped response.

    Nemotron may put the trace in `reasoning_content` and the answer in `content`. Only the
    answer is wanted; if the answer is empty the trace is used as a last resort so a verdict
    is not silently lost.
    """
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    body = msg.get("content")
    if isinstance(body, list):                      # some gateways return content parts
        body = "".join(p.get("text", "") for p in body if isinstance(p, dict))
    text = (body or "").strip()
    return text or (msg.get("reasoning_content") or "").strip()


def _detail(response) -> str:
    """The server's own error text, trimmed. Falls back to the raw body."""
    try:
        data = response.json()
    except ValueError:
        return (response.text or "")[:300].strip() or "(empty body)"
    if isinstance(data, dict):
        for key in ("detail", "message", "error"):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()[:300]
            if isinstance(v, dict) and isinstance(v.get("message"), str):
                return v["message"].strip()[:300]
    return json.dumps(data)[:300]


#: Model ids that are not chat models: probing them wastes the budget and their 404/403 is
#: noise (the Windows run spent five of eight probes on embedders and safety classifiers).
NOT_CHAT = ("embed", "safety", "guard", "reward", "rerank", "retriever", "parse", "clip",
            "content-safety", "ocr", "asr", "tts", "vlm-embed", "pii")

#: Last resort when the key may call no Nemotron model at all: a strong general model, so
#: verdicts still come from NIM. Reported loudly; never chosen silently over Nemotron.
GENERAL_FALLBACKS = ("meta/llama-3.3-70b-instruct", "meta/llama-3.1-70b-instruct",
                     "mistralai/mixtral-8x22b-instruct-v0.1", "meta/llama-3.1-8b-instruct")


def is_chat_model(model_id: str) -> bool:
    m = (model_id or "").lower()
    return not any(t in m for t in NOT_CHAT)


class NimClient:
    """Chat-completions client for one configured model.

    `cfg` is the agent Config; `cfg.nim_url` is the full chat-completions URL so an operator
    can point this at a self-hosted NIM container without touching code.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self._probe: tuple[float, bool] = (0.0, False)
        self._fallback: str | None = None      # model that worked after a 403
        self._searched = False                 # search at most once per run

    # ------------------------------------------------------------------ config
    @property
    def configured_model(self) -> str:
        return self.cfg.nim_model or NEMOTRON_ULTRA

    @property
    def model(self) -> str:
        return self._fallback or self.configured_model

    @property
    def configured(self) -> bool:
        return bool(self.cfg.nim_enabled and self.cfg.nim_key and self.cfg.nim_url)

    def _models_url(self) -> str:
        base = self.cfg.nim_url.split("/chat/completions")[0].rstrip("/")
        return f"{base}/models"

    # ------------------------------------------------------------------ health
    def available(self, *, force: bool = False) -> bool:
        """Is the endpoint actually reachable and the key accepted?

        A key in .env is not the same as a working endpoint, so this asks. Cached for
        PROBE_TTL_S because the agent health loop runs every 15s.
        """
        if not self.configured:
            return False
        at, ok = self._probe
        now = time.monotonic()
        if not force and now - at < PROBE_TTL_S:
            return ok
        try:
            r = http_get(self._models_url(), cfg=self.cfg, timeout=6,
                         headers={"Authorization": f"Bearer {self.cfg.nim_key}"})
            ok = r.status_code == 200
        except Exception:
            ok = False
        self._probe = (now, ok)
        return ok

    def models(self) -> list[str]:
        """Model ids the endpoint advertises. Empty if it cannot be asked."""
        try:
            r = http_get(self._models_url(), cfg=self.cfg, timeout=10,
                         headers={"Authorization": f"Bearer {self.cfg.nim_key}"})
            if r.status_code != 200:
                return []
            data = r.json().get("data") or []
            return sorted(m.get("id", "") for m in data if isinstance(m, dict) and m.get("id"))
        except Exception:
            return []

    # ------------------------------------------------------------------ chat
    def payload(self, messages: list[dict], *, max_tokens: int = 600, temperature: float = 0.0,
                json_object: bool = False) -> dict:
        p: dict = {"model": self.model, "messages": messages, "temperature": temperature,
                   "max_tokens": max_tokens, "stream": False}
        if is_nemotron(self.model):
            # Plain answers, no chain-of-thought in the response body.
            p["chat_template_kwargs"] = {"enable_thinking": False}
        if json_object:
            p["response_format"] = {"type": "json_object"}
        return p

    #: Payload keys that some NIM builds reject. Dropped one at a time, in this order,
    #: before giving up: each is an optimisation, not a requirement.
    OPTIONAL_KEYS = ("response_format", "chat_template_kwargs")

    def _post(self, payload: dict, timeout: int):
        return http_post(self.cfg.nim_url, cfg=self.cfg, timeout=timeout, json=payload,
                         headers={"Authorization": f"Bearer {self.cfg.nim_key}"})

    def chat(self, messages: list[dict], *, max_tokens: int = 600, temperature: float = 0.0,
             json_object: bool = False, log_payload: bool = True, timeout: int = 120) -> str:
        """One completion, degrading gracefully when the endpoint rejects an extra.

        `response_format` and `chat_template_kwargs` are supported by the hosted endpoint
        but not by every self-hosted NIM build or gateway. Rather than fail outright, each
        is dropped in turn and the call retried: the prompt already demands JSON, and
        clean() strips a thinking trace, so both are optimisations we can live without.
        """
        p = self.payload(messages, max_tokens=max_tokens, temperature=temperature,
                         json_object=json_object)
        if log_payload:
            # Transparency: print EXACTLY what leaves the machine.
            print("[azkaban] NIM request (aggregated metadata + public text only):\n"
                  + json.dumps(p, indent=2), file=sys.stderr, flush=True)
        r = self._post(p, timeout)
        for key in self.OPTIONAL_KEYS:
            if r.status_code not in (400, 422) or key not in p:
                break
            print(f"[azkaban] endpoint rejected '{key}'; retrying without it", file=sys.stderr, flush=True)
            p.pop(key, None)
            r = self._post(p, timeout)
        if r.status_code == 403 and not self._searched:
            alt = self.find_working_model()
            if alt and alt != p.get("model"):
                print(f"[azkaban] key is not entitled to {p.get('model')}; using {alt} instead "
                      f"(set AZK_NIM_MODEL={alt} in .env to make this permanent)",
                      file=sys.stderr, flush=True)
                p["model"] = alt
                if not is_nemotron(alt):
                    p.pop("chat_template_kwargs", None)
                r = self._post(p, timeout)
        if r.status_code >= 400:
            # requests' own message hides the body, which is where NVIDIA says what is
            # actually wrong (bad key, unknown model, quota). Surface it.
            raise RuntimeError(f"NIM returned HTTP {r.status_code}: {_detail(r)}")
        try:
            return _content(r.json())
        except ValueError:
            raise RuntimeError(f"NIM returned non-JSON: {(r.text or '')[:300]}") from None

    # ------------------------------------------------------------------ entitlement
    def candidates(self, *, general: bool = True) -> list[str]:
        """Chat models worth trying: configured, preferred Nemotrons, other listed Nemotrons,
        then (only if `general`) strong non-Nemotron chat models as a last resort."""
        listed = self.models()
        order = [self.configured_model] + [m for m in FALLBACK_MODELS if m != self.configured_model]
        if listed:
            known = set(listed)
            order = [m for m in order if m in known]
            order += [m for m in listed if "nemotron" in m.lower() and m not in order]
            if general:
                order += [m for m in GENERAL_FALLBACKS if m in known]
        elif general:
            order += list(GENERAL_FALLBACKS)
        return [m for m in dict.fromkeys(order) if is_chat_model(m)]

    def try_model(self, model: str, timeout: int = 45) -> tuple[bool, str]:
        """One tiny completion against `model`. (ok, short reason)."""
        p = {"model": model, "messages": [{"role": "user", "content": "Reply with: OK"}],
             "max_tokens": 8, "temperature": 0.0, "stream": False}
        if is_nemotron(model):
            p["chat_template_kwargs"] = {"enable_thinking": False}
        try:
            r = self._post(p, timeout)
            if r.status_code in (400, 422) and "chat_template_kwargs" in p:
                p.pop("chat_template_kwargs")
                r = self._post(p, timeout)
        except Exception as ex:
            return False, f"{type(ex).__name__}"
        if r.status_code == 200:
            return True, "ok"
        return False, f"HTTP {r.status_code}: {_detail(r)[:80]}"

    def find_working_model(self, limit: int = 12) -> str | None:
        """First candidate this key can actually call. Cached for the rest of the run."""
        self._searched = True
        for model in self.candidates()[:limit]:
            ok, _ = self.try_model(model)
            if ok:
                if model != self.configured_model:
                    self._fallback = model
                return model
        return None

    def ask(self, system: str, user: str, **kw) -> str:
        """One-shot prompt returning sanitised plain text."""
        return clean(self.chat([{"role": "system", "content": system},
                                {"role": "user", "content": user}], **kw))
