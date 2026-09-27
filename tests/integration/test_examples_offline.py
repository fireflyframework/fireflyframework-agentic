"""Executable examples must import safely and produce real local workflow outputs."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from examples import pipeline_state


@pytest.mark.parametrize(
    ("text", "expected"),
    [("GREAT! Wonderful.", "positive"), ("Awful, terrible!", "negative"), ("Great but awful.", "neutral")],
)
async def test_state_example_counts_punctuated_sentiment_words(text: str, expected: str) -> None:
    result = await pipeline_state.classify_sentiment(pipeline_state.SentimentState(text=text))
    assert result["sentiment"] == expected


async def test_state_map_worker_computes_document_statistics() -> None:
    result = await pipeline_state.process_item(pipeline_state.MapReduceState(item="Alpha beta beta."))
    assert result["processed"] == [{"text": "Alpha beta beta.", "words": 3, "unique_words": 2, "characters": 16}]


async def test_state_map_rejects_an_empty_workload() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        await pipeline_state.plan(pipeline_state.MapReduceState(items=[" ", ""]))


async def test_state_release_creates_and_verifies_real_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.html").write_text("<h1>Release</h1>")
    state = pipeline_state.HitlState(
        target_env="staging", source_dir=str(source), release_dir=str(tmp_path / "releases")
    )
    built = await pipeline_state.build_artifact(state)
    artifact = Path(built["artifact"])
    assert artifact.is_file()
    with tarfile.open(artifact) as archive:
        content = archive.extractfile("index.html")
        assert content is not None and content.read() == b"<h1>Release</h1>"
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert built["artifact_sha256"] == digest
    deployed = await pipeline_state.deploy_artifact(state.model_copy(update=built))
    destination = Path(deployed["deployed_to"])
    assert destination.is_relative_to(tmp_path / "releases" / "staging")
    assert destination.read_bytes() == artifact.read_bytes()


async def test_state_release_refuses_a_changed_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.tar.gz"
    artifact.write_bytes(b"changed after approval")
    state = pipeline_state.HitlState(
        target_env="staging",
        source_dir=str(tmp_path),
        release_dir=str(tmp_path / "releases"),
        artifact=str(artifact),
        artifact_sha256=hashlib.sha256(b"approved bytes").hexdigest(),
    )
    with pytest.raises(ValueError, match="digest"):
        await pipeline_state.deploy_artifact(state)
    assert not (tmp_path / "releases").exists()


def test_examples_import_without_keys_model_selection_or_network(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"MODEL", "MODEL_CHEAP", "MODEL_MED", "MODEL_EXPENSIVE"}
        and not key.endswith(("API_KEY", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY", "SESSION_TOKEN"))
        and not key.startswith("FIREFLY_AGENTIC_")
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib
from pathlib import Path
import socket
import sys
import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: False
def no_network(*args, **kwargs):
    raise AssertionError('An example contacted the network while importing')
socket.socket.connect = no_network
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "examples"))
for path in sorted((root / 'examples').glob('*.py')):
    if path.name != '__init__.py':
        importlib.import_module(f'examples.{path.stem}')
print('All top-level examples imported')
""",
            str(root),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "All top-level examples imported" in result.stdout


async def test_quota_example_enforces_budget_and_rate_limits_without_a_model() -> None:
    from examples import quota_management

    assert await quota_management.demonstrate_budget_enforcement() == pytest.approx(0.02)
    assert await quota_management.demonstrate_rate_limiting() == 3
    assert await quota_management.demonstrate_adaptive_backoff() == [0.01, 0.02, 0.04]


async def test_batch_pipeline_uses_all_loaded_documents(monkeypatch, capsys) -> None:
    from pydantic_ai.models.test import TestModel

    from examples import batch_processing
    from fireflyframework_agentic.agents import FireflyAgent

    def local_agent(name, **kwargs):
        kwargs["model"] = TestModel(custom_output_text="technology")
        return FireflyAgent(name, **kwargs)

    monkeypatch.setattr(batch_processing, "FireflyAgent", local_agent)
    await batch_processing.demo_batch_in_pipeline()
    assert "Documents loaded: 5" in capsys.readouterr().out


def test_cache_example_converts_million_token_prices_correctly() -> None:
    from examples.prompt_caching import illustrative_costs

    assert illustrative_costs() == pytest.approx({"without_cache": 0.30, "with_cache": 0.0645, "savings": 0.2355})


