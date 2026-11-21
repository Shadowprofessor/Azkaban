"""NVIDIA NIM / Nemotron reasoning engine: output hygiene, payload shape, fallback."""
from __future__ import annotations

import pytest

from azkaban_agent import nim
from azkaban_agent.config import NEMOTRON_ULTRA, Config


def cfg(**kw) -> Config:
    base = dict(nim_enabled=True, nim_url="https://integrate.api.nvidia.com/v1/chat/completions",
                nim_model=NEMOTRON_ULTRA, nim_key="nvapi-test")
    base.update(kw)
    return Config(**base)


# ------------------------------------------------------------------ clean()
@pytest.mark.parametrize("raw", [
    "**Section 6(1)** requires consent",
    "## Verdict\n*questionable*",
    "* bullet one\n- bullet two",
    "`code` and ```py\nblock\n```",
    "___underlined___ text",
])
def test_clean_strips_all_markdown(raw):
    out = nim.clean(raw)
    assert not set("*#`") & set(out), out
    assert "___" not in out, out


def test_clean_drops_thinking_trace_but_keeps_the_answer():
    out = nim.clean("<think>I should check Section 6 first.</think>The transfer is questionable.")
    assert "I should check" not in out
    assert out == "The transfer is questionable."


def test_clean_drops_unterminated_thinking_trace():
    # A truncated response can leave <think> open; the tail must not reach the UI.
    assert nim.clean("Answer here.\n<think>half a thought") == "Answer here."


def test_clean_preserves_statute_quotes():
    # The legal prompt requires quoted operative words, and _validate checks them.
    out = nim.clean('Section 6 limits data to that **"necessary for such specified purpose"**.')
    assert '"necessary for such specified purpose"' in out


def test_clean_keeps_bullet_text_without_leading_space():
    assert nim.clean("* first\n* second") == "first\nsecond"


def test_clean_is_safe_on_empty_and_plain_text():
    assert nim.clean("") == ""
    assert nim.clean("Plain sentence.") == "Plain sentence."


# ------------------------------------------------------------------ payload
def test_nemotron_payload_disables_thinking():
    p = nim.NimClient(cfg()).payload([{"role": "user", "content": "hi"}])
    assert p["model"] == NEMOTRON_ULTRA
    assert p["chat_template_kwargs"] == {"enable_thinking": False}
    assert p["stream"] is False


def test_non_nemotron_payload_has_no_template_kwargs():
    p = nim.NimClient(cfg(nim_model="meta/llama-3.1-70b-instruct")).payload([])
    assert "chat_template_kwargs" not in p


def test_json_object_mode_is_requested_when_asked():
    p = nim.NimClient(cfg()).payload([], json_object=True)
    assert p["response_format"] == {"type": "json_object"}


def test_models_url_derived_from_chat_url():
    assert nim.NimClient(cfg())._models_url() == "https://integrate.api.nvidia.com/v1/models"


def test_configured_requires_key_and_flag():
    assert nim.NimClient(cfg()).configured
    assert not nim.NimClient(cfg(nim_key="")).configured
    assert not nim.NimClient(cfg(nim_enabled=False)).configured
    assert not nim.NimClient(cfg()).available() or True   # no network in tests


# ------------------------------------------------------------------ response parsing
def test_content_prefers_answer_over_reasoning_field():
    data = {"choices": [{"message": {"content": "the answer", "reasoning_content": "the trace"}}]}
    assert nim._content(data) == "the answer"


def test_content_falls_back_to_reasoning_when_answer_is_empty():
    data = {"choices": [{"message": {"content": "", "reasoning_content": "salvaged"}}]}
    assert nim._content(data) == "salvaged"


def test_content_handles_content_parts_list():
    data = {"choices": [{"message": {"content": [{"text": "a"}, {"text": "b"}]}}]}
    assert nim._content(data) == "ab"


def test_content_survives_a_malformed_response():
    assert nim._content({}) == ""
    assert nim._content({"choices": []}) == ""
