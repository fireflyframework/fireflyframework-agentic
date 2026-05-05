import re
from collections.abc import Iterator

from fireflyframework_agentic.ingestion.domain import RawFile, TargetSchema, TypedRecord

PATTERN = re.compile(r"customers.*\.csv$")


def map(file: RawFile, schema: TargetSchema) -> Iterator[TypedRecord]:
    text = file.local_path.read_text()
    lines = text.strip().splitlines()
    headers = lines[0].split(",")
    for row in lines[1:]:
        values = row.split(",")
        record = dict(zip(headers, values, strict=False))
        yield TypedRecord(
            table="customers",
            row={"id": int(record["id"]), "name": record["name"], "tier": record["tier"]},
        )