async def test_http_example_executes_all_requests_against_a_local_echo_service(monkeypatch) -> None:
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    from examples import http_connection_pooling

    observed = []
    connections = []

    class EchoServer(ThreadingHTTPServer):
        daemon_threads = False

        def get_request(self):
            connection, address = super().get_request()
            connections.append(connection)
            return connection, address

    class EchoHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self.reply()

        def do_POST(self):
            self.reply()

        def reply(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            observed.append((self.command, self.path, body, self.headers.get("X-Example")))
            data = json.dumps({"method": self.command, "body": body.decode()}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            return

    server = EchoServer(("127.0.0.1", 0), EchoHandler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    monkeypatch.setattr(http_connection_pooling, "BASE_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        await http_connection_pooling.main()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert not thread.is_alive()
    assert server.socket.fileno() == -1
    assert connections and all(connection.fileno() == -1 for connection in connections)
    assert len(observed) == 22
    assert ("POST", "/post", b'{"value": 123}', None) in observed
    assert any(entry[3] == "firefly-pooling" for entry in observed)


async def test_idp_templates_and_local_tools_use_public_framework_apis() -> None:
    from examples import idp_tools

    assert idp_tools.classification_prompt.render(max_chars=12, document_text="Example text").user.endswith("---")
    assert "certificate" in idp_tools.extraction_prompt.render(doc_type="certificate", document_text="Acme").user
    assert await idp_tools.date_normalizer.execute(date_string="January 15th, 2026") == "2026-01-15"
    headings = await idp_tools.section_finder.execute(
        text="[PAGE 2]\nARTICLE I. NAME\nText\n[PAGE 4]\nSECTION 2. BOARD"
    )
    assert "ARTICLE I. NAME (page 2)" in headings
    assert "SECTION 2. BOARD (page 4)" in headings


@pytest.mark.parametrize(
    ("module_name", "expected"),
    [
        ("extractor", "Contact Extractor"),
        ("conversational_memory", "Agent:"),
        ("summarizer", "Summarizer"),
        ("delegation_strategies", "Chosen (cheapest survivor)"),
        ("reasoning_cot", "Answer:"),
        ("reasoning_react", "Answer:"),
        ("reasoning_memory", "Answer:"),
        ("reasoning_reflexion", "Final answer:"),
        ("reasoning_pipeline", "Final output:"),
        ("reasoning_plan", "Results (1 steps)"),
        ("reasoning_goal", "Task Results (1)"),
        ("reasoning_tot", "Best approach:"),
        ("rubric_reviewer", "Satisfied: True"),
    ],
)
async def test_domain_examples_with_explicit_provider_fixtures(module_name, expected, monkeypatch, capsys) -> None:
    import importlib

    from pydantic_ai.models.test import TestModel

    class DomainFixtureModel(TestModel):
        async def request(self, messages, model_settings, model_request_parameters):
            args = None
            if model_request_parameters.output_tools:
                fields = model_request_parameters.output_tools[0].parameters_json_schema.get("properties", {})
                if "is_final" in fields:
                    args = {
                        "content": "Fixture completed.",
                        "is_final": True,
                        "final_answer": "Verified fixture answer",
                    }
                elif "is_satisfactory" in fields:
                    args = {"is_satisfactory": True}
                elif "steps" in fields:
                    args = {
                        "goal": "Fixture goal",
                        "steps": [{"id": "one", "description": "Complete the fixture task"}],
                    }
                elif "phases" in fields:
                    args = {"goal": "Fixture goal", "phases": [{"name": "one", "tasks": ["Complete the fixture task"]}]}
                elif "branches" in fields:
                    args = {"branches": ["Fixture approach A", "Fixture approach B"]}
                fixture = TestModel(call_tools=[], custom_output_args=args)
            else:
                text = "0" if module_name == "delegation_strategies" else "MET: 1\nMET: 2\nMET: 3\nSATISFIED"
                fixture = TestModel(call_tools=[], custom_output_text=text)
            return await fixture.request(messages, model_settings, model_request_parameters)

    module = importlib.import_module(f"examples.{module_name}")
    model = DomainFixtureModel(call_tools=[])
    for variable in ("MODEL", "MODEL_CHEAP", "MODEL_MED", "MODEL_EXPENSIVE"):
        if hasattr(module, variable):
            monkeypatch.setattr(module, variable, model)
    monkeypatch.setattr(sys, "argv", [module_name])
    await module.main()
    assert expected in capsys.readouterr().out


async def test_idp_pipeline_runs_all_stages_with_pdf_and_model_boundary_fixtures(monkeypatch) -> None:
    import importlib
    import json

    import httpx
    from pydantic_ai.models.test import TestModel

    from fireflyframework_agentic.memory import MemoryManager
    from fireflyframework_agentic.pipeline.context import PipelineContext
    from fireflyframework_agentic.tools.cached import CachedTool

    # A complete one-page PDF, served through the real downloader's HTTP boundary.
    lines = ["BYLAWS", "ARTICLE I. NAME", "Example Inc is incorporated in Delaware."]
    lines += ["The board meets annually and records the votes of all directors."] * 6
    commands = "BT /F1 12 Tf 50 750 Td " + " 0 -20 Td ".join(f"({line}) Tj" for line in lines) + " ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(commands)} >>\nstream\n{commands}\nendstream".encode(),
    ]
    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(pdf)
    pdf += b"xref\n0 6\n0000000000 65535 f \n"
    pdf += b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets[1:])
    pdf += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()

    requests = []

    def serve(request):
        requests.append(request)
        return httpx.Response(200, content=pdf, headers={"Content-Type": "application/pdf"})

    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(serve), **kwargs)
    )
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples"))
    module = importlib.import_module("examples.idp_pipeline")

    class IDPFixtureModel(TestModel):
        async def request(self, messages, model_settings, model_request_parameters):
            if model_request_parameters.output_tools:
                properties = model_request_parameters.output_tools[0].parameters_json_schema["properties"]
                if "company_name" in properties:
                    args = {
                        "company_name": "Example Inc",
                        "doc_type": "bylaws",
                        "incorporation_state": "Delaware",
                        "sections": [{"title": "ARTICLE I. NAME", "page_number": 1, "content_summary": "Company name"}],
                    }
                else:
                    args = {"category": "bylaws", "confidence": 0.95, "reasoning": "The page title identifies bylaws."}
                fixture = TestModel(call_tools=[], custom_output_args=args)
            else:
                fixture = TestModel(
                    call_tools=[], custom_output_text=json.dumps([{"title": "Bylaws", "page_start": 1, "page_end": 1}])
                )
            return await fixture.request(messages, model_settings, model_request_parameters)

    memory = MemoryManager()
    monkeypatch.setattr(module, "MODEL", IDPFixtureModel(call_tools=[]))
    monkeypatch.setattr(module, "memory", memory)
    monkeypatch.setattr(module, "_cached_pdf_tool", CachedTool(module.idp_toolkit.tools[0]))
    pipeline = module.build_pipeline()
    result = await pipeline.run(context=PipelineContext(inputs="https://pdf.example/document.pdf", memory=memory))
    assert result.success, result.error
    assert len(requests) == 1
    assert result.completed_nodes == ["ingest", "split", "classify", "extract", "validate", "assemble", "explain"]
    documents = result.final_output["assembled"]["documents"]
    assert len(documents) == 1
    assert documents[0]["extracted_fields"]["company_name"] == "Example Inc"
    assert documents[0]["validation_passed"] is True


