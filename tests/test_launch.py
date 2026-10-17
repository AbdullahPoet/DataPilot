import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def test_python_app_launches(tmp_path: Path) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = {**os.environ, "DATAPILOT_HOME": str(tmp_path)}
    process = subprocess.Popen(
        [
            sys.executable,
            "app.py",
            "--server.headless=true",
            "--server.address=127.0.0.1",
            f"--server.port={port}",
            "--browser.gatherUsageStats=false",
        ],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        start_new_session=sys.platform != "win32",
    )
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            assert process.poll() is None, "python app.py exited before becoming healthy"
            try:
                with urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as response:
                    assert response.read() == b"ok"
                    return
            except (URLError, TimeoutError, ConnectionError):
                time.sleep(0.1)
        raise AssertionError("python app.py did not become healthy within 25 seconds")
    finally:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
