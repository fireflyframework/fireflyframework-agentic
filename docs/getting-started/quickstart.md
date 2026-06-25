---
title: Quick Start
description: Configure a provider, define an agent, add memory, reason, validate and wire a pipeline — in five minutes.
---

# 5-Minute Quick Start

This is the shape of the framework end to end. For the full, hands-on path, see
**[The Complete Tutorial](../tutorial.md)**.

## 1. Configure

Create a `.env` file (or set environment variables):

```bash
# Provider API key (Pydantic AI reads these automatically)
OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
# GEMINI_API_KEY=...

# Framework settings
FIREFLY_AGENTIC_DEFAULT_MODEL=openai:gpt-4o
FIREFLY_AGENTIC_DEFAULT_TEMPERATURE=0.3
```

The model string is `"provider:model_name"` — e.g. `"openai:gpt-4o"`,
`"anthropic:claude-sonnet-4-20250514"`, `"google:gemini-2.0-flash"`. For
programmatic credentials (Azure, Bedrock, custom endpoints), pass a Pydantic AI
`Model` object to `FireflyAgent(model=...)` — see the
[tutorial](../tutorial.md#model-providers-authentication).

## 2. Define an agent

```python
from fireflyframework_agentic.agents import firefly_agent

@firefly_agent(name="assistant", model="openai:gpt-4o")
def assistant_instructions(ctx):
    return "You are a helpful conversational assistant."
```

## 3. Register a tool

```python
from fireflyframework_agentic.tools import firefly_tool

@firefly_tool(name="lookup", description="Look up a term")
async def lookup(query: str) -> str:
    return f"Result for {query}"
```

!!! tip "Human-in-the-loop"
    Mark a tool `@firefly_tool(name=..., requires_approval=True)` and the agent run
    **pauses** before executing it — `run()` returns a `DeferredToolRequests`
    (detect with `is_deferred(result)`). Resume with
    `agent.run(message_history=paused.all_messages(), deferred_tool_results=...)`.
    Full detail in [Tools → Human-in-the-loop](../tools.md#human-in-the-loop-tool-approval).

## 4. Add memory for multi-turn conversations

```python
from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.memory import MemoryManager

memory = MemoryManager(max_conversation_tokens=32_000)
agent = FireflyAgent(name="bot", model="openai:gpt-4o", memory=memory)

cid = memory.new_conversation()
result = await agent.run("Hello!", conversation_id=cid)
result = await agent.run("What did I just say?", conversation_id=cid)
```

## 5. Apply a reasoning pattern

```python
from fireflyframework_agentic.reasoning import ReActPattern

react = ReActPattern(max_steps=5)
result = await react.execute(agent, "What is the weather in London?")
print(result.output)
```

## 6. Validate output

```python
from pydantic import BaseModel
from fireflyframework_agentic.validation import OutputReviewer

class Answer(BaseModel):
    answer: str
    confidence: float

reviewer = OutputReviewer(output_type=Answer, max_retries=2)
result = await reviewer.review(agent, "What is 2+2?")
print(result.output)  # Answer(answer="4", confidence=0.99)
```

## 7. Wire a pipeline

```python
from fireflyframework_agentic.pipeline.builder import PipelineBuilder
from fireflyframework_agentic.pipeline.steps import AgentStep, CallableStep

pipeline = (
    PipelineBuilder("my-pipeline")
    .add_node("classify", AgentStep(classifier_agent))
    .add_node("extract", AgentStep(extractor_agent))
    .add_node("validate", CallableStep(validate_fn))
    .chain("classify", "extract", "validate")
    .build()
)
result = await pipeline.run(inputs="Process this document")
```

## 8. Embed and search (RAG)

```python
from fireflyframework_agentic.embeddings.providers import OpenAIEmbedder
from fireflyframework_agentic.vectorstores import InMemoryVectorStore, VectorDocument

embedder = OpenAIEmbedder(model="text-embedding-3-small")
store = InMemoryVectorStore(embedder=embedder)

await store.upsert([
    VectorDocument(id="1", text="Python is great for AI"),
    VectorDocument(id="2", text="Rust is fast and safe"),
])

results = await store.search_text("machine learning languages", top_k=1)
print(results[0].document.text)  # Python is great for AI
```

---

Next: **[The Complete Tutorial](../tutorial.md)** builds a full IDP pipeline from
scratch · or jump to the [Architecture](../architecture.md) overview.
