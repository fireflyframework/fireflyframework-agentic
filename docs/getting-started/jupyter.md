---
title: Jupyter Notebooks
description: Firefly Agentic is async-first, so await works directly in notebook cells — no asyncio.run() or nest_asyncio needed.
---

# Using in Jupyter Notebooks

Firefly Agentic works seamlessly in Jupyter and JupyterLab. Because the framework
is async-first, use `await` directly in cells — Jupyter provides a running event
loop automatically.

## Setup

```bash
cd fireflyframework-agentic
source .venv/bin/activate            # the venv created by the installer
pip install ipykernel
python -m ipykernel install --user --name fireflyagentic --display-name "Firefly Agentic"
jupyter lab                          # or: jupyter notebook
```

Then select the **Firefly Agentic** kernel when creating a new notebook.

## Example notebook

```python
# Cell 1 — configure
import os
os.environ["OPENAI_API_KEY"] = "sk-..."          # or set in .env
os.environ["FIREFLY_AGENTIC_DEFAULT_MODEL"] = "openai:gpt-4o"
```

```python
# Cell 2 — create an agent
from fireflyframework_agentic.agents import FireflyAgent

agent = FireflyAgent(name="notebook-bot", model="openai:gpt-4o")
result = await agent.run("Explain quantum entanglement in two sentences.")
print(result.output)
```

```python
# Cell 3 — memory for multi-turn conversations
from fireflyframework_agentic.memory import MemoryManager

memory = MemoryManager(max_conversation_tokens=32_000)
agent_with_mem = FireflyAgent(name="chat", model="openai:gpt-4o", memory=memory)

cid = memory.new_conversation()
await agent_with_mem.run("My name is Alice.", conversation_id=cid)
result = await agent_with_mem.run("What is my name?", conversation_id=cid)
print(result.output)  # Alice
```

```python
# Cell 4 — reasoning patterns
from fireflyframework_agentic.reasoning import ReActPattern

react = ReActPattern(max_steps=5)
result = await react.execute(agent, "What are the top 3 uses of Python in 2026?")
print(result.output)
```

```python
# Cell 5 — structured output with validation
from pydantic import BaseModel
from fireflyframework_agentic.validation import OutputReviewer

class Summary(BaseModel):
    title: str
    bullet_points: list[str]
    confidence: float

reviewer = OutputReviewer(output_type=Summary, max_retries=2)
result = await reviewer.review(agent, "Summarize the benefits of async Python.")
result.output  # displays the structured Summary object in the notebook
```

!!! tip
    You do not need `asyncio.run()` or `nest_asyncio` in Jupyter — `await` works at
    the top level of any cell because Jupyter runs its own event loop.
