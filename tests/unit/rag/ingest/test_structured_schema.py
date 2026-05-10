from fireflyframework_agentic.rag.ingest.structured_schema import (
    ColumnSpec,
    ColumnType,
    TableSpec,
    TargetSchema,
)


def test_column_spec_defaults():
    col = ColumnSpec(name="id", type=ColumnType.integer)
    assert col.nullable is True
    assert col.primary_key is False


def test_table_spec_columns():
    table = TableSpec(
        name="sales",
        columns=[
            ColumnSpec(name="id", type=ColumnType.integer, primary_key=True),
            ColumnSpec(name="amount", type=ColumnType.float_),
        ],
    )
    assert len(table.columns) == 2
    assert table.columns[0].primary_key is True


def test_target_schema_roundtrip():
    schema = TargetSchema(
        tables=[
            TableSpec(
                name="customers",
                columns=[ColumnSpec(name="name", type=ColumnType.string, nullable=False)],
            )
        ]
    )
    json_str = schema.model_dump_json()
    restored = TargetSchema.model_validate_json(json_str)
    assert restored.tables[0].name == "customers"
    assert restored.tables[0].columns[0].nullable is False


def test_column_type_values():
    assert ColumnType.string == "string"
    assert ColumnType.float_ == "float"
    assert ColumnType.datetime == "datetime"
