import ast
import re
from collections.abc import Iterable
from dataclasses import dataclass

from datapilot.agents.pandas_agent import PandasAnalysisPlan


class PandasPlanValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedPandasPlan:
    operations: tuple[str, ...]
    required_columns: tuple[str, ...]
    explanation: str
    assumptions: tuple[str, ...]
    file_type: str
    model: str
    provider: str


_UNSAFE_TERMS = re.compile(
    r"\b(?:exec|eval|compile|__import__|subprocess|os\.system|os\.popen|"
    r"open\s*\(|read_csv\s*\(|read_excel\s*\(|read_parquet\s*\(|"
    r"to_csv\s*\(|to_excel\s*\(|to_pickle\s*\(|read_pickle\s*\(|"
    r"requests\.|urllib\.|httpx\.|socket\.|shutil\.|pathlib\.|"
    r"globals\s*\(|locals\s*\(|getattr\s*\(|setattr\s*\(|"
    r"delattr\s*\(|import\s+\w+|from\s+\w+\s+import)\b",
    re.IGNORECASE,
)


def _validate_description(operation: str, *, maximum_length: int) -> str:
    text = operation.strip()
    if not text or len(text) > maximum_length:
        raise PandasPlanValidationError("Operation must be non-empty and within the length limit")
    if any(character in text for character in ("\x00", "\r", "\n", "`", ";", "\\")):
        raise PandasPlanValidationError("Operation contains code-like delimiters")
    if _UNSAFE_TERMS.search(text):
        raise PandasPlanValidationError("Operation contains a prohibited executable instruction")
    try:
        parsed = ast.parse(text, mode="exec")
    except SyntaxError:
        return text
    if any(
        isinstance(node, (ast.Call, ast.Import, ast.ImportFrom, ast.Assign, ast.AugAssign,
                          ast.Delete, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                          ast.For, ast.While, ast.With, ast.Try, ast.Lambda, ast.Subscript))
        for node in ast.walk(parsed)
    ):
        raise PandasPlanValidationError("Executable Python is not an accepted analysis plan")
    return text


def validate_pandas_plan(
    plan: PandasAnalysisPlan,
    available_columns: Iterable[str],
    *,
    max_operations: int = 20,
    max_operation_length: int = 500,
) -> ValidatedPandasPlan:
    if not isinstance(plan, PandasAnalysisPlan):
        raise TypeError("Expected a PandasAnalysisPlan")
    if not isinstance(max_operations, int) or max_operations < 1:
        raise ValueError("max_operations must be a positive integer")
    if not isinstance(max_operation_length, int) or max_operation_length < 1:
        raise ValueError("max_operation_length must be a positive integer")
    if plan.file_type not in ("csv", "xlsx"):
        raise PandasPlanValidationError("Unsupported file type")
    columns = tuple(available_columns)
    if not columns or any(not isinstance(column, str) or not column for column in columns):
        raise PandasPlanValidationError("Verified columns must be non-empty strings")
    if len(set(columns)) != len(columns):
        raise PandasPlanValidationError("Verified columns contain duplicates")
    if not plan.operations or len(plan.operations) > max_operations:
        raise PandasPlanValidationError("Operation count is outside the accepted range")
    if len(set(plan.required_columns)) != len(plan.required_columns):
        raise PandasPlanValidationError("Required columns contain duplicates")
    missing = set(plan.required_columns).difference(columns)
    if missing:
        raise PandasPlanValidationError(f"Unknown columns: {', '.join(sorted(missing))}")
    operations = tuple(
        _validate_description(operation, maximum_length=max_operation_length)
        for operation in plan.operations
    )
    if not plan.explanation.strip():
        raise PandasPlanValidationError("Explanation is required")
    return ValidatedPandasPlan(
        operations=operations,
        required_columns=plan.required_columns,
        explanation=plan.explanation,
        assumptions=plan.assumptions,
        file_type=plan.file_type,
        model=plan.model,
        provider=plan.provider,
    )
