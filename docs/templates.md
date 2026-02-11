# Template Agents Guide

Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.

The `agents.templates` package provides pre-built, factory-function agents for common
GenAI use cases. Each factory returns a fully configured `FireflyAgent` ready for
immediate use, while accepting keyword arguments for customisation.

---

## Quick Start

```python
from fireflyframework_genai.agents.templates import (
    create_summarizer_agent,
    create_classifier_agent,
    create_extractor_agent,
    create_conversational_agent,
    create_router_agent,
)

# One-liner: production-ready summarizer
summarizer = create_summarizer_agent(model="openai:gpt-4o")
result = await summarizer.run("Summarize this document: ...")
```

Every factory function supports the following common keyword arguments:

- **name** -- Agent name for the registry (each template has a sensible default).
- **model** -- LLM model string; falls back to the framework default when `None`.
- **extra_instructions** -- Free-text appended to the system prompt.
- **tools** -- Additional tools to attach to the agent. When empty, templates that
  benefit from built-in tools will auto-attach them (see *Default Tools* below).
- **auto_register** -- Set to `False` to skip global registry registration.

---

## Summarizer Agent

Summarizes text and documents with tuneable length, style, and output format.

```python
from fireflyframework_genai.agents.templates import create_summarizer_agent

agent = create_summarizer_agent(
    max_length="short", # concise | short | medium | detailed
    style="technical", # professional | casual | technical | academic
    output_format="bullets", # paragraph | bullets | numbered
    model="openai:gpt-4o",
)
result = await agent.run("Long document text here...")
```

### Parameters

- **max_length** -- `"concise"` (1-2 sentences), `"short"` (1 paragraph), `"medium"` (2-3 paragraphs), `"detailed"` (comprehensive).
- **style** -- `"professional"`, `"casual"`, `"technical"`, or `"academic"`.
- **output_format** -- `"paragraph"`, `"bullets"`, or `"numbered"`.

### Default Tools

When no `tools` are provided, the summarizer is equipped with **TextTool** for
word/sentence counting and text analysis.

---

## Classifier Agent

Classifies text into user-defined categories and returns a structured
`ClassificationResult` with category, confidence, and reasoning.

```python
from fireflyframework_genai.agents.templates import create_classifier_agent

agent = create_classifier_agent(
    categories=["bug", "feature", "question"],
    descriptions={
        "bug": "Error reports and unexpected behaviour",
        "feature": "New feature requests",
        "question": "General questions about usage",
    },
    model="openai:gpt-4o",
)
result = await agent.run("The app crashes when I click save.")
# result.output -> ClassificationResult(category="bug", confidence=0.95, reasoning="...")
```

### Parameters

- **categories** (required) -- List of allowed category labels.
- **descriptions** -- Optional mapping of category to human-readable description.
- **multi_label** -- When `True`, tells the model multiple categories may apply (returns the most confident one).

### Output Type

```python
from fireflyframework_genai.agents.templates.classifier import ClassificationResult

class ClassificationResult(BaseModel):
    category: str
    confidence: float # 0.0 – 1.0
    reasoning: str
```

---

## Extractor Agent

Extracts structured data from text into a user-provided Pydantic model.

```python
from pydantic import BaseModel
from fireflyframework_genai.agents.templates import create_extractor_agent

class Invoice(BaseModel):
    vendor: str
    amount: float
    date: str
    invoice_number: str | None = None

agent = create_extractor_agent(
    Invoice,
    field_descriptions={
        "vendor": "The company or person that issued the invoice",
        "amount": "Total monetary amount",
    },
    model="openai:gpt-4o",
)
result = await agent.run("Invoice from Acme Corp, $1,234.56, dated 2026-01-15")
# result.output -> Invoice(vendor="Acme Corp", amount=1234.56, ...)
```

### Parameters

- **output_type** (required) -- A Pydantic `BaseModel` defining the fields to extract.
- **field_descriptions** -- Optional mapping of field name to extraction guidance.

### Default Tools

When no `tools` are provided, the extractor is equipped with **JsonTool** and
**TextTool** for parsing and text analysis.

---

## Conversational Agent

A memory-enabled multi-turn assistant with configurable personality and domain focus.

```python
from fireflyframework_genai.agents.templates import create_conversational_agent
from fireflyframework_genai.memory import MemoryManager

memory = MemoryManager(max_conversation_tokens=32_000)
agent = create_conversational_agent(
    personality="friendly and concise",
    domain="customer support",
    memory=memory,
    model="openai:gpt-4o",
)

cid = memory.new_conversation()
result = await agent.run("I need help with my order.", conversation_id=cid)
result = await agent.run("Can you check order #12345?", conversation_id=cid)
```

### Parameters

- **personality** -- Description of the assistant's tone (default `"helpful and professional"`).
- **domain** -- Optional domain focus (e.g. `"healthcare"`, `"finance"`). Scopes the agent's instructions.
- **memory** -- Optional `MemoryManager` for multi-turn conversation history.

### Default Tools

When no `tools` are provided, the conversational agent is equipped with
**DateTimeTool**, **CalculatorTool**, and **TextTool** so it can answer time,
math, and text questions out of the box.

---

## Router Agent

An intent-routing supervisor that analyses user messages and returns a
`RoutingDecision` indicating which child agent should handle the request.

```python
from fireflyframework_genai.agents.templates import create_router_agent

agent = create_router_agent(
    agent_map={
        "billing": "Handles billing inquiries, invoices, and payments",
        "technical": "Handles technical support and troubleshooting",
        "sales": "Handles product questions and purchasing",
    },
    fallback_agent="general",
    model="openai:gpt-4o",
)
result = await agent.run("I was charged twice for my subscription.")
# result.output -> RoutingDecision(target_agent="billing", confidence=0.92, reasoning="...")
```

### Parameters

- **agent_map** (required) -- Mapping of agent name to a description of what that agent handles.
- **fallback_agent** -- Agent name to use when no confident match is found.

### Output Type

```python
from fireflyframework_genai.agents.templates.router import RoutingDecision

class RoutingDecision(BaseModel):
    target_agent: str
    confidence: float # 0.0 – 1.0
    reasoning: str
```

---

## Combining Templates

Template agents are standard `FireflyAgent` instances, so they integrate with every
framework feature: delegation, pipelines, REST exposure, experiments, and more.

```python
from fireflyframework_genai.agents.templates import (
    create_router_agent,
    create_summarizer_agent,
    create_classifier_agent,
)

# Create specialised agents
create_summarizer_agent(name="summarizer", model="openai:gpt-4o")
create_classifier_agent(
    ["positive", "negative", "neutral"],
    name="sentiment",
    model="openai:gpt-4o",
)

# Create a router that delegates to them
router = create_router_agent(
    agent_map={
        "summarizer": "Summarizes documents and long text",
        "sentiment": "Analyses sentiment of text",
    },
    model="openai:gpt-4o",
)
```
