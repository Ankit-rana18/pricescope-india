# Build context: repository root. One image serves the API and the Celery worker.
# Layout mirrors the repo (/app = backend, /integrations, /workers) because the backend
# installs the two packages from ../integrations and ../workers.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
WORKDIR /app

FROM base AS deps
COPY integrations/ /integrations/
COPY workers/ /workers/
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM base AS runtime
RUN useradd --system --uid 10001 --create-home pricescope
COPY --from=deps /app/.venv /app/.venv
COPY integrations/ /integrations/
COPY workers/ /workers/
COPY backend/ /app/
ENV PATH="/app/.venv/bin:$PATH"
USER pricescope
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health').status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
