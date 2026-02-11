# Memory Guide

Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.

The Memory module provides conversation history, working memory, and pluggable
storage backends for agents, multi-agent delegation, reasoning patterns, and
pipelines. It ensures that LLM interactions are stateful and context-aware
across turns, sessions, and pipeline steps.

---

## Architecture

The memory subsystem has four layers:

```mermaid
graph TD
    MM[MemoryManager] --> CM[ConversationMemory]
    MM --> WM[WorkingMemory]
    WM --> STORE[MemoryStore]
    CM --> TOKENS[TokenEstimator]
    STORE --> IM[InMemoryStore]
    STORE --> FS[FileStore]
    STORE --> CUSTOM[Custom Backend]
```

- **ConversationMemory** -- Token-aware, per-conversation chat history that
  wraps pydantic-ai's `message_history` mechanism.
- **WorkingMemory** -- Scoped key-value scratchpad for session facts, entities,
  and intermediate state.
- **MemoryStore** -- Pluggable persistence backends (in-memory, file, custom).
- **MemoryManager** -- Facade that composes conversation and working memory
  behind a single API.

---

## Quick Start

```python
from fireflyframework_genai.agents import FireflyAgent
from fireflyframework_genai.memory import MemoryManager

# Create a memory manager
memory = MemoryManager(max_conversation_tokens=32_000)

# Attach to an agent
agent = FireflyAgent(
    name="assistant",
    model="openai:gpt-4o",
    memory=memory,
)

# Start a conversation
conv_id = memory.new_conversation()

# Each run automatically loads/stores conversation history
result1 = await agent.run("What is Python?", conversation_id=conv_id)
result2 = await agent.run("What about its type system?", conversation_id=conv_id)
# result2 has full context from result1
```

---

## Conversation Memory

`ConversationMemory` manages `list[ModelMessage]` per conversation ID. It
automatically enforces a token budget by dropping oldest turns (FIFO).

```python
from fireflyframework_genai.memory import ConversationMemory

conv_mem = ConversationMemory(max_tokens=16_000)
cid = conv_mem.new_conversation()

# After an agent run, store the turn
conv_mem.add_turn(
    cid,
    user_prompt="Hello",
    assistant_response="Hi there!",
    raw_messages=result.new_messages(), # pydantic-ai ModelMessage list
)

# Before the next run, get the trimmed history
history = conv_mem.get_message_history(cid)
# Pass to agent: agent.run("Next question", message_history=history)
```

When `FireflyAgent` has a `memory` attached, all of this happens automatically.

### Token Budget

When the total token count exceeds `max_tokens`, older turns are evicted from
the front. The `TokenEstimator` (from the content module) is used for counting.

```python
conv_mem = ConversationMemory(max_tokens=4_000)
# After many turns, only the most recent ones fitting in 4000 tokens are returned
```

### Conversation Summarization

When many turns are evicted, important context can be lost. The optional
**summarization** feature compresses evicted turns into a summary that is
retained for context enrichment.

Summarization triggers when the total token count exceeds `summarize_threshold`.
Pass a `summarizer` callable that takes a list of `ConversationTurn` objects
and returns a summary string:

```python
from fireflyframework_genai.memory import ConversationMemory

def my_summarizer(turns):
    texts = [f"{t.user_prompt} -> {t.assistant_response}" for t in turns]
    return "Summary of earlier conversation: " + "; ".join(texts)

conv_mem = ConversationMemory(
    max_tokens=4_000,
    summarize_threshold=3_000,
    summarizer=my_summarizer,
)
```

Retrieve the summary for a conversation:

```python
summary = conv_mem.get_summary(conversation_id)
if summary:
    print(f"Evicted turns summarised as: {summary}")
```

In production, the summarizer can be an LLM call that condenses older turns
into a concise paragraph, preserving key facts while staying within budget.

Configure the threshold via environment variable:

```bash
export FIREFLY_GENAI_MEMORY_SUMMARIZE_THRESHOLD=10
```

---

## Working Memory

`WorkingMemory` is a scoped key-value store for facts and intermediate state.
It is useful for passing context between pipeline steps, storing extraction
results for validation, or maintaining entities across reasoning iterations.

```python
from fireflyframework_genai.memory import WorkingMemory

wm = WorkingMemory(scope_id="idp-session-42")
wm.set("doc_type", "invoice")
wm.set("vendor", "Acme Corp")

print(wm.get("doc_type")) # "invoice"
print(wm.to_dict()) # {"doc_type": "invoice", "vendor": "Acme Corp"}

# Render as a text block for prompt injection
print(wm.to_context_string())
# Working Memory:
# - doc_type: invoice
# - vendor: Acme Corp
```

