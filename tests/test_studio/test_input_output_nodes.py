"""Tests for Input and Output boundary nodes."""

from __future__ import annotations

import pytest

from fireflyframework_genai.studio.codegen.models import GraphNode, NodeType
from fireflyframework_genai.studio.execution.io_nodes import (
    FileConfig,
    HttpConfig,
    InputNodeConfig,
    OutputNodeConfig,
    QueueConfig,
    ScheduleConfig,
    StoreConfig,
    WebhookConfig,
)


class TestInputOutputNodeTypes:
    def test_input_node_type_exists(self):
        assert NodeType.INPUT == "input"

    def test_output_node_type_exists(self):
        assert NodeType.OUTPUT == "output"

    def test_input_node_creation(self):
        node = GraphNode(
            id="input_1",
            type=NodeType.INPUT,
            label="HTTP Input",
            position={"x": 0, "y": 200},
            data={"trigger_type": "http"},
        )
        assert node.type == "input"
        assert node.data["trigger_type"] == "http"

    def test_output_node_creation(self):
        node = GraphNode(
            id="output_1",
            type=NodeType.OUTPUT,
            label="API Response",
            position={"x": 600, "y": 200},
            data={"destination_type": "response"},
        )
        assert node.type == "output"
        assert node.data["destination_type"] == "response"


class TestInputNodeConfig:
    def test_manual_trigger(self):
        config = InputNodeConfig(trigger_type="manual")
        assert config.trigger_type == "manual"
        assert config.schema is None

    def test_http_trigger(self):
        config = InputNodeConfig(
            trigger_type="http",
            http_config=HttpConfig(method="POST", auth_required=True),
        )
        assert config.http_config is not None
        assert config.http_config.auth_required is True

    def test_queue_trigger(self):
        config = InputNodeConfig(
            trigger_type="queue",
            queue_config=QueueConfig(
                broker="kafka",
                topic_or_queue="pipeline-input",
                group_id="studio-group",
            ),
        )
        assert config.queue_config is not None
        assert config.queue_config.broker == "kafka"

    def test_schedule_trigger(self):
        config = InputNodeConfig(
            trigger_type="schedule",
            schedule_config=ScheduleConfig(
                cron_expression="0 */6 * * *",
                timezone="America/New_York",
                payload={"action": "report"},
            ),
        )
        assert config.schedule_config is not None
        assert config.schedule_config.cron_expression == "0 */6 * * *"

    def test_file_upload_trigger(self):
        config = InputNodeConfig(
            trigger_type="file_upload",
            file_config=FileConfig(
                accepted_types=["application/pdf", "text/csv"],
                max_size_mb=100,
            ),
        )
        assert config.file_config is not None
        assert "application/pdf" in config.file_config.accepted_types

    def test_invalid_trigger_type(self):
        with pytest.raises(ValueError):
            InputNodeConfig(trigger_type="invalid")


class TestOutputNodeConfig:
    def test_response_destination(self):
        config = OutputNodeConfig(destination_type="response")
        assert config.destination_type == "response"

    def test_queue_destination(self):
        config = OutputNodeConfig(
            destination_type="queue",
            queue_config=QueueConfig(broker="redis", topic_or_queue="results"),
        )
        assert config.queue_config is not None

    def test_webhook_destination(self):
        config = OutputNodeConfig(
            destination_type="webhook",
            webhook_config=WebhookConfig(url="https://example.com/callback"),
        )
        assert config.webhook_config is not None

    def test_store_destination(self):
        config = OutputNodeConfig(
            destination_type="store",
            store_config=StoreConfig(storage_type="file", path_or_table="/tmp/results.json"),
        )
        assert config.store_config is not None

    def test_invalid_destination_type(self):
        with pytest.raises(ValueError):
            OutputNodeConfig(destination_type="invalid")
