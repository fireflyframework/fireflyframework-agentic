FROM python:3.13-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN pip install --no-cache-dir uv==0.5.14

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev --extra rest --extra mcp

FROM python:3.13-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=8000

RUN groupadd --system firefly && useradd --system --gid firefly --home /app firefly

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src /app/src

WORKDIR /app
USER firefly

EXPOSE 8000

CMD ["firefly-mcp-http"]
