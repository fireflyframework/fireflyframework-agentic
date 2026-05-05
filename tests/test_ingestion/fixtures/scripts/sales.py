import re
from collections.abc import Iterator
from pathlib import Path

from fireflyframework_agentic.ingestion.domain import RawFile, TargetSchema, TypedRecord

PATTERN = re.compile(r"sales.*\.csv$")


def map(file: RawFile, path: Path, schema: TargetSchema) -> Iterator[TypedRecord]:
    text = path.read_text()
    lines = text.strip().splitlines()
    headers = lines[0].split(",")
    for row in lines[1:]:
        values = row.split(",")
        record = dict(zip(headers, values, strict=False))
        yield TypedRecord(
            table="sales",
            row={
                "id": int(record["id"]),
                "customer_id": int(record["customer_id"]),
                "day": record["day"],
                "amount": float(record["amount"]),
                "paid": record["paid"],
            },
        )
