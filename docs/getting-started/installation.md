---
title: Installation
description: Install Firefly Agentic with the interactive installer, uv, or pip — and pick only the extras your deployment needs.
---

# Installation

## Requirements

- **Python 3.13** or later
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- At least one LLM provider key — `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  `GEMINI_API_KEY`, `GROQ_API_KEY`, or any
  [Pydantic AI-supported provider](https://ai.pydantic.dev/models/).

## One-line installer (recommended)

The interactive installer detects your platform, checks Python and uv, lets you
choose extras, and verifies the result.

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
uv sync --all-extras                       # or: pip install -e ".[all]"
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
| `cohere-embeddings` · `google-embeddings` · `mistral-embeddings` · `voyage-embeddings` · `bedrock-embeddings` · `ollama-embeddings` | provider SDKs | The matching embedding provider |
| `vectorstores-chroma` · `vectorstores-pinecone` · `vectorstores-qdrant` · `vectorstores-pgvector` · `vectorstores-sqlite-vec` | backend clients | The matching vector-store backend |
| `postgres` · `mongodb` | asyncpg/SQLAlchemy · motor/pymongo | Database-backed memory / storage |
| `binary` | pypdf, Pillow, pillow-heif, cairosvg, py7zr, extract-msg | `content.binary` file normalisation |
| `watch` | watchfiles | File-watching for content sources |
| `all` | Everything above | Full install with all integrations |

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
