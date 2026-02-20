"""PyInstaller hidden-imports hook for fireflyframework-genai.

Ensures that all runtime-discovered sub-packages and optional
dependencies are bundled into the frozen executable.
"""

hiddenimports = [
    # Studio server
    "fireflyframework_genai.studio",
    "fireflyframework_genai.studio.cli",
    "fireflyframework_genai.studio.server",
    "fireflyframework_genai.studio.config",
    "fireflyframework_genai.studio.projects",
    "fireflyframework_genai.studio.api.assistant",
    "fireflyframework_genai.studio.api.checkpoints",
    "fireflyframework_genai.studio.api.codegen",
    "fireflyframework_genai.studio.api.execution",
    "fireflyframework_genai.studio.api.files",
    "fireflyframework_genai.studio.api.monitoring",
    "fireflyframework_genai.studio.api.projects",
    "fireflyframework_genai.studio.api.registry",
    "fireflyframework_genai.studio.codegen.generator",
    "fireflyframework_genai.studio.codegen.models",
    "fireflyframework_genai.studio.execution.compiler",
    "fireflyframework_genai.studio.execution.runner",
    "fireflyframework_genai.studio.execution.checkpoint",
    # Pipeline engine
    "fireflyframework_genai.pipeline.builder",
    "fireflyframework_genai.pipeline.context",
    "fireflyframework_genai.pipeline.dag",
    "fireflyframework_genai.pipeline.engine",
    "fireflyframework_genai.pipeline.steps",
    # Agent framework
    "fireflyframework_genai.agents.base",
    "fireflyframework_genai.agents.registry",
    "fireflyframework_genai.agents.context",
    "fireflyframework_genai.agents.middleware",
    # Tools & reasoning
    "fireflyframework_genai.tools.registry",
    "fireflyframework_genai.reasoning.registry",
    # Config
    "fireflyframework_genai.config",
    # Web server dependencies
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "fastapi",
    "starlette",
    "starlette.staticfiles",
    "pydantic",
    "pydantic_settings",
    "httpx",
]
