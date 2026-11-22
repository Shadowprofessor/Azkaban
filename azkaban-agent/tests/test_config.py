"""Settings precedence: the project's .env key must beat a stale environment variable."""
from __future__ import annotations

from azkaban_agent import config, nim


def load(tmp_path, monkeypatch, env_text: str, **environ):
    (tmp_path / ".env").write_text(env_text, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    for k in ("NVIDIA_API_KEY", "AZK_WS_PORT"):
        monkeypatch.delenv(k, raising=False)
    for k, v in environ.items():
        monkeypatch.setenv(k, v)
    config.SOURCES.clear()
    return config.Config.from_env()


def test_dotenv_key_overrides_a_stale_environment_key(tmp_path, monkeypatch):
    # The Windows failure: an old key in the user environment shadowed the new .env key.
    c = load(tmp_path, monkeypatch, "NVIDIA_API_KEY=nvapi-3m-new\n", NVIDIA_API_KEY="nvapi-_1-old")
    assert c.nim_key == "nvapi-3m-new"
    assert "overrides" in config.SOURCES["NVIDIA_API_KEY"]


def test_environment_still_wins_for_ordinary_settings(tmp_path, monkeypatch):
    c = load(tmp_path, monkeypatch, "AZK_WS_PORT=8787\n", AZK_WS_PORT="9100")
    assert c.ws_port == 9100


def test_quoted_values_and_a_bom_are_handled(tmp_path, monkeypatch):
    # Notepad saves UTF-8 with a BOM; people paste keys in quotes.
    c = load(tmp_path, monkeypatch, '﻿NVIDIA_API_KEY="nvapi-quoted"\n')
    assert c.nim_key == "nvapi-quoted"


def test_embedders_and_classifiers_are_not_chat_candidates():
    for m in ("nvidia/nemotron-3-embed-1b", "nvidia/nemotron-3.5-content-safety",
              "nvidia/llama-3.1-nemotron-safety-guard-8b-v3", "nvidia/nemotron-3.5-embed-8b"):
        assert not nim.is_chat_model(m), m
    for m in ("nvidia/nemotron-3-ultra-550b-a55b", "meta/llama-3.3-70b-instruct"):
        assert nim.is_chat_model(m), m


def test_base_url_is_expanded_to_the_chat_endpoint(tmp_path, monkeypatch):
    # NVIDIA's examples show base_url=".../v1"; the client POSTs to nim_url directly.
    for given in ("https://integrate.api.nvidia.com/v1", "https://integrate.api.nvidia.com/v1/",
                  "https://integrate.api.nvidia.com/v1/chat/completions"):
        monkeypatch.setenv("AZK_NIM_URL", given)
        c = load(tmp_path, monkeypatch, "")
        assert c.nim_url == "https://integrate.api.nvidia.com/v1/chat/completions", given
