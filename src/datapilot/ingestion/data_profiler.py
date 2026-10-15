import math

import pandas as pd
from pandas.api.types import (
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_numeric_dtype,
)


def _column_kind(series: pd.Series) -> str:
    if is_bool_dtype(series.dtype):
        return "categorical"
    if is_datetime64_any_dtype(series.dtype):
        return "datetime"
    if is_numeric_dtype(series.dtype):
        return "numerical"
    return "categorical"


def _finite_float(value: object) -> float | None:
    if pd.isna(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def profile_dataframe(frame: pd.DataFrame) -> dict[str, object]:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Expected a pandas DataFrame")
    if not frame.columns.is_unique:
        raise ValueError("DataFrame column names must be unique")
    if not all(isinstance(name, str) for name in frame.columns):
        raise ValueError("DataFrame column names must be strings")

    try:
        duplicate_rows = int(frame.duplicated().sum())
    except TypeError as error:
        raise ValueError("DataFrame contains values that cannot be compared") from error

    columns: list[dict[str, object]] = []
    for name in frame.columns:
        series = frame[name]
        kind = _column_kind(series)
        details: dict[str, object] = {
            "name": name,
            "dtype": str(series.dtype),
            "kind": kind,
            "missing_count": int(series.isna().sum()),
        }
        if kind == "numerical":
            valid = pd.to_numeric(series, errors="coerce").dropna()
            details["statistics"] = {
                "count": int(valid.count()),
                "mean": _finite_float(valid.mean()),
                "std": _finite_float(valid.std()),
                "min": _finite_float(valid.min()),
                "max": _finite_float(valid.max()),
            }
        columns.append(details)

    return {
        "row_count": len(frame),
        "column_count": len(frame.columns),
        "duplicate_row_count": duplicate_rows,
        "columns": columns,
    }
