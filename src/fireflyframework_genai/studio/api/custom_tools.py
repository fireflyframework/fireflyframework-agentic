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

"""REST API endpoints for managing custom tools in Firefly Agentic Studio.

Provides CRUD operations so the Studio frontend can create, list, update,
and delete user-defined tools (Python, webhook, and API types).  Also
includes a pre-built connector catalog for common platforms.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException  # type: ignore[import-not-found]
from pydantic import BaseModel  # type: ignore[import-not-found]

from fireflyframework_genai.studio.custom_tools import (
    CustomToolDefinition,
    CustomToolManager,
    ToolParameter,
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ToolParameterModel(BaseModel):
    """A single parameter for a custom tool."""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    default: Any = None


class SaveToolRequest(BaseModel):
    """Body for creating or updating a custom tool."""

    name: str
    description: str = ""
    tool_type: str = "webhook"
    tags: list[str] = []
    parameters: list[ToolParameterModel] = []

    # Python tool fields
    module_path: str = ""
    python_code: str = ""  # Inline Python code (saved as .py file)

    # Webhook tool fields
    webhook_url: str = ""
    webhook_method: str = "POST"
    webhook_headers: dict[str, str] = {}

    # API tool fields
    api_base_url: str = ""
    api_path: str = ""
    api_method: str = "GET"
    api_auth_type: str = ""
    api_auth_value: str = ""
    api_headers: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Pre-built connector catalog
# ---------------------------------------------------------------------------

_CONNECTOR_CATALOG: list[dict[str, Any]] = [
    {
        "id": "slack",
        "name": "Slack",
        "category": "messaging",
        "description": "Send messages to Slack channels via the Slack Web API. Requires a Slack Bot Token (configure in Tool Credentials).",
        "icon": "message-square",
        "requires_credential": "slack_bot_token",
        "setup_guide": (
            "1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App**\n"
            "2. Choose **From scratch**, name it, and select your workspace\n"
            "3. Under **OAuth & Permissions**, add the `chat:write` scope\n"
            "4. Click **Install to Workspace** and authorize\n"
            "5. Copy the **Bot User OAuth Token** (starts with `xoxb-`)\n"
            "6. Paste it in **Tool Credentials > Slack Bot Token** above"
        ),
        "verify_url": "https://slack.com/api/auth.test",
        "verify_method": "bearer",
        "definition": {
            "name": "slack_send_message",
            "description": "Send a message to a Slack channel. Pass 'channel' (channel ID or name) and 'text' (message content).",
            "tool_type": "api",
            "tags": ["messaging", "slack", "notifications"],
            "api_base_url": "https://slack.com",
            "api_path": "/api/chat.postMessage",
            "api_method": "POST",
            "api_auth_type": "bearer",
            "api_auth_value": "__SLACK_BOT_TOKEN__",
        },
    },
    {
        "id": "telegram",
        "name": "Telegram",
        "category": "messaging",
        "description": "Send messages via the Telegram Bot API. Requires a Telegram Bot Token (configure in Tool Credentials).",
        "icon": "send",
        "requires_credential": "telegram_bot_token",
        "setup_guide": (
            "1. Open Telegram and message [@BotFather](https://t.me/BotFather)\n"
            "2. Send `/newbot` and follow the prompts to name your bot\n"
            "3. BotFather will give you an **HTTP API token**\n"
            "4. Copy the token and paste it in **Tool Credentials > Telegram Bot Token** above"
        ),
        "verify_url": "https://api.telegram.org/bot{token}/getMe",
        "verify_method": "url_token",
        "definition": {
            "name": "telegram_send_message",
            "description": "Send a message via Telegram. Pass 'chat_id' and 'text'.",
            "tool_type": "api",
            "tags": ["messaging", "telegram", "notifications"],
            "api_base_url": "https://api.telegram.org",
            "api_path": "/bot__TELEGRAM_BOT_TOKEN__/sendMessage",
            "api_method": "POST",
            "api_auth_type": "none",
        },
    },
    {
        "id": "discord",
        "name": "Discord",
        "category": "messaging",
        "description": "Send messages to Discord channels via incoming webhooks. Provide your Discord webhook URL during installation.",
        "icon": "hash",
        "requires_credential": None,
        "setup_guide": (
            "1. Open Discord and go to **Server Settings > Integrations**\n"
            "2. Click **Webhooks > New Webhook**\n"
            "3. Name the webhook and select the target channel\n"
            "4. Click **Copy Webhook URL**\n"
            "5. Paste it when prompted during installation below"
        ),
        "verify_method": "head",
        "definition": {
            "name": "discord_webhook",
            "description": "Send a message to a Discord channel via webhook. Pass 'content' (message text).",
            "tool_type": "webhook",
            "tags": ["messaging", "discord", "notifications"],
            "webhook_url": "",
            "webhook_method": "POST",
        },
    },
    {
        "id": "teams",
        "name": "Microsoft Teams",
        "category": "messaging",
        "description": "Send messages to Microsoft Teams channels via incoming webhooks. Provide your Teams webhook URL during installation.",
        "icon": "users",
        "requires_credential": None,
        "setup_guide": (
            "1. In Teams, go to the channel and click **... > Connectors**\n"
            "2. Find **Incoming Webhook** and click **Configure**\n"
            "3. Name the webhook and optionally upload an image\n"
            "4. Click **Create** and copy the webhook URL\n"
            "5. Paste it when prompted during installation below"
        ),
        "verify_method": "head",
        "definition": {
            "name": "teams_webhook",
            "description": "Send a message to a Microsoft Teams channel via incoming webhook. Pass 'text' (message content).",
            "tool_type": "webhook",
            "tags": ["messaging", "teams", "notifications"],
            "webhook_url": "",
            "webhook_method": "POST",
        },
    },
    {
        "id": "github_issues",
        "name": "GitHub Issues",
        "category": "developer",
        "description": "Create GitHub issues programmatically. Requires a GitHub Personal Access Token.",
        "icon": "git-pull-request",
        "requires_credential": None,
        "setup_guide": (
            "1. Go to [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens)\n"
            "2. Click **Generate new token (classic)**\n"
            "3. Select the `repo` scope (for private repos) or `public_repo` (for public only)\n"
            "4. Generate and copy the token\n"
            "5. After installing, edit the tool and paste the token as the Bearer auth value\n"
            "6. Update the API path to `/repos/YOUR_ORG/YOUR_REPO/issues`"
        ),
        "verify_url": "https://api.github.com/user",
        "verify_method": "bearer",
        "definition": {
            "name": "github_create_issue",
            "description": "Create an issue on a GitHub repository. Pass 'title', 'body', and configure the repo in the API path.",
            "tool_type": "api",
            "tags": ["developer", "github", "issues"],
            "api_base_url": "https://api.github.com",
            "api_path": "/repos/OWNER/REPO/issues",
            "api_method": "POST",
            "api_auth_type": "bearer",
            "api_auth_value": "",
        },
    },
    {
        "id": "sendgrid",
        "name": "SendGrid Email",
        "category": "email",
        "description": "Send transactional emails via the SendGrid API. Requires a SendGrid API Key.",
        "icon": "mail",
        "requires_credential": None,
        "setup_guide": (
            "1. Sign in to [SendGrid](https://app.sendgrid.com/)\n"
            "2. Go to **Settings > API Keys > Create API Key**\n"
            "3. Give it a name and select **Restricted Access** with Mail Send permissions\n"
            "4. Copy the generated API key\n"
            "5. After installing, edit the tool and paste the key as the Bearer auth value"
        ),
        "verify_url": "https://api.sendgrid.com/v3/scopes",
        "verify_method": "bearer",
        "definition": {
            "name": "sendgrid_send_email",
            "description": "Send an email via SendGrid. Pass 'to' (email), 'subject', and 'content' (body text).",
            "tool_type": "api",
            "tags": ["email", "sendgrid", "notifications"],
            "api_base_url": "https://api.sendgrid.com",
            "api_path": "/v3/mail/send",
            "api_method": "POST",
            "api_auth_type": "bearer",
            "api_auth_value": "",
        },
    },
    {
        "id": "webhook_generic",
        "name": "Generic Webhook",
        "category": "integration",
        "description": "Call any HTTP endpoint as a tool. Configure the URL and method.",
        "icon": "webhook",
        "requires_credential": None,
        "setup_guide": (
            "1. Obtain the webhook URL from your target service\n"
            "2. Provide the URL during installation\n"
            "3. The default method is POST; edit the tool after install to change it"
        ),
        "verify_method": "head",
        "definition": {
            "name": "custom_webhook",
            "description": "Call a custom HTTP webhook endpoint.",
            "tool_type": "webhook",
            "tags": ["integration", "webhook"],
            "webhook_url": "",
            "webhook_method": "POST",
        },
    },
    {
        "id": "rest_api_generic",
        "name": "Generic REST API",
        "category": "integration",
        "description": "Call any REST API with configurable auth. Supports Bearer tokens, API keys, and no-auth.",
        "icon": "globe",
        "requires_credential": None,
        "setup_guide": (
            "1. Install this connector, then edit it to configure:\n"
            "2. Set the **Base URL** (e.g. `https://api.example.com`)\n"
            "3. Set the **Path** (e.g. `/v1/resource`)\n"
            "4. Choose the **Auth Type** and provide credentials if needed"
        ),
        "definition": {
            "name": "custom_rest_api",
            "description": "Call a custom REST API endpoint.",
            "tool_type": "api",
            "tags": ["integration", "api"],
            "api_base_url": "",
            "api_path": "",
            "api_method": "GET",
            "api_auth_type": "none",
        },
    },
]


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_custom_tools_router(manager: CustomToolManager) -> APIRouter:
    """Create an :class:`APIRouter` for custom tool management.

    Endpoints
    ---------
    ``GET /api/custom-tools``
        List all custom tools.
    ``GET /api/custom-tools/catalog``
        List pre-built connectors.
    ``POST /api/custom-tools/catalog/{connector_id}/install``
        Install a pre-built connector.
    ``GET /api/custom-tools/{name}``
        Get a single custom tool definition.
    ``POST /api/custom-tools``
        Create or update a custom tool.
    ``DELETE /api/custom-tools/{name}``
        Delete a custom tool.
    ``POST /api/custom-tools/{name}/test``
        Test a custom tool.
    ``POST /api/custom-tools/{name}/register``
        Register a tool in the runtime registry.
    """
    router = APIRouter(prefix="/api/custom-tools", tags=["custom-tools"])

    @router.get("")
    async def list_tools() -> list[dict[str, Any]]:
        tools = manager.list_all()
        return [asdict(t) for t in tools]

    # ---- Static path routes MUST come before /{name} catch-all ----

    @router.get("/catalog")
    async def list_connectors() -> list[dict[str, Any]]:
        """Return the pre-built connector catalog with setup guides."""
        installed_names = {t.name for t in manager.list_all()}
        catalog = []
        for connector in _CONNECTOR_CATALOG:
            entry = {
                "id": connector["id"],
                "name": connector["name"],
                "category": connector["category"],
                "description": connector["description"],
                "icon": connector["icon"],
                "requires_credential": connector["requires_credential"],
                "installed": connector["definition"]["name"] in installed_names,
                "tool_name": connector["definition"]["name"],
                "setup_guide": connector.get("setup_guide", ""),
            }
            catalog.append(entry)
        return catalog

    @router.post("/catalog/{connector_id}/install")
    async def install_connector(connector_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Install a pre-built connector as a custom tool."""
        connector = next(
            (c for c in _CONNECTOR_CATALOG if c["id"] == connector_id), None
        )
        if connector is None:
            raise HTTPException(status_code=404, detail=f"Connector '{connector_id}' not found")

        defn_data = dict(connector["definition"])

        # Resolve credential placeholders from settings
        if connector.get("requires_credential"):
            from fireflyframework_genai.studio.settings import load_settings
            settings = load_settings()
            cred_field = connector["requires_credential"]
            cred_val = getattr(settings.tool_credentials, cred_field, None)
            if cred_val is not None:
                secret = cred_val.get_secret_value()
                for key, val in defn_data.items():
                    if isinstance(val, str):
                        placeholder = f"__{cred_field.upper()}__"
                        defn_data[key] = val.replace(placeholder, secret)

        # Apply user overrides (e.g., webhook_url for Discord/Teams)
        if body:
            for key in ("webhook_url", "api_base_url", "api_path", "api_auth_value", "name"):
                if key in body and body[key]:
                    defn_data[key] = body[key]

        params = [ToolParameter(**p) for p in defn_data.pop("parameters", [])]
        definition = CustomToolDefinition(**defn_data, parameters=params)
        manager.save(definition)

        # Register at runtime
        try:
            tool = manager.create_runtime_tool(definition)
            from fireflyframework_genai.tools.registry import tool_registry
            tool_registry.register(tool)
        except Exception:
            pass

        return {"status": "installed", "tool_name": f"custom:{definition.name}"}

    @router.post("/catalog/{connector_id}/verify")
    async def verify_connector(connector_id: str) -> dict[str, Any]:
        """Verify a connector's credentials by making a test API call."""
        import httpx

        connector = next(
            (c for c in _CONNECTOR_CATALOG if c["id"] == connector_id), None
        )
        if connector is None:
            raise HTTPException(status_code=404, detail=f"Connector '{connector_id}' not found")

        verify_method = connector.get("verify_method", "")
        if not verify_method:
            return {"status": "ok", "message": "No verification available for this connector."}

        # Resolve credential if needed
        token = ""
        if connector.get("requires_credential"):
            from fireflyframework_genai.studio.settings import load_settings
            settings = load_settings()
            cred_field = connector["requires_credential"]
            cred_val = getattr(settings.tool_credentials, cred_field, None)
            if cred_val is None:
                return {"status": "error", "message": f"Missing credential: {cred_field}. Configure it in Tool Credentials."}
            token = cred_val.get_secret_value()
            if not token:
                return {"status": "error", "message": f"Credential '{cred_field}' is empty. Configure it in Tool Credentials."}

        # For webhook-based connectors (Discord, Teams), check the installed tool URL
        if verify_method == "head":
            installed_tools = manager.list_all()
            tool_name = connector["definition"]["name"]
            tool_def = next((t for t in installed_tools if t.name == tool_name), None)
            if tool_def is None:
                return {"status": "error", "message": "Connector not installed yet. Install it first."}
            url = tool_def.webhook_url or tool_def.api_base_url
            if not url:
                return {"status": "error", "message": "No URL configured for this connector."}
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.head(url)
                    if resp.status_code < 400:
                        return {"status": "ok", "message": f"Webhook reachable (HTTP {resp.status_code})."}
                    return {"status": "error", "message": f"Webhook returned HTTP {resp.status_code}."}
            except httpx.RequestError as exc:
                return {"status": "error", "message": f"Connection failed: {exc}"}

        # Bearer token verification
        if verify_method == "bearer":
            verify_url = connector.get("verify_url", "")
            if not verify_url or not token:
                return {"status": "error", "message": "Missing verify URL or token."}
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        verify_url,
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    if resp.status_code == 200:
                        return {"status": "ok", "message": "Credentials verified successfully."}
                    return {"status": "error", "message": f"Verification failed (HTTP {resp.status_code})."}
            except httpx.RequestError as exc:
                return {"status": "error", "message": f"Connection failed: {exc}"}

        # URL-embedded token (Telegram style)
        if verify_method == "url_token":
            verify_url = connector.get("verify_url", "").replace("{token}", token)
            if not verify_url:
                return {"status": "error", "message": "Missing verify URL."}
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(verify_url)
                    if resp.status_code == 200:
                        return {"status": "ok", "message": "Bot token verified successfully."}
                    return {"status": "error", "message": f"Verification failed (HTTP {resp.status_code})."}
            except httpx.RequestError as exc:
                return {"status": "error", "message": f"Connection failed: {exc}"}

        return {"status": "ok", "message": "Verification not implemented for this connector type."}

    # ---- Dynamic path routes ----

    @router.get("/{name}")
    async def get_tool(name: str) -> dict[str, Any]:
        try:
            tool = manager.load(name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        result = asdict(tool)
        # Include inline Python code if this is a Python tool
        if tool.tool_type == "python" and tool.module_path:
            from pathlib import Path
            py_path = Path(tool.module_path)
            if py_path.is_file():
                try:
                    result["python_code"] = py_path.read_text(encoding="utf-8")
                except Exception:
                    result["python_code"] = ""
            else:
                result["python_code"] = ""
        return result

    @router.post("")
    async def save_tool(body: SaveToolRequest) -> dict[str, Any]:
        from pathlib import Path

        module_path = body.module_path

        # If inline Python code is provided, write it to a .py file
        if body.tool_type == "python" and body.python_code.strip():
            tools_dir = Path.home() / ".firefly-studio" / "custom_tools"
            tools_dir.mkdir(parents=True, exist_ok=True)
            py_path = tools_dir / f"{body.name}.py"
            py_path.write_text(body.python_code, encoding="utf-8")
            module_path = str(py_path)

        definition = CustomToolDefinition(
            name=body.name,
            description=body.description,
            tool_type=body.tool_type,
            tags=body.tags,
            parameters=[
                ToolParameter(
                    name=p.name,
                    type=p.type,
                    description=p.description,
                    required=p.required,
                    default=p.default,
                )
                for p in body.parameters
            ],
            module_path=module_path,
            webhook_url=body.webhook_url,
            webhook_method=body.webhook_method,
            webhook_headers=body.webhook_headers,
            api_base_url=body.api_base_url,
            api_path=body.api_path,
            api_method=body.api_method,
            api_auth_type=body.api_auth_type,
            api_auth_value=body.api_auth_value,
            api_headers=body.api_headers,
        )

        # Try to preserve created_at from existing definition
        try:
            existing = manager.load(body.name)
            definition.created_at = existing.created_at
        except FileNotFoundError:
            pass

        manager.save(definition)

        # Auto-register if possible
        try:
            tool = manager.create_runtime_tool(definition)
            from fireflyframework_genai.tools.registry import tool_registry

            tool_registry.register(tool)
        except Exception:
            pass  # Registration may fail for incomplete definitions

        return asdict(definition)

    @router.delete("/{name}")
    async def delete_tool(name: str) -> dict[str, str]:
        try:
            manager.delete(name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"status": "deleted"}

    @router.post("/{name}/test")
    async def test_tool(name: str) -> dict[str, Any]:
        """Send a test request to a custom tool and return the result."""
        try:
            definition = manager.load(name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            tool = manager.create_runtime_tool(definition)
            handler = tool.pydantic_handler()
            import asyncio
            import time

            start = time.monotonic()
            result = await asyncio.wait_for(handler(), timeout=15.0)
            elapsed = round(time.monotonic() - start, 2)
            return {
                "status": "success",
                "tool_name": tool.name,
                "response_time": elapsed,
                "result": str(result)[:1000],
            }
        except asyncio.TimeoutError:
            return {"status": "timeout", "tool_name": f"custom:{name}", "error": "Request timed out after 15s"}
        except Exception as exc:
            return {"status": "error", "tool_name": f"custom:{name}", "error": str(exc)}

    @router.post("/{name}/register")
    async def register_tool(name: str) -> dict[str, str]:
        try:
            definition = manager.load(name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            tool = manager.create_runtime_tool(definition)
            from fireflyframework_genai.tools.registry import tool_registry

            tool_registry.register(tool)
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to register tool: {exc}",
            ) from exc

        return {"status": "registered", "tool_name": tool.name}

    return router
