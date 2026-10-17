import importlib
from pathlib import Path

import pytest

MODULES = [
    ".".join(path.with_suffix("").parts[1:]) for path in sorted(Path("src/datapilot").rglob("*.py"))
]


@pytest.mark.parametrize("module", MODULES)
def test_backend_imports(module: str) -> None:
    importlib.import_module(module)
