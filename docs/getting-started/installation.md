---
title: Installation
description: Install Firefly Agentic with the interactive installer, uv, or pip — and pick only the extras your deployment needs.
---

# Installation

## Requirements

- **Python 3.13** or later
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- For hosted models, the selected provider’s credentials — `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  `GEMINI_API_KEY`, `GROQ_API_KEY`, or any
  [Pydantic AI-supported provider](https://ai.pydantic.dev/models/).

The runtime requires **Pydantic AI `>=2.51.0,<3`**. Firefly declares its agent
provider integrations explicitly; optional extras below add storage, embeddings,
and document processing. Existing installations should review the
[migration guide](../migration.md) before upgrading.

Local and test models may not need credentials.

## Install a release

Use a Python 3.13+ virtual environment and install the wheel from
[v26.09.0](https://github.com/fireflyframework/fireflyframework-agentic/releases/tag/v26.09.0):

```bash
python -m pip install "https://github.com/fireflyframework/fireflyframework-agentic/releases/download/v26.09.0/fireflyframework_agentic-26.9.0-py3-none-any.whl"
```

Include an extra using a direct-reference requirement:

```bash
python -m pip install "fireflyframework-agentic[postgres] @ https://github.com/fireflyframework/fireflyframework-agentic/releases/download/v26.09.0/fireflyframework_agentic-26.9.0-py3-none-any.whl"
```

Releases use **YY.MM.Patch**, starting with patch `0` each month. Python normalizes
`26.09.0` to `26.9.0` in package filenames. The release workflow publishes GitHub
assets; it does not publish to PyPI. Pin the framework and lock application
dependencies for reproducible deployments.

## One-line installer

The interactive installer detects your platform, checks Python and uv, lets you
choose extras, and verifies the result. It installs the current `main` branch;
use the release wheel above to pin a published version.

=== "macOS / Linux"

    ```bash
    curl -fsSL https://raw.githubusercontent.com/fireflyframework/fireflyframework-agentic/main/install.sh | bash
    ```

=== "Windows (PowerShell)"

    ```powershell
    irm https://raw.githubusercontent.com/fireflyframework/fireflyframework-agentic/main/install.ps1 | iex
    ```

## From source

```bash
git clone https://github.com/fireflyframework/fireflyframework-agentic.git
cd fireflyframework-agentic
uv sync --extra all                       # or: pip install -e ".[all]"
```

## Optional extras

Heavy libraries are pip extras, imported lazily so you install only what you
deploy.

| Extra | What it adds | When you need it |
|---|---|---|
| `security` | cryptography | At-rest encryption (`EncryptedMemoryStore`, `AESEncryptionProvider`) |
| `script-execution` | pydantic-monty | The deny-by-default Monty sandbox for secure script execution |
| `embeddings` | numpy | Fast in-memory vector math |
| `openai-embeddings` | openai | OpenAI / Azure text embeddings |
| `azure-embeddings` · `cohere-embeddings` · `google-embeddings` · `mistral-embeddings` · `voyage-embeddings` · `bedrock-embeddings` · `ollama-embeddings` | provider SDKs | The matching embedding provider |
| `vectorstores-chroma` · `vectorstores-pinecone` · `vectorstores-qdrant` · `vectorstores-pgvector` · `vectorstores-sqlite-vec` | backend clients | The matching vector-store backend |
| `postgres` · `mongodb` | asyncpg/SQLAlchemy · motor/pymongo | Persistent working memory / storage |
| `binary` | pypdf, Pillow, pillow-heif, cairosvg, py7zr, extract-msg | `content.binary` file normalisation |
| `watch` | watchfiles | File-watching for content sources |
| `reasoning-eval` | numpy, pandas | Reasoning quality comparisons |
| `evaluation` | Ragas, LangChain adapters | LLM-as-judge evaluation; read the [compatibility constraints](../migration.md#optional-evaluation-dependencies) |
| `dev` | pytest, Ruff, Pyright, pre-commit, Testcontainers | Framework development |
| `all` | Runtime integrations above | Excludes `reasoning-eval`, `evaluation`, and `dev`; `uv sync --all-extras` includes these too |

## Verify

```bash
python -c "import fireflyframework_agentic; print(fireflyframework_agentic.__version__)"
```

## Uninstall

=== "macOS / Linux"

    ```bash
    curl -fsSL https://raw.githubusercontent.com/fireflyframework/fireflyframework-agentic/main/uninstall.sh | bash
    ```

=== "Windows (PowerShell)"

    ```powershell
    irm https://raw.githubusercontent.com/fireflyframework/fireflyframework-agentic/main/uninstall.ps1 | iex
    ```

---

Next: the **[5-Minute Quick Start](quickstart.md)** →
