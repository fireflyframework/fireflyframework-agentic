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

"""Tests for the firefly-ingest CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fireflyframework_agentic.ingestion.cli import main


def _write_basic_config(tmp_path: Path) -> Path:
    schema = {
        "tables": [
            {
                "name": "customers",
                "columns": [
                    {"name": "id", "type": "integer", "primary_key": True, "nullable": False},
                ],
            }
        ]
    }
    (tmp_path / "schema.yaml").write_text(yaml.safe_dump(schema))
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "noop.py").write_text(
        "import re\n"
        "from collections.abc import Iterator\n"
        "PATTERN = re.compile(r'noop')\n"
        "def map(file, schema): yield from []\n"
    )
    cfg = {
        "source": {
            "type": "sharepoint",
            "config": {
                "tenant_id_secret": "T",
                "client_id_secret": "C",
                "client_secret_secret": "S",
                "drive_id": "drive-1",
            },
        },
        "mapper": {"type": "script", "scripts_dir": str(tmp_path / "scripts")},
        "sink": {"type": "sqlite", "mode": "in-memory"},
        "schema": str(tmp_path / "schema.yaml"),
        "state": {
            "cache_dir": str(tmp_path / "cache"),
            "delta_file": str(tmp_path / "delta.json"),
        },
        "secrets": {"type": "env"},
    }
    p = tmp_path / "ingestion.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


def test_status_subcommand_reports_layout(tmp_path: Path, capsys):
    config_path = _write_basic_config(tmp_path)
    rc = main(["status", "--config", str(config_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "scripts_dir" in out
    assert "1 mapping scripts" in out
    assert "delta_file" in out


def test_help_returns_zero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0


def test_run_with_missing_config_fails(tmp_path: Path, capsys):
    rc = main(["run", "--config", str(tmp_path / "missing.yaml")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "could not read" in err
