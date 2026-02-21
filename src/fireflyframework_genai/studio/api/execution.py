# Copyright 2026 Firefly Software Solutions Inc
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

"""WebSocket endpoint for real-time pipeline execution in Firefly Agentic Studio.

Provides a ``/ws/execution`` WebSocket route that accepts JSON messages,
compiles a :class:`GraphModel` into a :class:`PipelineEngine`, runs it,
and streams execution events back to the frontend in real time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect  # type: ignore[import-not-found]

from fireflyframework_genai.pipeline.context import PipelineContext
from fireflyframework_genai.studio.codegen.models import GraphModel, NodeType
from fireflyframework_genai.studio.config import StudioConfig
from fireflyframework_genai.studio.execution.compiler import CompilationError, compile_graph
from fireflyframework_genai.studio.execution.runner import StudioEventHandler

logger = logging.getLogger(__name__)


def create_execution_router() -> APIRouter:
    """Create an :class:`APIRouter` with the execution WebSocket endpoint.

    Endpoints
    ---------
    ``WS /ws/execution``
        Accept a WebSocket connection.  On receiving a JSON message with
        ``"action": "run"`` or ``"action": "debug"``, compile the attached
        graph into a pipeline and execute it, streaming events back.
    """
    router = APIRouter(tags=["execution"])

    @router.websocket("/ws/execution")
    async def execution_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        logger.info("Execution WebSocket connected")

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                    continue

                action = message.get("action")

                if action in ("run", "debug"):
                    await _handle_execution(websocket, message, debug=action == "debug")
                else:
                    await websocket.send_json({"type": "error", "message": f"Unknown action: {action}"})
        except WebSocketDisconnect:
            logger.info("Execution WebSocket disconnected")

    return router


async def _handle_execution(websocket: WebSocket, message: dict, *, debug: bool) -> None:
    """Compile the graph, run the pipeline, and stream events."""
    graph_data = message.get("graph")
    if not graph_data:
        await websocket.send_json({"type": "error", "message": "No 'graph' provided in message"})
        return

    # Parse and validate the graph
    try:
        graph = GraphModel.model_validate(graph_data)
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": f"Invalid graph: {exc}"})
        return

    # Compile graph into a PipelineEngine
    handler = StudioEventHandler()
    try:
        engine = compile_graph(graph, event_handler=handler)
    except CompilationError as exc:
        await websocket.send_json({"type": "error", "message": f"Compilation error: {exc}"})
        return

    # Prepare inputs
    inputs = message.get("inputs")
    project_name = message.get("project")

    # Wire MemoryManager when memory nodes are present
    memory = None
    has_memory = any(n.type == NodeType.MEMORY for n in graph.nodes)
    if has_memory and project_name:
        try:
            from fireflyframework_genai.memory.manager import MemoryManager
            from fireflyframework_genai.memory.store import FileStore

            config = StudioConfig()
            memory_dir = config.projects_dir / project_name / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            memory = MemoryManager(store=FileStore(base_dir=str(memory_dir)))
        except Exception as exc:
            logger.warning("Could not initialise MemoryManager: %s", exc)

    context = PipelineContext(inputs=inputs, memory=memory)

    # Wire checkpoint manager for debug mode
    if debug:
        checkpoint_mgr = getattr(websocket.app.state, "checkpoint_manager", None)
        if checkpoint_mgr is not None:
            checkpoint_mgr.clear()
            await websocket.send_json({"type": "debug_enabled", "message": "Debug mode active"})

    # Launch the pipeline in a background task
    t0 = time.monotonic()
    run_task = asyncio.create_task(engine.run(context, inputs=inputs))

    # Stream events until pipeline completes
    try:
        while not run_task.done():
            await handler.wait_for_event(0.5)
            events = handler.drain_events()
            for event in events:
                await websocket.send_json(event)
                # Create checkpoints for debug mode
                if debug and event.get("type") == "node_complete":
                    checkpoint_mgr = getattr(websocket.app.state, "checkpoint_manager", None)
                    if checkpoint_mgr is not None:
                        node_id = event.get("node_id", "")
                        result = context.get_node_result(node_id)
                        cp = checkpoint_mgr.create(
                            node_id=node_id,
                            state={"output": result.output if hasattr(result, "output") else result},
                            inputs=dict(context.results),
                        )
                        await websocket.send_json(
                            {
                                "type": "checkpoint_created",
                                "index": cp.index,
                                "node_id": cp.node_id,
                                "state": cp.state,
                                "inputs": cp.inputs,
                                "timestamp": cp.timestamp,
                                "branch_id": getattr(cp, "branch_id", None),
                                "parent_index": getattr(cp, "parent_index", None),
                            }
                        )

        # Drain any remaining events after completion
        events = handler.drain_events()
        for event in events:
            await websocket.send_json(event)

        # Get the result
        result = await run_task
        duration_ms = (time.monotonic() - t0) * 1000

        await websocket.send_json(
            {
                "type": "pipeline_result",
                "success": result.success,
                "output": str(result.final_output) if result.final_output is not None else None,
                "duration_ms": round(duration_ms, 2),
                "pipeline_name": result.pipeline_name,
            }
        )

    except Exception as exc:
        duration_ms = (time.monotonic() - t0) * 1000
        logger.exception("Pipeline execution failed")

        # Cancel the task if it's still running
        if not run_task.done():
            run_task.cancel()

        await websocket.send_json(
            {
                "type": "pipeline_result",
                "success": False,
                "output": str(exc),
                "duration_ms": round(duration_ms, 2),
                "pipeline_name": graph.metadata.get("name", "studio-pipeline"),
            }
        )
