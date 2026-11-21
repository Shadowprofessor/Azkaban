"""Public benchmark integration. This module has no archive input."""

import json
import os
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .cases import BY_CASE
from .retrieval import retrieve


NVIDIA_URL = "https://integrate.api.nvidia.com/v1"
MODEL = "nvidia/nemotron-3-ultra-550b-a55b"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def post(url, payload, token, *, timeout=45):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout) as response:
            return json.loads(response.read(128 * 1024 + 1))
    except (URLError, TimeoutError, OSError, ValueError) as error:
        status = getattr(error, "code", None)
        message = f"Endpoint returned HTTP {status}." if status else "Endpoint unavailable or returned invalid JSON."
        raise RuntimeError(message) from None


def bridge_rank(server_url, case_id):
    if case_id not in BY_CASE:
        raise ValueError("Expected a built-in synthetic case ID.")
    allowed = {guide["id"] for guide in retrieve(BY_CASE[case_id])}
    response = post(f"{server_url.rstrip('/')}/v1/benchmark", {"case": case_id},
                    os.getenv("GHOSTPRINT_BRIDGE_TOKEN"), timeout=55)
    ids = response.get("ids") if isinstance(response, dict) else None
    if (not isinstance(ids, list) or any(not isinstance(id_, str) or id_ not in allowed for id_ in ids)
            or len(ids) != len(set(ids))):
        raise RuntimeError("Bridge returned invalid guide citations.")
    return ids


def rank(case_id, *, base=NVIDIA_URL, model=MODEL):
    question = BY_CASE[case_id]
    candidates = retrieve(question)
    if not candidates:
        return {"ids": [], "mode": "abstained"}
    hosted = base.rstrip("/") == NVIDIA_URL
    token = os.getenv("NVIDIA_API_KEY" if hosted else "GHOSTPRINT_MODEL_TOKEN")
    if hosted and not token:
        raise RuntimeError("Set NVIDIA_API_KEY on the model laptop.")
    context = [{key: guide[key] for key in ("id", "title", "summary", "steps")} for guide in candidates]
    allowed = {guide["id"] for guide in context}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Rank the supplied public privacy guides by relevance. "
             "Return only a JSON object with an ids array of guide IDs in rank order. "
             "Omit irrelevant guides. Return an empty ids array if none answer the question."},
            {"role": "user", "content": json.dumps({"question": question, "public_guides": context})},
        ],
        "max_tokens": 256,
        "temperature": 0.1,
        "stream": False,
    }
    if "nemotron" in model.lower():
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    result = post(f"{base.rstrip('/')}/chat/completions", payload, token)
    try:
        raw = result["choices"][0]["message"]["content"].strip()
        if raw.startswith("```") and raw.endswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        ids = json.loads(raw)["ids"]
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        raise RuntimeError("Model did not return a guide ID list.") from None
    if not isinstance(ids, list) or any(not isinstance(id_, str) or id_ not in allowed for id_ in ids):
        raise RuntimeError("Model cited a guide outside the retrieved context.")
    if len(ids) != len(set(ids)):
        raise RuntimeError("Model returned duplicate guide IDs.")
    return {"ids": ids, "mode": "model"}