@pytest.mark.parametrize(
    "module_name",
    [
        "basic_agent",
        "batch_processing",
        "cached_tool",
        "circuit_breaker",
        "classifier",
        "conversation_export_import",
        "cost_tracking",
        "full_integration",
        "incremental_streaming",
        "llm_eval_example",
        "model_agnostic_agent",
        "observability_usage",
        "pipeline_branching",
        "pipeline_state",
        "prompt_caching",
        "quota_management",
        "router",
        "security_guards",
        "tool_timeout",
    ],
)
def test_example_entrypoints_offline(module_name: str, tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.endswith(("API_KEY", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY", "SESSION_TOKEN"))
        and not key.startswith("FIREFLY_AGENTIC_")
    }
    env.update(
        {
            key: "test"
            for key in ("MODEL", "MODEL_CHEAP", "MODEL_MED", "MODEL_EXPENSIVE", "FIREFLY_AGENTIC_DEFAULT_MODEL")
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import runpy
import socket
import sys
import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: False
def no_network(*args, **kwargs):
    raise AssertionError('Offline entrypoint tried to contact the network')
socket.socket.connect = no_network
root, module = sys.argv[1:]
sys.path[:0] = [root, root + '/examples']
path = root + '/examples/' + module + '.py'
sys.argv = [path]
runpy.run_path(path, run_name='__main__')
""",
            str(root),
            module_name,
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip()


async def test_responses_example_runs_through_the_real_sdk_with_an_http_fixture(monkeypatch, capsys) -> None:
    import httpx2

    from examples import openai_responses
    from fireflyframework_agentic.agents import FireflyAgent
    from tests.integration.test_openai_api_compatibility import _HTTPBoundary, _responses_response, _stream_reply

    boundary = _HTTPBoundary()
    model_name = "gpt-6-luna"
    tool = _responses_response(model_name, tool="multiply")
    tool["output"][0]["arguments"] = '{"a":17,"b":23}'
    structured = _responses_response(model_name, tool="final_result")
    structured["output"][0]["arguments"] = '{"expression":"17 * 23","value":391}'
    boundary.replies = [
        httpx2.Response(200, json=tool),
        httpx2.Response(200, json=_responses_response(model_name, "391")),
        httpx2.Response(200, json=_responses_response(model_name, "17 and 23")),
        httpx2.Response(200, json=structured),
        _stream_reply("responses", model_name),
    ]

    def agent_with_http_fixture(*args, **kwargs):
        assert kwargs["model"] == f"openai-responses:{model_name}"
        kwargs["model"] = boundary.model("responses", model_name)
        return FireflyAgent(*args, **kwargs)

    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    monkeypatch.setenv("OPENAI_MODEL", model_name)
    monkeypatch.setattr(openai_responses, "load_dotenv", lambda: False)
    monkeypatch.setattr(openai_responses, "FireflyAgent", agent_with_http_fixture)
    async with boundary.client:
        await openai_responses.main()
    assert not boundary.replies
    assert len(boundary.requests) == 5
    for index, request in enumerate(boundary.requests):
        assert request.url.path == "/v1/responses"
        assert boundary.body(index)["reasoning"]["effort"] == "low"
        assert boundary.body(index)["store"] is False
    assert any(item.get("output") == "391" for item in boundary.body(1)["input"])
    assert '"value":391' in capsys.readouterr().out
