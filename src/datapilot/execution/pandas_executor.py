from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from datapilot.validation.pandas_validator import ValidatedPandasPlan


OperationKind = Literal["filter", "select", "groupby", "sort", "limit"]


class PandasExecutionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PandasOperation:
    kind: OperationKind
    parameters: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PandasExecutionResult:
    dataframe: pd.DataFrame
    row_count: int
    columns: tuple[str, ...]
    operations_applied: int
    truncated: bool


def _columns(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise PandasExecutionError(f"{label} must be a non-empty sequence of column names")
    if len(set(value)) != len(value):
        raise PandasExecutionError(f"{label} contains duplicate columns")
    return list(value)


def _require_columns(frame: pd.DataFrame, names: Sequence[str]) -> None:
    missing = set(names).difference(frame.columns)
    if missing:
        raise PandasExecutionError(f"Unknown columns: {', '.join(sorted(missing))}")


def _apply_operation(frame: pd.DataFrame, operation: PandasOperation) -> pd.DataFrame:
    params = operation.parameters
    if not isinstance(params, Mapping):
        raise PandasExecutionError("Operation parameters must be a mapping")
    if operation.kind == "select":
        if set(params) != {"columns"}:
            raise PandasExecutionError("Select requires only columns")
        columns = _columns(params["columns"], label="Selected columns")
        _require_columns(frame, columns)
        return frame.loc[:, columns].copy()
    if operation.kind == "filter":
        if set(params) != {"column", "operator", "value"}:
            raise PandasExecutionError("Filter requires column, operator and value")
        column, operator, value = params["column"], params["operator"], params["value"]
        if not isinstance(column, str):
            raise PandasExecutionError("Filter column must be text")
        _require_columns(frame, [column])
        series = frame[column]
        try:
            if operator == "eq":
                mask = series.eq(value)
            elif operator == "ne":
                mask = series.ne(value)
            elif operator == "gt":
                mask = series.gt(value)
            elif operator == "gte":
                mask = series.ge(value)
            elif operator == "lt":
                mask = series.lt(value)
            elif operator == "lte":
                mask = series.le(value)
            elif operator == "in" and isinstance(value, (list, tuple)):
                mask = series.isin(value)
            elif operator == "is_null" and value is None:
                mask = series.isna()
            elif operator == "not_null" and value is None:
                mask = series.notna()
            else:
                raise PandasExecutionError("Unsupported filter operator or value")
            if not pd.api.types.is_bool_dtype(mask):
                raise PandasExecutionError("Filter expression did not produce a boolean mask")
            return frame.loc[mask.fillna(False)].copy()
        except (TypeError, ValueError) as error:
            if isinstance(error, PandasExecutionError):
                raise
            raise PandasExecutionError("Invalid filter value for column type") from error
    if operation.kind == "groupby":
        if set(params) != {"by", "aggregations"}:
            raise PandasExecutionError("Groupby requires by and aggregations")
        by = _columns(params["by"], label="Group columns")
        aggregations = params["aggregations"]
        if not isinstance(aggregations, Mapping) or not aggregations:
            raise PandasExecutionError("Aggregations must be a non-empty mapping")
        if any(not isinstance(column, str) or not isinstance(fn, str) for column, fn in aggregations.items()):
            raise PandasExecutionError("Aggregations must map columns to function names")
        if any(fn not in {"sum", "mean", "min", "max", "count", "nunique"} for fn in aggregations.values()):
            raise PandasExecutionError("Unsupported aggregation function")
        _require_columns(frame, [*by, *aggregations])
        if set(by).intersection(aggregations):
            raise PandasExecutionError("Group columns cannot also be aggregate targets")
        try:
            return frame.groupby(by, dropna=False, sort=False).agg(dict(aggregations)).reset_index()
        except (TypeError, ValueError) as error:
            raise PandasExecutionError("Aggregation is incompatible with the column type") from error
    if operation.kind == "sort":
        if set(params) != {"by", "ascending"}:
            raise PandasExecutionError("Sort requires by and ascending")
        by = _columns(params["by"], label="Sort columns")
        ascending = params["ascending"]
        if type(ascending) is not bool:
            raise PandasExecutionError("Ascending must be a boolean")
        _require_columns(frame, by)
        return frame.sort_values(by=by, ascending=ascending, kind="stable").copy()
    if operation.kind == "limit":
        if set(params) != {"rows"} or type(params["rows"]) is not int or params["rows"] < 1:
            raise PandasExecutionError("Limit requires a positive integer row count")
        return frame.head(params["rows"]).copy()
    raise PandasExecutionError("Unsupported Pandas operation")


def execute_pandas_plan(
    dataframe: pd.DataFrame,
    validated_plan: ValidatedPandasPlan,
    operations: Sequence[PandasOperation],
    *,
    max_input_rows: int = 1_000_000,
    max_result_rows: int = 10_000,
) -> PandasExecutionResult:
    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("A Pandas DataFrame is required")
    if not isinstance(validated_plan, ValidatedPandasPlan):
        raise TypeError("A validated Pandas analysis plan is required")
    if type(max_input_rows) is not int or max_input_rows < 1:
        raise ValueError("max_input_rows must be a positive integer")
    if type(max_result_rows) is not int or max_result_rows < 1:
        raise ValueError("max_result_rows must be a positive integer")
    if len(dataframe) > max_input_rows:
        raise PandasExecutionError("Input exceeds the configured row limit")
    if any(not isinstance(name, str) for name in dataframe.columns) or not dataframe.columns.is_unique:
        raise PandasExecutionError("DataFrame columns must be unique strings")
    _require_columns(dataframe, validated_plan.required_columns)
    if not operations or len(operations) > len(validated_plan.operations):
        raise PandasExecutionError("Operations must fit within the validated plan length")
    if any(not isinstance(operation, PandasOperation) for operation in operations):
        raise PandasExecutionError("Every step must be an allowlisted PandasOperation")
    result = dataframe.copy()
    for operation in operations:
        result = _apply_operation(result, operation)
    truncated = len(result) > max_result_rows
    result = result.head(max_result_rows).copy()
    return PandasExecutionResult(
        dataframe=result,
        row_count=len(result),
        columns=tuple(result.columns),
        operations_applied=len(operations),
        truncated=truncated,
    )
