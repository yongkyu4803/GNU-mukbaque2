"""The distributable runs without the original checkout, Node or a dev build."""
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def test_standalone_launcher_starts_api_worker_and_bundled_web(tmp_path):
    root = Path(__file__).resolve().parent.parent
    standalone = tmp_path / "standalone"
    standalone.mkdir()
    for folder in ("server", "lz", "data", "web"):
        shutil.copytree(root / folder, standalone / folder,
                        ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(root / "run.py", standalone / "run.py")
    assert not (standalone / "LZ-program").exists()
    assert not (standalone / "client").exists()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (tmp_path / "launcher.log").open("w") as log:
        process = subprocess.Popen([sys.executable, str(standalone / "run.py"),
            "--no-install", "--port", str(port)], cwd=standalone,
            stdout=log, stderr=subprocess.STDOUT)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5) as client:
                deadline = time.monotonic() + 15
                while True:
                    try:
                        if client.get("/api/v1/health/ready").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    assert time.monotonic() < deadline, "standalone startup timed out"
                    assert process.poll() is None, "launcher exited early"
                    time.sleep(.1)
                assert "Protein Lab" in client.get("/").text
                assert client.get("/fonts/Pretendard-Regular.woff2").status_code == 200
                assert client.get("/docs").status_code == 200
                response = client.post("/api/v1/targets", json={"helix": {
                    "sequence": "RMKQLEDKVEELLSKNYHLENEVARLKKLVGER"}})
                response.raise_for_status()
                response = client.post("/api/v1/runs", json={"kind": "design",
                    "target_id": response.json()["id"], "seed": 1,
                    "parameters": {"n_restarts": 1, "n_steps": 50}})
                response.raise_for_status()
                run_id = response.json()["id"]
                deadline = time.monotonic() + 15
                while True:
                    state = client.get(f"/api/v1/runs/{run_id}").json()
                    if state["status"] in ("succeeded", "failed"):
                        break
                    assert time.monotonic() < deadline, "standalone worker timed out"
                    time.sleep(.1)
                assert state["status"] == "succeeded", state
                assert client.get(f"/api/v1/runs/{run_id}/results").json()["candidates"]
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    assert process.returncode == 0
