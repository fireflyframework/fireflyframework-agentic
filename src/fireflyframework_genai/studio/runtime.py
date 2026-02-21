"""ProjectRuntime: manages background processes for a deployed project.

Handles queue consumers, schedulers, and execution lifecycle for projects
with Input/Output boundary nodes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fireflyframework_genai.studio.codegen.models import GraphModel, NodeType
from fireflyframework_genai.studio.execution.compiler import compile_graph
from fireflyframework_genai.studio.execution.io_nodes import InputNodeConfig, OutputNodeConfig

logger = logging.getLogger(__name__)


class ProjectRuntime:
    """Manages queue consumers, schedulers, and tunnel for a project."""

    def __init__(self, project_name: str) -> None:
        self.project_name = project_name
        self.status: Literal["stopped", "starting", "running", "error"] = "stopped"
        self._graph: GraphModel | None = None
        self._input_config: InputNodeConfig | None = None
        self._output_configs: list[OutputNodeConfig] = []
        self._consumers: list[Any] = []
        self._scheduler: Any | None = None
        self._tasks: list[asyncio.Task[Any]] = []

    async def start(self, graph: GraphModel) -> None:
        """Parse IO nodes and start background processes."""
        self.status = "starting"
        self._graph = graph

        # Extract Input/Output configs
        for node in graph.nodes:
            if node.type == NodeType.INPUT:
                self._input_config = InputNodeConfig(**node.data)
            elif node.type == NodeType.OUTPUT:
                self._output_configs.append(OutputNodeConfig(**node.data))

        # Start queue consumers if queue trigger
        if self._input_config and self._input_config.trigger_type == "queue":
            await self._start_queue_consumer()

        # Start scheduler if schedule trigger
        if self._input_config and self._input_config.trigger_type == "schedule":
            await self._start_scheduler()

        self.status = "running"
        logger.info("ProjectRuntime '%s' started (trigger=%s)",
                     self.project_name,
                     self._input_config.trigger_type if self._input_config else "none")

    async def stop(self) -> None:
        """Gracefully stop all background processes."""
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

        for consumer in self._consumers:
            await consumer.stop()
        self._consumers.clear()

        if self._scheduler is not None:
            await self._scheduler.shutdown()
            self._scheduler = None

        self.status = "stopped"
        logger.info("ProjectRuntime '%s' stopped", self.project_name)

    async def execute(self, inputs: Any, trigger: str = "manual") -> Any:
        """Execute the pipeline with given inputs."""
        if self._graph is None:
            raise RuntimeError(f"Runtime '{self.project_name}' has no graph loaded")

        engine = compile_graph(self._graph)
        result = await engine.run(inputs)
        return result

    def get_status(self) -> dict[str, Any]:
        """Report runtime status."""
        return {
            "project": self.project_name,
            "status": self.status,
            "trigger_type": self._input_config.trigger_type if self._input_config else None,
            "consumers": len(self._consumers),
            "scheduler_active": self._scheduler is not None,
        }

    async def _start_queue_consumer(self) -> None:
        """Start a queue consumer based on the input config."""
        if not self._input_config or not self._input_config.queue_config:
            return

        qc = self._input_config.queue_config
        logger.info("Starting %s consumer for topic '%s'", qc.broker, qc.topic_or_queue)

        if qc.broker == "kafka":
            from fireflyframework_genai.exposure.queues.kafka import KafkaAgentConsumer
            consumer = KafkaAgentConsumer(
                topic=qc.topic_or_queue,
                group_id=qc.group_id or f"studio-{self.project_name}",
                bootstrap_servers=qc.connection_url or "localhost:9092",
            )
        elif qc.broker == "rabbitmq":
            from fireflyframework_genai.exposure.queues.rabbitmq import RabbitMQAgentConsumer
            consumer = RabbitMQAgentConsumer(
                queue_name=qc.topic_or_queue,
                connection_url=qc.connection_url or "amqp://localhost",
            )
        elif qc.broker == "redis":
            from fireflyframework_genai.exposure.queues.redis import RedisAgentConsumer
            consumer = RedisAgentConsumer(
                channel=qc.topic_or_queue,
                redis_url=qc.connection_url or "redis://localhost",
            )
        else:
            logger.warning("Unknown broker: %s", qc.broker)
            return

        self._consumers.append(consumer)
        task = asyncio.create_task(consumer.start())
        self._tasks.append(task)

    async def _start_scheduler(self) -> None:
        """Start a cron scheduler based on the input config."""
        if not self._input_config or not self._input_config.schedule_config:
            return

        sc = self._input_config.schedule_config
        logger.info("Starting scheduler: %s (%s)", sc.cron_expression, sc.timezone)

        try:
            from apscheduler import AsyncScheduler
            from apscheduler.triggers.cron import CronTrigger

            scheduler = AsyncScheduler()
            trigger = CronTrigger.from_crontab(sc.cron_expression, timezone=sc.timezone)

            async def _scheduled_run() -> None:
                payload = sc.payload or {}
                await self.execute(payload, trigger="schedule")

            await scheduler.add_schedule(_scheduled_run, trigger)
            await scheduler.start_in_background()
            self._scheduler = scheduler
        except ImportError:
            logger.warning("apscheduler not installed; scheduled triggers unavailable")
