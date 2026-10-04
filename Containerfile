# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
FROM python:3.12-slim

# tesseract: docling's OCR backend for pages without a text layer.
# poppler-utils: pdftoppm/pdfinfo, for inspecting extraction by hand.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-pol \
        tesseract-ocr-eng \
        poppler-utils \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    GRADIO_SERVER_NAME=0.0.0.0 \
    GRADIO_ANALYTICS_ENABLED=False \
    HF_HOME=/opt/models \
    DOCLING_ARTIFACTS_PATH=/opt/models/docling

WORKDIR /src
COPY pyproject.toml ./

# The dependencies and the model weights are installed before the source is
# copied, so editing app/ costs one small layer instead of re-downloading
# 1.4 GB of weights. The stub package exists only so that the project's
# dependencies can be resolved from pyproject before app/ is there.
#
# torch comes from the CPU index: docling is pinned to the CPU (the GPU
# belongs to Ollama), so the CUDA wheels would be gigabytes of dead weight.
#
# The dev extra is installed so the image can run its own test suite:
#   podman run --rm --network none -v .:/src:ro -w /src glosator:latest pytest
RUN mkdir -p app && touch app/__init__.py \
    && uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python \
        --index-url https://download.pytorch.org/whl/cpu torch torchvision \
    && uv pip install --python /opt/venv/bin/python ".[dev]"

# Bake docling's layout and table models into the image. The container has no
# network at run time, so a model that is not here is a model we cannot use.
#
# The target directory is explicit: the default is $HOME/.cache/docling, and
# with --userns=keep-id $HOME is not the one that existed at build time, which
# leaves 1.4 GB of weights behind a permission error. a+rX for the same reason.
RUN python -c "\
from pathlib import Path; \
from docling.utils.model_downloader import download_models; \
download_models(output_dir=Path('/opt/models/docling'), progress=False)" \
    && chmod -R a+rX /opt/models

# From here on nothing may reach out: a missing model must fail loudly rather
# than quietly download itself on the first page of the first run.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

COPY app ./app
RUN uv pip install --python /opt/venv/bin/python --no-deps .

EXPOSE 7860
CMD ["python", "-m", "app.ui"]
