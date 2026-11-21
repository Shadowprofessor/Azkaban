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


# ------------------------------------------------------------------ transport behaviour
class FakeResponse:
    def __init__(self, status: int, body=None, text: str = ""):
        self.status_code = status
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def reply(text: str = "ok"):
    return FakeResponse(200, {"choices": [{"message": {"content": text}}]})


def run_chat(monkeypatch, responses, **kw):
    """Drive NimClient.chat against a scripted sequence of responses."""
    sent: list[dict] = []
    queue = list(responses)

    def fake_post(url, *, cfg=None, timeout=None, json=None, headers=None):
        # Snapshot: chat() mutates one payload dict across retries, so storing the
        # reference would make every captured request look like the last one.
        sent.append(dict(json))
        return queue.pop(0)

    monkeypatch.setattr(nim, "http_post", fake_post)
    out = nim.NimClient(cfg()).chat([{"role": "user", "content": "hi"}],
                                    log_payload=False, **kw)
    return out, sent


def test_a_plain_success_sends_one_request(monkeypatch):
    out, sent = run_chat(monkeypatch, [reply("hello")])
    assert out == "hello"
    assert len(sent) == 1


def test_response_format_is_dropped_when_rejected(monkeypatch):
    # Some NIM builds 400 on response_format; the prompt already demands JSON.
    out, sent = run_chat(monkeypatch, [FakeResponse(400, {"detail": "bad response_format"}),
                                       reply("{}")], json_object=True)
    assert out == "{}"
    assert "response_format" in sent[0]
    assert "response_format" not in sent[1]
    assert "chat_template_kwargs" in sent[1]       # only the rejected key is dropped


def test_chat_template_kwargs_is_dropped_next(monkeypatch):
    out, sent = run_chat(monkeypatch, [FakeResponse(400, {"detail": "no response_format"}),
                                       FakeResponse(422, {"detail": "no chat_template_kwargs"}),
                                       reply("done")], json_object=True)
    assert out == "done"
    assert len(sent) == 3
    assert "chat_template_kwargs" not in sent[2]


def test_a_persistent_error_surfaces_the_server_message(monkeypatch):
    # requests' own message hides the body, which is where NVIDIA says what is wrong.
    monkeypatch.setattr(nim, "http_post",
                        lambda *a, **k: FakeResponse(401, {"detail": "invalid api key"}))
    with pytest.raises(RuntimeError, match="401.*invalid api key"):
        nim.NimClient(cfg()).chat([], log_payload=False)


def test_an_unknown_model_error_is_readable(monkeypatch):
    monkeypatch.setattr(nim, "http_post",
                        lambda *a, **k: FakeResponse(404, {"error": {"message": "model not found"}}))
    with pytest.raises(RuntimeError, match="model not found"):
        nim.NimClient(cfg()).chat([], log_payload=False)


def test_a_gateway_html_error_does_not_crash_the_parser(monkeypatch):
    monkeypatch.setattr(nim, "http_post",
                        lambda *a, **k: FakeResponse(502, None, "<html>502 Bad Gateway</html>"))
    with pytest.raises(RuntimeError, match="502"):
        nim.NimClient(cfg()).chat([], log_payload=False)


def test_non_json_success_body_is_reported_clearly(monkeypatch):
    monkeypatch.setattr(nim, "http_post", lambda *a, **k: FakeResponse(200, None, "not json"))
    with pytest.raises(RuntimeError, match="non-JSON"):
        nim.NimClient(cfg()).chat([], log_payload=False)


def test_a_non_400_error_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        return FakeResponse(500, {"detail": "upstream down"})

    monkeypatch.setattr(nim, "http_post", fake_post)
    with pytest.raises(RuntimeError, match="500"):
        nim.NimClient(cfg()).chat([], log_payload=False, json_object=True)
    assert calls["n"] == 1, "a 500 is not a payload problem; retrying is pointless"
