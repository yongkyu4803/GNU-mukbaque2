"""Run with python -m server.worker. CPU work never runs in the HTTP process."""
import argparse
import json
import multiprocessing
import os
import signal
import time
import traceback

from .services import execute, initialize_catalog, provenance
from .store import Store, dumps, new_id


class Cancelled(Exception):
    pass


def child_job(root, run, stop):
    store = Store(root)
    folder = store.file(f"runs/{run['id']}")
    folder.mkdir(parents=True, exist_ok=True)

    def progress(fraction, message):
        if stop.is_set():
            raise Cancelled()
        store.progress(run["id"], fraction, message)

    try:
        if provenance()["source_sha256"] != run["snapshot"]["provenance"]["source_sha256"]:
            raise ValueError("source changed since submission; submit a new run")
        execute(store, run, progress)
    except Cancelled:
        return
    except Exception as exc:
        (folder / ".error.json").write_text(dumps({
            "code": "computation_failed", "message": str(exc), "retryable": False}))
        (folder / "traceback.log").write_text(traceback.format_exc())
        raise SystemExit(1)


def run_one(store, worker_id, shutdown=None, timeout=900):
    store.heartbeat(worker_id)
    store.recover()
    run = store.claim(worker_id)
    if run is None:
        return False
    context = multiprocessing.get_context("spawn")
    stop = context.Event()
    child = context.Process(target=child_job, args=(str(store.root), run, stop))
    error, cancelled = None, False
    start = time.monotonic()
    try:
        child.start()
        while child.is_alive():
            store.heartbeat(worker_id, run["id"])
            state = store.run(run["id"])["status"]
            if state == "cancel_requested":
                cancelled = True
                break
            if shutdown is not None and shutdown.is_set():
                error = {"code": "interrupted", "message": "worker stopped", "retryable": True}
                break
            if time.monotonic() - start > timeout:
                error = {"code": "timeout", "message": "execution time limit exceeded", "retryable": True}
                break
            child.join(.2)
    except Exception as exc:
        error = {"code": "worker_failed", "message": str(exc), "retryable": True}
    finally:
        if child.pid is not None:
            if child.is_alive():
                stop.set()
                child.join(.5)
            if child.is_alive():
                child.terminate()
                child.join(2)
            if child.is_alive():
                child.kill()
                child.join()
    folder = store.file(f"runs/{run['id']}")
    if cancelled:
        store.finish(run["id"], worker_id, "cancelled")
    elif error:
        store.finish(run["id"], worker_id, "failed", error=error)
    elif child.exitcode == 0 and (folder / ".completion.json").exists():
        completion = json.loads((folder / ".completion.json").read_text())
        store.finish(run["id"], worker_id, "succeeded", **completion)
    else:
        path = folder / ".error.json"
        error = json.loads(path.read_text()) if path.exists() else {
            "code": "worker_crashed", "message": "calculation exited without a result", "retryable": True}
        store.finish(run["id"], worker_id, "failed", error=error)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=os.environ.get("LZ_DATA_DIR", "var"))
    parser.add_argument("--once", action="store_true", help="process at most one queued run")
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    import threading
    shutdown = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: shutdown.set())
    store = Store(args.data_dir)
    store.initialize()
    initialize_catalog(store)
    worker_id = new_id("worker")
    try:
        while not shutdown.is_set():
            worked = run_one(store, worker_id, shutdown, args.timeout)
            if args.once:
                break
            if not worked:
                shutdown.wait(.5)
    finally:
        with store.connect() as db:
            db.execute("DELETE FROM workers WHERE id=?", (worker_id,))


if __name__ == "__main__":
    main()
