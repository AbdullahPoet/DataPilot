from dataclasses import dataclass
from typing import Literal, Protocol, Sequence


Scalar = str | int | float | bool | None


class SQLResultLike(Protocol):
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    row_count: int
    truncated: bool


class PandasResultLike(Protocol):
    dataframe: object
    columns: tuple[str, ...]
    row_count: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class ExpectedResult:
    case_id: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Scalar, ...], ...]
    order_sensitive: bool = True


@dataclass(frozen=True, slots=True)
class VerificationEvidence:
    case_id: str
    status: Literal["passed", "failed"]
    reason: str
    evidence_reference: str
    expected_rows: int
    actual_rows: int


@dataclass(frozen=True, slots=True)
class VerificationReport:
    passed: bool
    evidence: tuple[VerificationEvidence, ...]


def _validate_case(case: ExpectedResult) -> None:
    if not isinstance(case.case_id, str) or not case.case_id.strip():
        raise ValueError("Expected result needs a nonempty case ID")
    if not case.columns or any(not isinstance(name, str) or not name for name in case.columns):
        raise ValueError("Expected columns must be nonempty strings")
    if len(set(case.columns)) != len(case.columns):
        raise ValueError("Expected columns must be unique")
    if not isinstance(case.rows, tuple) or any(
        not isinstance(row, tuple) or len(row) != len(case.columns)
        for row in case.rows
    ):
        raise ValueError("Expected rows must match expected columns")
    if any(type(value) not in {str, int, float, bool, type(None)} for row in case.rows for value in row):
        raise ValueError("Expected cells must use scalar JSON-compatible values")
    if type(case.order_sensitive) is not bool:
        raise ValueError("order_sensitive must be boolean")


def _normalize(value: object) -> Scalar:
    if type(value) in {str, int, float, bool, type(None)}:
        return value
    if hasattr(value, "item"):
        converted = value.item()
        if type(converted) in {str, int, float, bool, type(None)}:
            return converted
    raise ValueError("Result contains a value requiring explicit normalization")


def verify_result(
    *,
    columns: Sequence[str],
    rows: Sequence[Sequence[object]],
    truncated: bool,
    cases: Sequence[ExpectedResult],
    evidence_reference: str,
) -> VerificationReport:
    if not isinstance(evidence_reference, str) or not evidence_reference.strip():
        raise ValueError("A nonempty external evidence reference is required")
    if not cases:
        raise ValueError("At least one independently specified expected result is required")
    if type(truncated) is not bool:
        raise ValueError("truncated must be boolean")
    actual_columns = tuple(columns)
    if any(not isinstance(name, str) for name in actual_columns):
        raise ValueError("Actual columns must be strings")
    actual_rows = tuple(tuple(_normalize(value) for value in row) for row in rows)
    if any(len(row) != len(actual_columns) for row in actual_rows):
        raise ValueError("Actual rows do not match columns")
    seen: set[str] = set()
    evidence: list[VerificationEvidence] = []
    for case in cases:
        _validate_case(case)
        if case.case_id in seen:
            raise ValueError("Expected case IDs must be unique")
        seen.add(case.case_id)
        if truncated:
            reason = "Result was truncated; full correctness cannot be verified"
        elif actual_columns != case.columns:
            reason = "Column names or order differ from expected results"
        elif case.order_sensitive and actual_rows != case.rows:
            reason = "Ordered result rows differ from expected results"
        elif not case.order_sensitive and sorted(actual_rows, key=repr) != sorted(case.rows, key=repr):
            reason = "Unordered result rows differ from expected results"
        else:
            reason = "Columns and complete result rows match independently supplied expectations"
        evidence.append(
            VerificationEvidence(
                case_id=case.case_id,
                status="passed" if reason.startswith("Columns and complete") else "failed",
                reason=reason,
                evidence_reference=evidence_reference.strip(),
                expected_rows=len(case.rows),
                actual_rows=len(actual_rows),
            )
        )
    return VerificationReport(
        passed=all(item.status == "passed" for item in evidence),
        evidence=tuple(evidence),
    )


def verify_sql_result(
    result: SQLResultLike,
    cases: Sequence[ExpectedResult],
    evidence_reference: str,
) -> VerificationReport:
    if result.row_count != len(result.rows):
        raise ValueError("SQL result row count does not match materialized rows")
    return verify_result(
        columns=result.columns,
        rows=result.rows,
        truncated=result.truncated,
        cases=cases,
        evidence_reference=evidence_reference,
    )


def verify_pandas_result(
    result: PandasResultLike,
    cases: Sequence[ExpectedResult],
    evidence_reference: str,
) -> VerificationReport:
    import pandas as pd

    if not isinstance(result.dataframe, pd.DataFrame):
        raise TypeError("Pandas result must contain a DataFrame")
    if result.row_count != len(result.dataframe):
        raise ValueError("Pandas result row count does not match materialized rows")
    return verify_result(
        columns=result.columns,
        rows=result.dataframe.itertuples(index=False, name=None),
        truncated=result.truncated,
        cases=cases,
        evidence_reference=evidence_reference,
    )
