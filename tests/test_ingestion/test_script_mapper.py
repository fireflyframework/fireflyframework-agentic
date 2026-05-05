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

"""Tests for ScriptMapper using real Python files on disk."""

from datetime import datetime
from pathlib import Path

import pytest

from fireflyframework_agentic.ingestion.adapters.mappers import ScriptMapper
from fireflyframework_agentic.ingestion.domain import (
    ColumnSpec,
    RawFile,
    TableSpec,
    TargetSchema,
)
from fireflyframework_agentic.ingestion.exceptions import (
    MappingScriptError,
    MultipleMappersError,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def scripts_dir() -> Path:
    return FIXTURES_DIR / "scripts"


@pytest.fixture
def schema() -> TargetSchema:
    return TargetSchema(
        tables=[
            TableSpec(
                name="customers",
                columns=[
                    ColumnSpec(name="id", type="integer", primary_key=True, nullable=False),
                    ColumnSpec(name="name", type="string"),
                    ColumnSpec(name="tier", type="string"),
                ],
            ),
            TableSpec(
                name="sales",
                columns=[
                    ColumnSpec(name="id", type="integer", primary_key=True, nullable=False),
                    ColumnSpec(name="customer_id", type="integer", nullable=False),
                    ColumnSpec(name="day", type="date"),
                    ColumnSpec(name="amount", type="float"),
                    ColumnSpec(name="paid", type="boolean"),
                ],
            ),
        ]
    )


def _make_raw(name: str, source_id: str, local_path: Path) -> RawFile:
    return RawFile(
        source_id=source_id,
        name=name,
        fetched_at=datetime(2026, 1, 1),
        local_path=local_path,
    )


def test_loads_scripts_from_directory(scripts_dir: Path):
    mapper = ScriptMapper(scripts_dir)
    assert mapper.script_count == 2


def test_supports_returns_true_for_matching_pattern(scripts_dir: Path, tmp_path: Path):
    mapper = ScriptMapper(scripts_dir)
    f = tmp_path / "customers_q1.csv"
    f.write_text("id,name,tier\n1,A,gold\n")
    raw = _make_raw("customers_q1.csv", "fake:customers_q1.csv", f)
    assert mapper.supports(raw)


def test_supports_returns_false_when_no_pattern_matches(scripts_dir: Path, tmp_path: Path):
    mapper = ScriptMapper(scripts_dir)
    f = tmp_path / "unrelated.txt"
    f.write_text("nope")
    raw = _make_raw("unrelated.txt", "fake:unrelated.txt", f)
    assert not mapper.supports(raw)


def test_map_dispatches_to_matching_script(scripts_dir: Path, schema: TargetSchema, tmp_path: Path):
    mapper = ScriptMapper(scripts_dir)
    f = tmp_path / "customers_q1.csv"
    f.write_text("id,name,tier\n1,Alpha,gold\n2,Beta,silver\n")
    raw = _make_raw("customers_q1.csv", "fake:customers_q1.csv", f)
    records = list(mapper.map(raw, schema))
    assert [r.row["name"] for r in records] == ["Alpha", "Beta"]
    assert all(r.table == "customers" for r in records)


def test_map_raises_when_no_script_matches(scripts_dir: Path, schema: TargetSchema, tmp_path: Path):
    mapper = ScriptMapper(scripts_dir)
    f = tmp_path / "unrelated.txt"
    f.write_text("nope")
    raw = _make_raw("unrelated.txt", "fake:unrelated.txt", f)
    with pytest.raises(MappingScriptError, match="no mapping script matches"):
        list(mapper.map(raw, schema))


def test_loader_raises_when_directory_missing(tmp_path: Path):
    with pytest.raises(MappingScriptError, match="does not exist"):
        ScriptMapper(tmp_path / "missing")


def test_loader_raises_when_script_missing_pattern(tmp_path: Path):
    bad = tmp_path / "scripts"
    bad.mkdir()
    (bad / "bad.py").write_text("def map(f, s): yield None\n")
    with pytest.raises(MappingScriptError, match="PATTERN"):
        ScriptMapper(bad)


def test_loader_raises_when_script_missing_map(tmp_path: Path):
    bad = tmp_path / "scripts"
    bad.mkdir()
    (bad / "bad.py").write_text("import re\nPATTERN = re.compile('.*')\n")
    with pytest.raises(MappingScriptError, match="map"):
        ScriptMapper(bad)


def test_loader_raises_when_script_pattern_invalid_regex(tmp_path: Path):
    bad = tmp_path / "scripts"
    bad.mkdir()
    (bad / "bad.py").write_text("PATTERN = '['  # invalid regex\ndef map(f, s): yield None\n")
    with pytest.raises(MappingScriptError, match="not a valid regex"):
        ScriptMapper(bad)


def test_loader_skips_underscore_prefixed_files(tmp_path: Path):
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "_helpers.py").write_text("PATTERN = '.*'\ndef map(f, s): yield None\n")
    mapper = ScriptMapper(d)
    assert mapper.script_count == 0


def test_map_raises_on_multiple_matches(tmp_path: Path, schema: TargetSchema):
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "a.py").write_text(
        "import re\n"
        "from collections.abc import Iterator\n"
        "from fireflyframework_agentic.ingestion.domain import RawFile, "
        "TargetSchema, TypedRecord\n"
        "PATTERN = re.compile(r'collide')\n"
        "def map(f, s): yield from []\n"
    )
    (d / "b.py").write_text(
        "import re\n"
        "from collections.abc import Iterator\n"
        "from fireflyframework_agentic.ingestion.domain import RawFile, "
        "TargetSchema, TypedRecord\n"
        "PATTERN = re.compile(r'collide')\n"
        "def map(f, s): yield from []\n"
    )
    mapper = ScriptMapper(d)
    f = tmp_path / "collide.csv"
    f.write_text("x")
    raw = _make_raw("collide.csv", "fake:collide.csv", f)
    with pytest.raises(MultipleMappersError):
        list(mapper.map(raw, schema))


def test_pattern_can_be_string(tmp_path: Path, schema: TargetSchema):
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "a.py").write_text(
        "from collections.abc import Iterator\n"
        "from fireflyframework_agentic.ingestion.domain import RawFile, "
        "TargetSchema, TypedRecord\n"
        "PATTERN = r'string-regex.*\\.csv$'\n"
        "def map(f, s): yield from []\n"
    )
    mapper = ScriptMapper(d)
    f = tmp_path / "string-regex-q1.csv"
    f.write_text("x")
    raw = _make_raw("string-regex-q1.csv", "fake:string-regex-q1.csv", f)
    assert mapper.supports(raw)
