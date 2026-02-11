# Contributing to fireflyframework-genai

Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.

Thank you for considering a contribution. This document explains how to set up
your development environment, the coding standards we follow, and the process
for submitting changes.

---

## Development Environment

### Prerequisites

- Python 3.13 or later
- [UV](https://docs.astral.sh/uv/) for dependency and virtual-environment management
- Git

### Setup

```bash
git clone https://github.com/fireflyframework/fireflyframework-genai.git
cd fireflyframework-genai
uv sync --all-extras
```

This installs all runtime and development dependencies, including optional extras
for REST, Kafka, RabbitMQ, and Redis.

### Running Tests

```bash
uv run pytest
```

To generate a coverage report:

```bash
uv run pytest --cov=fireflyframework_genai --cov-report=term-missing
```

### Linting

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

### Type Checking

We use [Pyright](https://github.com/microsoft/pyright) in standard mode:

```bash
uv run pyright src/
```

---

## Coding Standards

### Style

- Follow PEP 8. Ruff enforces this automatically.
- Maximum line length is 120 characters.
- Use `from __future__ import annotations` at the top of every module.
- All public functions, classes, and methods must have docstrings.
- Prefer explicit type annotations over implicit types.

### Copyright Header

Every Python source file must begin with the Apache 2.0 copyright header:

```python
# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
```

### Imports

Imports are organised into three groups, separated by blank lines:

1. Standard library
2. Third-party packages
3. Internal (`fireflyframework_genai`) modules

Ruff isort rules enforce this automatically.

### Testing

- Every new module must have a corresponding test file in `tests/`.
- Use `pytest` with `pytest-asyncio` for asynchronous tests.
- Aim for clear, descriptive test names that explain the behaviour under test.
- Mock external services rather than making real network calls.

---

## Submitting Changes

### Branch Naming

Use descriptive branch names:

- `feature/agent-retry-logic`
- `fix/prompt-template-escaping`
- `docs/reasoning-patterns-guide`

### Commit Messages

Write clear commit messages in the imperative mood:

```
Add retry logic to agent lifecycle manager

Introduces configurable retry with exponential backoff when an agent
invocation fails due to a transient provider error.
```

### Pull Request Process

1. Create a feature branch from `main`.
2. Make your changes, ensuring all tests pass and lint is clean.
3. Open a pull request against `main`.
4. Fill in the PR template, describing what changed and why.
5. Address any review feedback.
6. Once approved, the maintainers will merge your PR.

### Review Checklist

Before opening a PR, confirm that:

- All new code has the copyright header.
- All public APIs have docstrings.
- Tests cover the new or changed behaviour.
- `uv run ruff check src/ tests/` reports no issues.
- `uv run pyright src/` reports no errors.
- `uv run pytest` passes.

---

## Reporting Issues

Open an issue on GitHub with:

- A clear title summarising the problem.
- Steps to reproduce the issue.
- Expected and actual behaviour.
- Your Python version and operating system.

## Code of Conduct

We are committed to providing a welcoming and inclusive experience for everyone.
Be respectful, constructive, and professional in all interactions.
