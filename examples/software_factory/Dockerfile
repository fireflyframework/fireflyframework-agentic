# syntax=docker/dockerfile:1.7
FROM python:3.13-slim AS base

# System deps: gh CLI for codegen/qa, git for codegen workspace ops.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod 644 /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd -u 1001 -m runner
WORKDIR /home/runner

# Copy the framework source tree and the software_factory example.
COPY --chown=runner:runner pyproject.toml uv.lock README.md /home/runner/
COPY --chown=runner:runner src /home/runner/src
COPY --chown=runner:runner examples/software_factory /home/runner/software_factory

# Install the framework + factory runtime deps.
RUN pip install --no-cache-dir uv \
    && uv pip install --system --no-cache "." \
    && uv pip install --system --no-cache "sqlite-vec>=0.1.0" "pyyaml>=6.0"

# Make software_factory importable.
ENV PYTHONPATH=/home/runner

USER runner
ENTRYPOINT ["python", "-m", "software_factory.action_runtime"]
