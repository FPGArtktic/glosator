# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""The Ollama wrapper: options, model listing, failure mode."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import config, ollama


class FakeClient:
    def __init__(self, response: str = "text", models: list[str] | None = None) -> None:
        self.response = response
        self.models = models or []
        self.calls: list[dict] = []

    def list(self) -> dict:
        return {"models": [{"model": name} for name in self.models]}

    def generate(self, **kwargs: object) -> dict:
        self.calls.append(kwargs)
        return {"response": self.response}


class BrokenClient:
    def list(self) -> dict:
        raise ConnectionRefusedError("connection refused")

    def generate(self, **_kwargs: object) -> dict:
        raise ConnectionRefusedError("connection refused")


def test_list_models_is_sorted(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient(models=["qwen3-vl:8b", "gemma3:12b-it-qat"])
    monkeypatch.setattr(ollama, "client", lambda: fake)
    assert ollama.list_models() == ["gemma3:12b-it-qat", "qwen3-vl:8b"]


def test_generate_applies_the_configured_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeClient(response="  a note  ")
    monkeypatch.setattr(ollama, "client", lambda: fake)

    assert (
        ollama.generate("gemma3", "prompt", images=[Path("/tmp/fig.png")]) == "a note"
    )

    call = fake.calls[0]
    assert call["options"] == {
        "num_ctx": config.NUM_CTX,
        "temperature": config.TEMPERATURE,
        "num_predict": config.NUM_PREDICT,
    }
    assert call["keep_alive"] == config.OLLAMA_KEEP_ALIVE
    assert call["images"] == ["/tmp/fig.png"]


def test_generate_rejects_an_empty_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ollama, "client", lambda: FakeClient(response="   "))
    with pytest.raises(ollama.OllamaUnavailable, match="empty"):
        ollama.generate("gemma3", "prompt")


def test_unreachable_ollama_is_reported_with_its_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ollama, "client", BrokenClient)
    with pytest.raises(ollama.OllamaUnavailable, match=config.OLLAMA_URL):
        ollama.list_models()
    with pytest.raises(ollama.OllamaUnavailable, match="gemma3"):
        ollama.generate("gemma3", "prompt")


def test_unload_asks_ollama_to_drop_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient()
    monkeypatch.setattr(ollama, "client", lambda: fake)

    ollama.unload("gemma3:12b-it-qat")

    assert fake.calls[0]["keep_alive"] == 0
    assert fake.calls[0]["model"] == "gemma3:12b-it-qat"


def test_unload_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # A finished job must not be failed by a GPU that will free itself anyway.
    monkeypatch.setattr(ollama, "client", BrokenClient)
    ollama.unload("gemma3:12b-it-qat")