### Scoped Isolation

Multiple `WorkingMemory` instances can share the same store backend while
maintaining independent namespaces:

```python
from fireflyframework_genai.memory import InMemoryStore, WorkingMemory

store = InMemoryStore()
agent_a_mem = WorkingMemory(store=store, scope_id="agent_a")
agent_b_mem = WorkingMemory(store=store, scope_id="agent_b")

agent_a_mem.set("key", "from A")
agent_b_mem.set("key", "from B")
assert agent_a_mem.get("key") == "from A"
assert agent_b_mem.get("key") == "from B"
```

---

## Storage Backends

### InMemoryStore

Dict-backed, fast, non-persistent. Suitable for testing and short-lived sessions.

```python
from fireflyframework_genai.memory import InMemoryStore
store = InMemoryStore()
```

### FileStore

JSON file persistence. Each namespace is a separate file.

```python
from fireflyframework_genai.memory import FileStore
store = FileStore(base_dir=".firefly_memory")
```

`FileStore` also provides **async wrappers** (`save_async`, `load_async`,
`delete_async`, `clear_async`) that delegate blocking I/O to
`asyncio.to_thread()`, keeping the event loop non-blocking in async
applications:

```python
await store.save_async("conversations", entry)
entries = await store.load_async("conversations")
```

### PostgreSQLStore

Production-grade PostgreSQL persistence with connection pooling. Requires
`asyncpg` (install via `pip install fireflyframework-genai[postgres]`).

```python
from fireflyframework_genai.memory.database_store import PostgreSQLStore

store = PostgreSQLStore(
    url="postgresql://user:pass@localhost/firefly",
    pool_size=10,
)

# Use with MemoryManager
memory = MemoryManager(store=store)
```

**Environment Configuration:**

```bash
export FIREFLY_GENAI_MEMORY_BACKEND=postgres
export FIREFLY_GENAI_MEMORY_POSTGRES_URL=postgresql://user:pass@localhost/firefly
export FIREFLY_GENAI_MEMORY_POSTGRES_POOL_SIZE=10
```

The store automatically creates required tables on first use. All operations
are async-native using `asyncpg` for optimal performance.

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS firefly_memory (
    namespace VARCHAR(255) NOT NULL,
    entry_id VARCHAR(255) NOT NULL,
    key VARCHAR(255) NOT NULL,
    data JSONB NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (namespace, entry_id)
);

CREATE INDEX idx_namespace_key ON firefly_memory(namespace, key);
CREATE INDEX idx_created_at ON firefly_memory(created_at);
```

### MongoDBStore

Scalable MongoDB persistence with connection pooling. Requires `motor` and
`pymongo` (install via `pip install fireflyframework-genai[mongodb]`).

```python
from fireflyframework_genai.memory.database_store import MongoDBStore

store = MongoDBStore(
    url="mongodb://localhost:27017/",
    database="firefly",
    pool_size=10,
)

memory = MemoryManager(store=store)
```

**Environment Configuration:**

```bash
export FIREFLY_GENAI_MEMORY_BACKEND=mongodb
export FIREFLY_GENAI_MEMORY_MONGODB_URL=mongodb://localhost:27017/
export FIREFLY_GENAI_MEMORY_MONGODB_DATABASE=firefly
export FIREFLY_GENAI_MEMORY_MONGODB_POOL_SIZE=10
```

The store automatically creates required collections and indexes:

```javascript
// Collection: firefly_memory
{
  namespace: "conversations",
  entry_id: "conv-123",
  key: "user-session",
  data: { ... },
  metadata: { ... },
  created_at: ISODate("..."),
  updated_at: ISODate("...")
}

// Indexes
db.firefly_memory.createIndex({ namespace: 1, entry_id: 1 }, { unique: true })
db.firefly_memory.createIndex({ namespace: 1, key: 1 })
db.firefly_memory.createIndex({ created_at: 1 })
```

### Custom Backends

Implement the `MemoryStore` protocol for Redis, SQL, or any other backend:

```python
from fireflyframework_genai.memory import MemoryStore, MemoryEntry

class RedisStore:
    def save(self, namespace: str, entry: MemoryEntry) -> None: ...
    def load(self, namespace: str) -> list[MemoryEntry]: ...
    def load_by_key(self, namespace: str, key: str) -> MemoryEntry | None: ...
    def delete(self, namespace: str, entry_id: str) -> None: ...
    def clear(self, namespace: str) -> None: ...
