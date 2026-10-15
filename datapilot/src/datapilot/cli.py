import subprocess
import sys
from pathlib import Path


def main() -> int:
    app_path = Path(__file__).resolve().with_name("app.py")
    if not app_path.is_file():
        raise FileNotFoundError(f"DataPilot application not found: {app_path}")

    completed = subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path), *sys.argv[1:]],
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
