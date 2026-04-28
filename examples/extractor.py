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

"""Extractor template agent example.

Demonstrates:
- ``create_extractor_agent`` with a custom Pydantic output model.
- Structured data extraction from unstructured text.

Usage::

    uv run python examples/extractor.py
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from pydantic import BaseModel

from fireflyframework_agentic.agents.templates import create_extractor_agent

load_dotenv()

MODEL = os.environ["MODEL"]


class ContactInfo(BaseModel):
    """Structured contact information extracted from text."""

    name: str
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    role: str | None = None


TEXT = """\
Hi, I'm Sarah Chen, VP of Engineering at Nexus Robotics. You can reach me at
sarah.chen@nexusrobotics.io or call +1-415-555-0198. Looking forward to
discussing the partnership proposal.
"""


async def main() -> None:

    agent = create_extractor_agent(
        ContactInfo,
        model=MODEL,
        field_descriptions={
            "name": "Full name of the person",
            "email": "Email address",
            "phone": "Phone number in any format",
            "company": "Company or organisation name",
            "role": "Job title or role",
        },
    )

    print("=== Contact Extractor ===\n")
    print(f"Input:\n{TEXT}")
    result = await agent.run(TEXT)
    contact: ContactInfo = result.output
    print(f"Name   : {contact.name}")
    print(f"Email  : {contact.email}")
    print(f"Phone  : {contact.phone}")
    print(f"Company: {contact.company}")
    print(f"Role   : {contact.role}")


if __name__ == "__main__":
    asyncio.run(main())