```

---

## Conversation Export & Import

`ConversationMemory` supports exporting and importing conversations as
JSON-serialisable dictionaries. This is useful for backup, migration,
debugging, and cross-service conversation transfer.

```python
# Export a conversation
data = conv_mem.export_conversation(conversation_id)
# data is a dict with: conversation_id, turns, summary, total_tokens

# Import into another instance (or after restart)
new_id = conv_mem.import_conversation(data)
# Or override the conversation ID:
new_id = conv_mem.import_conversation(data, conversation_id="custom-id")
```

Exported turns include `turn_id`, `user_prompt`, `assistant_response`,
`token_estimate`, and `metadata`. Note that `raw_messages` (pydantic-ai
`ModelMessage` objects) are not exported as they are not portable.

---

## LLM-Based Summarization

`create_llm_summarizer()` is a factory function that returns a callable
suitable for `ConversationMemory`'s `summarizer` parameter. It uses an
ephemeral Pydantic AI agent to compress evicted turns into a concise summary.

```python
from fireflyframework_genai.memory.summarization import create_llm_summarizer

summarizer = create_llm_summarizer(model="openai:gpt-4o-mini")
conv_mem = ConversationMemory(
    max_tokens=4_000,
    summarize_threshold=3_000,
    summarizer=summarizer,
)
```

Parameters:

- **`model`** — Pydantic AI model string or `Model` instance. When `None`,
  uses the framework default model.
- **`prompt_template`** — Custom prompt template. Must contain a
  `{turns_text}` placeholder.
- **`max_summary_tokens`** — Soft limit on summary length (guidance, not
  enforced).

If the LLM call fails, the factory falls back to a non-LLM truncation
strategy that extracts key sentences from the most recent turns.

---

## MemoryManager

`MemoryManager` is the single entry point
memory. It is the object you attach to agents, delegation routers, and pipelines.

```python
from fireflyframework_genai.memory import MemoryManager

mgr = MemoryManager(
    max_conversation_tokens=32_000,
    working_scope_id="main-session",
)

# Conversation
cid = mgr.new_conversation()
mgr.add_turn(cid, "hello", "hi", raw_messages)
history = mgr.get_message_history(cid)

# Working memory
mgr.set_fact("doc_type", "invoice")
mgr.get_fact("doc_type") # "invoice"
```

### Forking

When delegating to a sub-agent or branching a pipeline, `fork()` creates a
child manager that shares conversation memory but has independent working memory:

```python
child = mgr.fork(working_scope_id="sub-agent-classify")
child.set_fact("classification", "invoice")
# parent's working memory is unaffected
```

---

## Integration Points

### Agents

```python
agent = FireflyAgent(name="bot", model="openai:gpt-4o", memory=mgr)
result = await agent.run("Hi", conversation_id=cid)
# message_history is auto-injected, new messages auto-stored
```

### Multi-Agent Delegation

```python
from fireflyframework_genai.agents.delegation import DelegationRouter, RoundRobinStrategy

router = DelegationRouter([agent_a, agent_b], RoundRobinStrategy(), memory=mgr)
result = await router.route("Translate this text.")
# delegated agent receives a forked memory scope
```

### Pipelines

```python
from fireflyframework_genai.pipeline.context import PipelineContext

ctx = PipelineContext(inputs=data, memory=mgr)
result = await engine.run(context=ctx)
# AgentStep and ReasoningStep automatically propagate memory
```

### Reasoning Patterns

Memory is injected into the reasoning state dict as `state["memory"]`:

```python
result = await pattern.execute(agent, "Analyze this", memory=mgr)
# Inside pattern hooks: state["memory"].working.set("key", "value")
```

### REST Exposure

Pass `conversation_id` in the request body for multi-turn conversations:

```json
{
  "prompt": "What did we discuss earlier?",
  "conversation_id": "abc123"
}
```

---

## Configuration

Memory settings are configured via environment variables:

```bash
export FIREFLY_GENAI_MEMORY_BACKEND=in_memory # or "file"
export FIREFLY_GENAI_MEMORY_MAX_CONVERSATION_TOKENS=128000
export FIREFLY_GENAI_MEMORY_SUMMARIZE_THRESHOLD=10
export FIREFLY_GENAI_MEMORY_FILE_DIR=.firefly_memory
```
