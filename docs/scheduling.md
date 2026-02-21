# Scheduled Pipeline Triggers

Copyright 2026 Firefly Software Solutions Inc. Licensed under the Apache License 2.0.

Pipelines with an Input node configured for `schedule` trigger type run
automatically on a cron schedule. The runtime uses APScheduler to manage
cron jobs with timezone support and optional payload injection.

---

## Prerequisites

APScheduler is included in the Studio extras:

```bash
pip install "fireflyframework-genai[studio]"
```

If APScheduler is not installed, the runtime logs a warning and skips
scheduler creation. Queue and manual triggers still work.

---

## Cron Expression Syntax

Cron expressions use the standard five-field format:

```
 +------------ minute (0-59)
 | +---------- hour (0-23)
 | | +-------- day of month (1-31)
 | | | +------ month (1-12)
 | | | | +---- day of week (0-6, 0=Sunday)
 | | | | |
 * * * * *
```

### Common Examples

| Expression | Description |
|---|---|
| `*/5 * * * *` | Every 5 minutes |
| `0 * * * *` | Every hour on the hour |
| `0 0 * * *` | Daily at midnight |
| `0 9 * * 1-5` | Weekdays at 9:00 AM |
| `0 0 1 * *` | First day of every month at midnight |
| `30 2 * * 0` | Sundays at 2:30 AM |
| `0 */6 * * *` | Every 6 hours |
| `0 8,17 * * *` | At 8:00 AM and 5:00 PM |
| `15 10 * * 1` | Mondays at 10:15 AM |

---

## Timezone Configuration

The `timezone` field in `ScheduleConfig` accepts any IANA timezone string.
Defaults to `UTC` if omitted.

```json
{
  "trigger_type": "schedule",
  "schedule_config": {
    "cron_expression": "0 9 * * 1-5",
    "timezone": "America/New_York"
  }
}
```

Common timezone values:

| Timezone | UTC Offset | Region |
|---|---|---|
| `UTC` | +00:00 | Coordinated Universal Time |
| `America/New_York` | -05:00 / -04:00 | US Eastern |
| `America/Chicago` | -06:00 / -05:00 | US Central |
| `America/Los_Angeles` | -08:00 / -07:00 | US Pacific |
| `Europe/London` | +00:00 / +01:00 | UK |
| `Europe/Berlin` | +01:00 / +02:00 | Central Europe |
| `Asia/Tokyo` | +09:00 | Japan |
| `Asia/Shanghai` | +08:00 | China |
| `Australia/Sydney` | +10:00 / +11:00 | Australia Eastern |

---

## Payload Injection

Scheduled runs can inject a static payload as the pipeline input. This is
useful for passing configuration or context to the pipeline.

```json
{
  "trigger_type": "schedule",
  "schedule_config": {
    "cron_expression": "0 0 * * *",
    "timezone": "UTC",
    "payload": {
      "source": "daily_report",
      "region": "us-east-1",
      "lookback_hours": 24
    }
  }
}
```

When no payload is specified, the pipeline receives an empty dict `{}`.

---

## How It Works

When you start a project runtime (via the TopBar play button or
`POST /api/projects/{name}/runtime/start`), the `ProjectRuntime` class:

1. Parses the Input node and finds `trigger_type: "schedule"`.
2. Reads the `ScheduleConfig` to get the cron expression and timezone.
3. Creates an `AsyncScheduler` from APScheduler.
4. Registers a `CronTrigger` built from the cron expression.
5. Starts the scheduler in the background.

Each scheduled invocation calls `ProjectRuntime.execute()` with the
configured payload, which compiles and runs the pipeline graph.

```python
# Equivalent to what the runtime does internally:
from apscheduler import AsyncScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncScheduler()
trigger = CronTrigger.from_crontab("0 9 * * 1-5", timezone="America/New_York")
await scheduler.add_schedule(my_pipeline_fn, trigger)
await scheduler.start_in_background()
```

---

## Studio UI Configuration

In the Studio canvas:

1. Drag an **Input** node from the palette.
2. Select it and open the config panel on the right.
3. Set **Trigger Type** to `schedule`.
4. Enter the **Cron Expression** (e.g., `*/5 * * * *`).
5. Set the **Timezone** (defaults to `UTC`).
6. Optionally enter a **Payload** as JSON.
7. Click the **Play** button in the top bar to start the runtime.

The runtime status indicator in the top bar shows whether the scheduler
is active. Use the **Stop** button to halt scheduled runs.

---

## Monitoring Scheduled Runs

Each scheduled execution is recorded in the execution history:

```bash
curl http://localhost:8470/api/projects/my-project/runtime/executions
```

You can also check that the scheduler is active:

```bash
curl http://localhost:8470/api/projects/my-project/runtime/status
# {"project": "my-project", "status": "running", "trigger_type": "schedule",
#  "consumers": 0, "scheduler_active": true}
```

---

## Troubleshooting

| Issue | Solution |
|---|---|
| "apscheduler not installed" warning | Install with `pip install "fireflyframework-genai[studio]"` |
| Schedule not firing | Check that the runtime is started and `scheduler_active: true` |
| Wrong time | Verify the timezone setting matches your expectation |
| Pipeline errors on scheduled run | Check the console tab or execution history for error details |

---

*See also: [Input/Output Nodes](input-output-nodes.md) for all trigger
types, [Project API](project-api.md) for runtime management endpoints.*
