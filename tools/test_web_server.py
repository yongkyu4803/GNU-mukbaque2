"""Isolated API + worker for Playwright; never writes browser test data to var/."""
import argparse
import os
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=8002, type=int)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    with tempfile.TemporaryDirectory(prefix="lz-browser-test-") as data:
        env = {**os.environ, "LZ_DATA_DIR": data}
        processes = []
        try:
            processes.append(subprocess.Popen([sys.executable, "-m", "lz", "serve", "--port", str(args.port)], cwd=root, env=env))
            processes.append(subprocess.Popen([sys.executable, "-m", "server.worker"], cwd=root, env=env))
            while not stop.wait(.2):
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError("browser test service exited early")
        finally:
            for p in processes:
                if p.poll() is None:
                    p.terminate()
            for p in processes:
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()


if __name__ == "__main__":
    main()
