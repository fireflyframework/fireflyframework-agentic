---
title: Quick Start
description: Configure a provider, define an agent, add memory, reason, validate and wire a pipeline — in five minutes.
---

# 5-Minute Quick Start

These Python blocks build on the preceding blocks and use notebook-style `await`.
In a script, place the calls in `async def main()` and finish with
`asyncio.run(main())`. For a complete executable script, see the
[model-agnostic example](https://github.com/fireflyframework/fireflyframework-agentic/blob/main/examples/model_agnostic_agent.py).

This is the shape of the framework end to end. For the full, hands-on path, see
**[The Complete Tutorial](../tutorial.md)**.

## 1. Configure

Create a `.env` file (or set environment variables):

```bash
# Provider API key (read from the environment)
OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
# GEMINI_API_KEY=...

# Framework settings
FIREFLY_AGENTIC_DEFAULT_MODEL=openai-responses:gpt-6-luna
```

The model string selects the provider and API. Keep it in configuration; agent,
tool, memory, and output-schema code can remain the same. Use `ModelOptions` for
portable controls and [`ModelSpec` / `ModelFactory`](../models.md) for application-managed
credentials, Azure deployments, and custom endpoints.

Existing `openai:` / `azure:` prefixes retain Chat Completions. Select
`openai-responses:` / `azure-responses:` explicitly for Responses. GPT-6 Astra
requires Responses for tools; Sol and Luna require `reasoning="none"` for Chat
tools. With Responses, reasoning and tools can be combined. Leave the global
temperature unset for reasoning models; see [model compatibility](../models.md#openai-choose-the-api-explicitly).

## 2. Define an agent

```python
from fireflyframework_agentic.agents import firefly_agent
from fireflyframework_agentic.models import ModelOptions

@firefly_agent(name="assistant", model_options=ModelOptions(max_tokens=4096))
def assistant_instructions(ctx):
    return "You are a helpful conversational assistant."
```

## 3. Attach a tool

Registering a tool makes it discoverable; passing it to `tools=` makes it callable
by this agent. Firefly adapts decorated tools and `ToolKit` instances automatically.

```python
from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.tools import firefly_tool

GLOSSARY = {
    "bounded retries": "Retry a failed operation up to a configured attempt limit.",
    "backoff": "Increase the delay between retry attempts to reduce load.",
}

@firefly_tool(name="lookup", description="Look up a term in the local engineering glossary")
async def lookup(query: str) -> str:
    return GLOSSARY.get(query.strip().lower(), "No glossary entry exists for that term.")

agent = FireflyAgent(name="glossary", tools=[lookup])
result = await agent.run("Use the glossary to explain bounded retries.")
print(result.output)
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
agent = FireflyAgent(name="bot", tools=[lookup], memory=memory)

cid = memory.new_conversation()
result = await agent.run("Hello!", conversation_id=cid)
result = await agent.run("What did I just say?", conversation_id=cid)
```

## 5. Apply a reasoning pattern

```python
from fireflyframework_agentic.reasoning import ReActPattern

react = ReActPattern(max_steps=5)
result = await react.execute(agent, "Explain why bounded retries and backoff work together.")
print(result.output)
```

## 6. Validate output

```python
from pydantic import BaseModel
from fireflyframework_agentic.validation import OutputReviewer

class Answer(BaseModel):
    answer: str
    confidence: float

answer_agent = FireflyAgent(name="answer", output_type=Answer)
reviewer = OutputReviewer(output_type=Answer, max_retries=2)
result = await reviewer.review(answer_agent, "What is 2+2?")
print(result.output)  # Answer(answer="4", confidence=0.99)
```

## 7. Wire a pipeline

```python
from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.pipeline.builder import PipelineBuilder
from fireflyframework_agentic.pipeline.steps import AgentStep

summarizer = FireflyAgent(name="summarizer", instructions="Summarize the supplied text in one sentence.")
editor = FireflyAgent(name="editor", instructions="Rewrite the summary in clear, concise English.")
pipeline = (
    PipelineBuilder("summarize-and-edit")
    .add_node("summarize", AgentStep(summarizer))
    .add_node("edit", AgentStep(editor))
    .chain("summarize", "edit")
    .build()
)
result = await pipeline.run(inputs="Retries must stop after three attempts and wait longer between attempts.")
print(result.outputs["edit"].output)
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
