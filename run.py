#!/usr/bin/env python3
"""Bootstrap and run the web client, FastAPI API and CPU worker together."""
import argparse
import hashlib
import os
import signal
import socket
import subprocess
import sys
import threading
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def installation_env():
    env = dict(os.environ)
    # Do not inherit broken certificate paths left by removed Python installations.
    # Existing, user-configured CA bundles are always preserved.
    for key in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE", "PIP_CERT"):
        if env.get(key) and not Path(env[key]).is_file():
            env.pop(key)
    return env


def setup():
    folder = ROOT / ".venv"
    python = folder / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        print("Creating a local Python environment...", flush=True)
        venv.EnvBuilder(with_pip=True).create(folder)
    files = (ROOT / "requirements.txt", ROOT / "constraints-server.txt")
    fingerprint = hashlib.sha256(b"".join(p.read_bytes() for p in files) + sys.version.encode()).hexdigest()
    marker = folder / ".lz-dependencies"
    if not marker.exists() or marker.read_text() != fingerprint:
        print("Installing server dependencies (first run only)...", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(files[0]),
                        "-c", str(files[1])], check=True, cwd=ROOT, env=installation_env())
        marker.write_text(fingerprint)
    return python


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--data-dir", default=os.environ.get("LZ_DATA_DIR", str(ROOT / "var")))
    parser.add_argument("--no-install", action="store_true", help="use current Python, dependencies already installed")
    parser.add_argument("--setup-only", action="store_true", help="install dependencies without starting services")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error("Python 3.12 or newer is required")
    if not 1 <= args.port <= 65535:
        parser.error("port must be in 1..65535")
    python = Path(sys.executable) if args.no_install else setup()
    if args.setup_only:
        return
    dist = ROOT / "client" / "dist" / "index.html"
    if not dist.is_file() and not (ROOT / "web" / "index.html").is_file():
        parser.error("web client missing; run npm ci && npm run build inside client/")
    # Fail before starting a worker if another app already owns the requested port.
    with socket.socket(socket.AF_INET6 if ":" in args.host else socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((args.host, args.port))
        except OSError as exc:
            parser.error(f"cannot listen on {args.host}:{args.port}: {exc}; select another --port")
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    data = Path(args.data_dir).expanduser().resolve()
    env = {**os.environ, "LZ_DATA_DIR": str(data)}
    processes = []
    try:
        processes.append(subprocess.Popen([str(python), "-m", "uvicorn", "server.main:app",
            "--host", args.host, "--port", str(args.port)], cwd=ROOT, env=env))
        processes.append(subprocess.Popen([str(python), "-m", "server.worker"], cwd=ROOT, env=env))
        display_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
        print(f"\nProtein Lab: http://{display_host}:{args.port}/\nAPI docs: http://{display_host}:{args.port}/docs\nData: {data}\nPress Ctrl+C to stop both services.\n", flush=True)
        while not stop.wait(.2):
            if any(p.poll() is not None for p in processes):
                raise RuntimeError("API or worker exited; stopping the remaining service")
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
    try:
        main()
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
