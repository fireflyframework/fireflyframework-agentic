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

"""Built-in date/time tool for retrieving the current date, time, and timezone info.

This is one of the most commonly needed tools in production GenAI
applications -- LLMs do not have access to the current date/time.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, available_timezones

from fireflyframework_agentic.tools.base import BaseTool, GuardProtocol, ParameterSpec


class DateTimeTool(BaseTool):
    """Return the current date and time, with optional timezone conversion.

    Supported actions:

    * ``"now"`` -- current date-time in the given format and timezone.
    * ``"date"`` -- current date only (YYYY-MM-DD).
    * ``"time"`` -- current time only (HH:MM:SS).
    * ``"timestamp"`` -- current Unix timestamp (seconds since epoch).
    * ``"timezones"`` -- list available timezone names.

    Parameters:
        default_timezone: IANA timezone name (e.g. ``"UTC"``,
            ``"America/New_York"``).  Defaults to ``"UTC"``.
        default_format: :meth:`~datetime.datetime.strftime` format string.
        guards: Optional guard chain.
    """

    def __init__(
        self,
        *,
        default_timezone: str = "UTC",
        default_format: str = "%Y-%m-%dT%H:%M:%S%z",
        guards: Sequence[GuardProtocol] = (),
    ) -> None:
        super().__init__(
            "datetime",
            description="Get the current date, time, or Unix timestamp with optional timezone conversion",
            tags=["datetime", "utility"],
            guards=guards,
            parameters=[
                ParameterSpec(
                    name="action",
                    type_annotation="str",
                    description="One of: now, date, time, timestamp, timezones",
                    required=False,
                    default="now",
                ),
                ParameterSpec(
                    name="timezone",
                    type_annotation="str",
                    description="IANA timezone name (e.g. 'America/New_York')",
                    required=False,
                    default=default_timezone,
                ),
                ParameterSpec(
                    name="format",
                    type_annotation="str",
                    description="strftime format string",
                    required=False,
                    default=default_format,
                ),
            ],
        )
        self._default_tz = default_timezone
        self._default_fmt = default_format

    async def _execute(self, **kwargs: Any) -> str | float | list[str]:
        action: str = kwargs.get("action", "now")
        tz_name: str = kwargs.get("timezone", self._default_tz)
        fmt: str = kwargs.get("format", self._default_fmt)

        tz = self._resolve_timezone(tz_name)
        now = datetime.now(tz)

        if action == "now":
            return now.strftime(fmt)
        if action == "date":
            return now.strftime("%Y-%m-%d")
        if action == "time":
            return now.strftime("%H:%M:%S")
        if action == "timestamp":
            return now.timestamp()
        if action == "timezones":
            return sorted(available_timezones())

        raise ValueError(f"Unknown action '{action}'; expected now, date, time, timestamp, or timezones")

    @staticmethod
    def _resolve_timezone(name: str) -> timezone | ZoneInfo:
        """Resolve a timezone name to a :class:`datetime.timezone` or :class:`ZoneInfo`."""
        if name.upper() == "UTC":
            return UTC
        return ZoneInfo(name)
