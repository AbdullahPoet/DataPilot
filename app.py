import subprocess
import sys
from pathlib import Path


def main() -> int:
    app_path = Path(__file__).resolve().with_name("streamlit_app.py")
    if not app_path.is_file():
        raise FileNotFoundError(f"Streamlit application not found: {app_path}")

    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        *sys.argv[1:],
    ]
    try:
        return subprocess.run(command, check=False).returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
