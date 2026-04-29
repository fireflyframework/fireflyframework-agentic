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

"""Tests for lab datasets."""

from __future__ import annotations

from fireflyframework_agentic.lab.dataset import EvalCase, EvalDataset


class TestEvalDataset:
    def test_create_and_add(self):
        ds = EvalDataset()
        ds.add(EvalCase(input="hello", expected_output="hi"))
        ds.add(EvalCase(input="bye", expected_output="goodbye"))
        assert len(ds) == 2

    def test_cases_access(self):
        ds = EvalDataset([EvalCase(input="x", expected_output="y")])
        assert ds.cases[0].input == "x"
        assert ds.cases[0].expected_output == "y"
