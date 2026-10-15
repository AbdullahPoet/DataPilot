from collections.abc import Mapping
from pathlib import Path


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def _display(value: object) -> str:
    if value is None:
        return "N/A"
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError("Unsupported statistic value")
    return str(value).replace("|", "\\|").replace("\n", " ")


def format_file_knowledge(profile: Mapping[str, object]) -> str:
    row_count = _integer(profile.get("row_count"), "row_count")
    column_count = _integer(profile.get("column_count"), "column_count")
    duplicate_count = _integer(profile.get("duplicate_row_count"), "duplicate_row_count")
    raw_columns = profile.get("columns")
    if not isinstance(raw_columns, list) or len(raw_columns) != column_count:
        raise ValueError("columns must match column_count")
    if duplicate_count > row_count:
        raise ValueError("duplicate_row_count cannot exceed row_count")

    lines = [
        "# Verified File Data Profile",
        "",
        "- Source: Pandas DataFrame profiler",
        f"- Rows: {row_count}",
        f"- Columns: {column_count}",
        f"- Duplicate rows: {duplicate_count}",
        "",
        "## Column Details",
        "",
    ]
    seen: set[str] = set()
    for raw_column in raw_columns:
        if not isinstance(raw_column, Mapping):
            raise ValueError("Each column must be a mapping")
        name = _text(raw_column.get("name"), "column name")
        dtype = _text(raw_column.get("dtype"), "column dtype")
        kind = _text(raw_column.get("kind"), "column kind")
        if kind not in {"numerical", "categorical", "datetime"}:
            raise ValueError(f"Unsupported column kind: {kind}")
        missing_count = _integer(raw_column.get("missing_count"), "missing_count")
        if missing_count > row_count or name in seen:
            raise ValueError("Duplicate column or invalid missing_count")
        seen.add(name)
        lines.extend([
            f"### {_display(name)}",
            "",
            f"- Data type: {_display(dtype)}",
            f"- Kind: {kind}",
            f"- Missing values: {missing_count}",
        ])
        if kind == "numerical":
            statistics = raw_column.get("statistics")
            if not isinstance(statistics, Mapping):
                raise ValueError(f"Missing numerical statistics for {name}")
            count = _integer(statistics.get("count"), "statistics count")
            if count > row_count - missing_count:
                raise ValueError("Statistics count exceeds non-missing rows")
            lines.extend([
                f"- Valid numerical values: {count}",
                f"- Mean: {_display(statistics.get('mean'))}",
                f"- Standard deviation: {_display(statistics.get('std'))}",
                f"- Minimum: {_display(statistics.get('min'))}",
                f"- Maximum: {_display(statistics.get('max'))}",
            ])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_file_knowledge(profile: Mapping[str, object], destination: Path) -> Path:
    content = format_file_knowledge(profile)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")
    return destination
