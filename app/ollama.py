# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""The one place that calls Ollama.

Both model passes share these options, so a change to the context window or
the sampling temperature happens once, in ``config``.
"""

from __future__ import annotations

from pathlib import Path

import ollama

from app import config, log


class OllamaUnavailable(RuntimeError):
    """Ollama could not be reached or the model is not pulled."""


def client() -> ollama.Client:
    return ollama.Client(host=config.OLLAMA_URL, timeout=config.OLLAMA_TIMEOUT_S)


def list_models() -> list[str]:
    """Model tags from ``GET /api/tags``, for the UI dropdown."""
    try:
        response = client().list()
    except Exception as error:  # ollama wraps httpx and socket errors
        raise OllamaUnavailable(f"{config.OLLAMA_URL}: {error}") from error
    return sorted(
        model.get("model") or model.get("name", "") for model in response["models"]
    )


def unload(model: str) -> None:
    """Drop a model from VRAM now, instead of after ``keep_alive`` expires.

    The card is shared with whatever else the user runs locally, so glosator
    holds it only while a job is in flight. Failing to unload is not worth
    failing a finished job over; Ollama frees it on its own eventually.
    """
    try:
        client().generate(model=model, prompt="", keep_alive=0)
    except Exception as error:
        log.event("ollama", "could not unload model", model=model, error=repr(error))


def generate(model: str, prompt: str, images: list[Path] | None = None) -> str:
    """One completion. Blocks for as long as ``OLLAMA_TIMEOUT_S`` allows."""
    try:
        response = client().generate(
            model=model,
            prompt=prompt,
            images=[str(image) for image in images] if images else None,
            keep_alive=config.OLLAMA_KEEP_ALIVE,
            options={
                "num_ctx": config.NUM_CTX,
                "temperature": config.TEMPERATURE,
                "num_predict": config.NUM_PREDICT,
            },
        )
    except Exception as error:
        raise OllamaUnavailable(f"{model} on {config.OLLAMA_URL}: {error}") from error
    text = response["response"].strip()
    if not text:
        raise OllamaUnavailable(f"{model} returned an empty response")
    return text
