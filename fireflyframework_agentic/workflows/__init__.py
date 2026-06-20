# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Dynamic workflows -- a code-defined orchestration DSL over pydantic-ai agents.

A workflow is a deterministic Python function that fans out isolated sub-agents
and reduces their results in plain code, mirroring Claude's Workflow mechanism:

    from fireflyframework_agentic.workflows import workflow, agent, parallel, pipeline, phase

    @workflow(name="deep_research", args_schema=ResearchArgs)
    async def deep_research(args, ctx):
        with phase("search"):
            hits = await parallel([lambda q=q: agent(f"search: {q}", model=args.model)
                                   for q in args.queries])
        candidates = dedupe([h for h in hits if h is not None])   # reduce in plain Python
        with phase("verify"):
            checked = await pipeline(candidates, verify_stage, score_stage)
        return await agent("write a cited report", deps=checked, model=args.model)

Run it with ``await deep_research(args)`` or ``run_workflow("deep_research", args)``.
The engine enforces a :class:`WorkflowBudget` (concurrency / agent-count / token
ceilings) and journals every agent call for deterministic resume.
"""

from fireflyframework_agentic.workflows.context import (
    WorkflowBudget,
    WorkflowContext,
    current_workflow,
)
from fireflyframework_agentic.workflows.journal import Journal
from fireflyframework_agentic.workflows.primitives import (
    agent,
    log,
    map_agents,
    parallel,
    phase,
    pipeline,
)
from fireflyframework_agentic.workflows.registry import (
    Workflow,
    WorkflowRegistry,
    run_workflow,
    workflow,
    workflow_registry,
)
from fireflyframework_agentic.workflows.routing import (
    ComplexityHeuristicStrategy,
    CostFloorStrategy,
    ModelSelectionStrategy,
    SmartRoutingRunner,
    price_model,
)
from fireflyframework_agentic.workflows.runner import (
    AgentCall,
    AgentRunner,
    DefaultAgentRunner,
)
from fireflyframework_agentic.workflows.verify import (
    CascadeResult,
    Verdict,
    adversarial_verify,
    cascade,
    judge_panel,
    loop_until_dry,
)

__all__ = [
    "AgentCall",
    "AgentRunner",
    "CascadeResult",
    "ComplexityHeuristicStrategy",
    "CostFloorStrategy",
    "DefaultAgentRunner",
    "Journal",
    "ModelSelectionStrategy",
    "SmartRoutingRunner",
    "Verdict",
    "Workflow",
    "WorkflowBudget",
    "WorkflowContext",
    "WorkflowRegistry",
    "adversarial_verify",
    "agent",
    "cascade",
    "current_workflow",
    "judge_panel",
    "log",
    "loop_until_dry",
    "map_agents",
    "parallel",
    "phase",
    "pipeline",
    "price_model",
    "run_workflow",
    "workflow",
    "workflow_registry",
]
