FROM python:3.13-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN pip install --no-cache-dir uv==0.5.14

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY fireflyframework_agentic ./fireflyframework_agentic
COPY examples ./examples

RUN uv sync --frozen --no-dev \
    --extra rest --extra mcp \
    --extra rag --extra openai-embeddings --extra azure --extra markitdown \
    --extra vectorstores-sqlite-vec

FROM python:3.13-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    PYTHONPATH=/app

RUN groupadd --system firefly && useradd --system --gid firefly --home /app firefly

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/fireflyframework_agentic /app/fireflyframework_agentic
COPY --from=builder /app/examples /app/examples

WORKDIR /app
USER firefly

EXPOSE 8000

CMD ["firefly-mcp-http"]
