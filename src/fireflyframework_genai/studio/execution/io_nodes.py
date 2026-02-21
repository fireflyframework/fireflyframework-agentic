"""Input and Output boundary node configuration models.

These models define the data schemas for Input and Output nodes, which
serve as pipeline entry and exit points in the BPM execution model.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, field_validator


class QueueConfig(BaseModel):
    """Configuration for queue-based triggers and destinations."""

    broker: Literal["kafka", "rabbitmq", "redis"]
    topic_or_queue: str
    group_id: str = ""
    connection_url: str = ""


class ScheduleConfig(BaseModel):
    """Configuration for cron-based scheduled triggers."""

    cron_expression: str
    timezone: str = "UTC"
    payload: dict[str, Any] | None = None


class HttpConfig(BaseModel):
    """Configuration for HTTP triggers."""

    method: str = "POST"
    path_suffix: str = ""
    auth_required: bool = False


class FileConfig(BaseModel):
    """Configuration for file upload triggers."""

    accepted_types: list[str] = ["*/*"]
    max_size_mb: int = 50


class WebhookConfig(BaseModel):
    """Configuration for webhook destinations."""

    url: str
    method: str = "POST"
    headers: dict[str, str] = {}


class StoreConfig(BaseModel):
    """Configuration for file/database storage destinations."""

    storage_type: Literal["file", "database"]
    path_or_table: str


_VALID_TRIGGER_TYPES = frozenset({"manual", "http", "queue", "schedule", "file_upload"})
_VALID_DESTINATION_TYPES = frozenset({"response", "queue", "webhook", "store", "multi"})


class InputNodeConfig(BaseModel):
    """Parsed configuration for an Input boundary node."""

    trigger_type: str
    schema: dict[str, Any] | None = None
    queue_config: QueueConfig | None = None
    schedule_config: ScheduleConfig | None = None
    http_config: HttpConfig | None = None
    file_config: FileConfig | None = None

    @field_validator("trigger_type")
    @classmethod
    def _validate_trigger_type(cls, v: str) -> str:
        if v not in _VALID_TRIGGER_TYPES:
            raise ValueError(
                f"Invalid trigger_type '{v}'. Must be one of: {', '.join(sorted(_VALID_TRIGGER_TYPES))}"
            )
        return v


class OutputNodeConfig(BaseModel):
    """Parsed configuration for an Output boundary node."""

    destination_type: str
    response_schema: dict[str, Any] | None = None
    queue_config: QueueConfig | None = None
    webhook_config: WebhookConfig | None = None
    store_config: StoreConfig | None = None
    destinations: list[dict[str, Any]] | None = None

    @field_validator("destination_type")
    @classmethod
    def _validate_destination_type(cls, v: str) -> str:
        if v not in _VALID_DESTINATION_TYPES:
            raise ValueError(
                f"Invalid destination_type '{v}'. Must be one of: {', '.join(sorted(_VALID_DESTINATION_TYPES))}"
            )
        return v
