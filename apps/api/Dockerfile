# syntax=docker/dockerfile:1

# ---- builder: resolve dependencies from the committed lockfile ----
FROM python:3.15-slim AS builder

# Pin uv to the version that produced uv.lock for reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Cache-friendly layer: install third-party dependencies only. This repo has
# no package build config, so the project itself is never installed here —
# source is copied into the runtime image instead.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# ---- runtime: minimal image, non-root ----
FROM python:3.15-slim AS runtime

# OCR engine for scanned PDF pages; language packs are configurable at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app && useradd --system --gid app --create-home app

WORKDIR /app/apps/api

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app apps/api /app/apps/api

USER app

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
