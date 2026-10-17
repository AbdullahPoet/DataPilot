import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


def test_built_distribution_contains_all_backend_modules(tmp_path: Path) -> None:
    output = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--offline", "--cache-dir", ".uv-cache", "--out-dir", str(output), "--quiet"],
        check=True,
    )
    wheel = next(output.glob("*.whl"))
    expected = {
        path.relative_to("src").as_posix()
        for path in Path("src/datapilot").rglob("*.py")
    }
    extracted = tmp_path / "installed"
    with zipfile.ZipFile(wheel) as archive:
        assert expected.issubset(archive.namelist())
        archive.extractall(extracted)
    with tarfile.open(next(output.glob("*.tar.gz"))) as archive:
        assert not any(Path(name).name == "AGENTS.md" for name in archive.getnames())
    code = (
        "import importlib, pathlib, sys; root = pathlib.Path(sys.argv[1]); "
        "sys.path.insert(0, str(root)); "
        "modules = ['.'.join(path.relative_to(root).with_suffix('').parts) "
        "for path in root.joinpath('datapilot').rglob('*.py')]; "
        "loaded = [importlib.import_module(name) for name in modules]; "
        "assert all(pathlib.Path(module.__file__).is_relative_to(root) for module in loaded)"
    )
    subprocess.run([sys.executable, "-I", "-c", code, str(extracted)], check=True)
