# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""``firefly-mcp-http`` CLI — run the MCP server over Streamable HTTP.

Used by network deployments (e.g. Azure Container Apps). Auth is enforced
at the ingress layer (zero-trust per issue #98); this process trusts the
JWT validation already done upstream.
"""

from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI

from fireflyframework_agentic.exposure.mcp.server import create_mcp_app


def build_app() -> FastAPI:
    mcp_app = create_mcp_app().http_app(path="/")
    app = FastAPI(title="firefly-mcp", version="0.1.0", lifespan=mcp_app.lifespan)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.mount("/mcp", mcp_app)
    return app


def main() -> None:
    """Entry point registered as ``firefly-mcp-http`` in ``[project.scripts]``."""
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(build_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
