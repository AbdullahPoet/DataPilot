from collections.abc import Mapping
from pathlib import Path


def _items(value: object, field: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{field} must be a list of dictionaries")
    return value


def _names(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return value


def _required_text(item: Mapping[str, object], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value.replace("\n", " ").replace("\r", " ")


def _identifier(value: str) -> str:
    escaped = value.replace("`", "\\`")
    return f"`{escaped}`"


def format_schema_markdown(metadata: Mapping[str, object]) -> str:
    dialect = _required_text(metadata, "dialect")
    schema = metadata.get("schema")
    if schema is not None and not isinstance(schema, str):
        raise ValueError("schema must be a string or None")

    lines = ["# Verified Database Schema", "", f"- Dialect: {_identifier(dialect)}"]
    if schema:
        lines.append(f"- Schema: {_identifier(schema)}")
    lines.extend(["- Source: SQLAlchemy Inspector", "", "## Tables"])

    for table in _items(metadata.get("tables"), "tables"):
        table_name = _required_text(table, "name")
        lines.extend(["", f"### {_identifier(table_name)}", "", "#### Columns"])
        for column in _items(table.get("columns"), "columns"):
            name = _required_text(column, "name")
            data_type = _required_text(column, "type")
            nullable = column.get("nullable")
            if not isinstance(nullable, bool):
                raise TypeError("nullable must be a boolean")
            lines.append(f"- {_identifier(name)}: {_identifier(data_type)}, nullable: {nullable}")

        primary_key = _names(table.get("primary_key"), "primary_key")
        lines.extend(["", "#### Primary Key", ""])
        lines.append(", ".join(_identifier(name) for name in primary_key) if primary_key else "None declared")
        lines.extend(["", "#### Declared Foreign Keys", ""])

        foreign_keys = _items(table.get("foreign_keys"), "foreign_keys")
        if not foreign_keys:
            lines.append("None declared")
        for foreign_key in foreign_keys:
            source_columns = _names(foreign_key.get("columns"), "columns")
            target_columns = _names(foreign_key.get("referenced_columns"), "referenced_columns")
            target_table = _required_text(foreign_key, "referenced_table")
            target_schema = foreign_key.get("referenced_schema")
            if target_schema is not None and not isinstance(target_schema, str):
                raise ValueError("referenced_schema must be a string or None")
            target = f"{target_schema}.{target_table}" if target_schema else target_table
            source = ", ".join(_identifier(name) for name in source_columns)
            destination = ", ".join(_identifier(name) for name in target_columns)
            lines.append(f"- ({source}) → {_identifier(target)} ({destination})")

    return "\n".join(lines) + "\n"


def write_schema_markdown(metadata: Mapping[str, object], output_path: Path) -> Path:
    content = format_schema_markdown(metadata)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path
