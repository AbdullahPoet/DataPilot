from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine


def inspect_schema(engine: Engine | Connection, schema: str | None = None) -> dict[str, object]:
    inspector = inspect(engine)
    tables: list[dict[str, object]] = []

    for table_name in sorted(inspector.get_table_names(schema=schema)):
        columns = [
            {
                "name": column["name"],
                "type": str(column["type"]),
                "nullable": column["nullable"],
                "default": str(column["default"]) if column.get("default") is not None else None,
            }
            for column in inspector.get_columns(table_name, schema=schema)
        ]
        primary_key = inspector.get_pk_constraint(table_name, schema=schema)
        foreign_keys = [
            {
                "columns": foreign_key["constrained_columns"],
                "referenced_schema": foreign_key.get("referred_schema"),
                "referenced_table": foreign_key["referred_table"],
                "referenced_columns": foreign_key["referred_columns"],
            }
            for foreign_key in inspector.get_foreign_keys(table_name, schema=schema)
        ]
        tables.append(
            {
                "name": table_name,
                "columns": columns,
                "primary_key": primary_key.get("constrained_columns") or [],
                "foreign_keys": foreign_keys,
            }
        )

    return {
        "dialect": inspector.dialect.name,
        "schema": schema,
        "tables": tables,
    }
