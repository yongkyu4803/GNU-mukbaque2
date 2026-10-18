"""SQLite persistence. No database lock is held during scientific computation."""
import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class Missing(ValueError):
    pass


class Conflict(ValueError):
    pass


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.path = self.root / "research.db"

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self):
        self.root.mkdir(parents=True, exist_ok=True)
        for folder in ("inputs", "runs"):
            (self.root / folder).mkdir(exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise RuntimeError(f"unsupported database schema {version}")
            if version == 1:
                # IDs are scoped by kind: model/default and library/default coexist.
                db.execute("ALTER TABLE entities RENAME TO entities_v1")
            db.execute("""CREATE TABLE IF NOT EXISTS entities (
                id TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(kind,id))""")
            if version == 1:
                db.execute("INSERT INTO entities SELECT * FROM entities_v1")
                db.execute("DROP TABLE entities_v1")
            db.execute("CREATE INDEX IF NOT EXISTS entity_kind ON entities(kind)")
            db.execute("""CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL,
                request TEXT NOT NULL, snapshot TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
                worker_id TEXT, heartbeat REAL, error TEXT, parent_id TEXT)""")
            db.execute("CREATE INDEX IF NOT EXISTS run_queue ON runs(status, created)")
            db.execute("""CREATE TABLE IF NOT EXISTS workers (
                id TEXT PRIMARY KEY, heartbeat REAL NOT NULL)""")
            db.execute("PRAGMA user_version=2")

    def put(self, kind, value, entity_id=None):
        entity_id = entity_id or new_id(kind)
        value = {**value, "id": entity_id}
        with self.connect() as db:
            db.execute("INSERT INTO entities VALUES(?,?,?)",
                       (entity_id, kind, dumps(value)))
        return value

    def get(self, kind, entity_id):
        with self.connect() as db:
            row = db.execute("SELECT data FROM entities WHERE kind=? AND id=?",
                             (kind, entity_id)).fetchone()
        if row is None:
            raise Missing(f"{kind} not found: {entity_id}")
        return json.loads(row[0])

    def list(self, kind, limit=100, offset=0):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute(
                "SELECT data FROM entities WHERE kind=? ORDER BY rowid LIMIT ? OFFSET ?",
                (kind, limit, offset))]

    @staticmethod
    def decode(row):
        if row is None:
            raise Missing("run not found")
        out = dict(row)
        for key in ("request", "snapshot", "error"):
            if out[key] is not None:
                out[key] = json.loads(out[key])
        return out

    def create_run(self, request, snapshot, parent_id=None):
        run_id, now = new_id("run"), time.time()
        with self.connect() as db:
            db.execute("""INSERT INTO runs
                (id,kind,status,created,updated,request,snapshot,parent_id)
                VALUES(?,?,'queued',?,?,?,?,?)""",
                (run_id, request["kind"], now, now, dumps(request),
                 dumps(snapshot), parent_id))
        return self.run(run_id)

    def run(self, run_id):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())

    def runs(self, limit=50, offset=0):
        with self.connect() as db:
            return [self.decode(r) for r in db.execute(
                "SELECT * FROM runs ORDER BY created DESC LIMIT ? OFFSET ?", (limit, offset))]

    def claim(self, worker_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM runs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("""UPDATE runs SET status='running',worker_id=?,heartbeat=?,updated=?
                WHERE id=? AND status='queued'""", (worker_id, time.time(), time.time(), row["id"]))
        return self.run(row["id"])

    def cancel(self, run_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise Missing("run not found")
            state = row[0]
            if state not in ("queued", "running", "cancel_requested"):
                raise Conflict("run is already terminal")
            db.execute("UPDATE runs SET status=?,updated=? WHERE id=?",
                       ("cancelled" if state == "queued" else "cancel_requested", time.time(), run_id))
        return self.run(run_id)

    def progress(self, run_id, fraction, message):
        with self.connect() as db:
            db.execute("""UPDATE runs SET progress=?,message=?,updated=?
                WHERE id=? AND status='running'""",
                (min(max(fraction, 0), .99), message, time.time(), run_id))

    def heartbeat(self, worker_id, run_id=None):
        now = time.time()
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO workers VALUES(?,?)", (worker_id, now))
            if run_id:
                db.execute("UPDATE runs SET heartbeat=? WHERE id=? AND worker_id=?",
                           (now, run_id, worker_id))

    def ready(self):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM workers WHERE heartbeat>? LIMIT 1",
                              (time.time() - 15,)).fetchone() is not None

    def recover(self, stale_seconds=30):
        with self.connect() as db:
            db.execute("""UPDATE runs SET status='failed', error=?, updated=?
                WHERE status IN ('running','cancel_requested') AND heartbeat<?""",
                (dumps({"code": "interrupted", "message": "worker heartbeat expired", "retryable": True}),
                 time.time(), time.time() - stale_seconds))

    def finish(self, run_id, worker_id, status, artifacts=(), model=None, error=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,worker_id FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None or row["worker_id"] != worker_id or row["status"] not in ("running", "cancel_requested"):
                return
            if row["status"] == "cancel_requested":
                status = "cancelled"
            if status == "succeeded":
                for artifact in artifacts:
                    db.execute("INSERT INTO entities VALUES(?,?,?)",
                               (artifact["id"], "artifact", dumps(artifact)))
                if model:
                    db.execute("INSERT INTO entities VALUES(?,?,?)", (model["id"], "model", dumps(model)))
            db.execute("UPDATE runs SET status=?,updated=?,progress=?,error=? WHERE id=?",
                       (status, time.time(), 1 if status == "succeeded" else 0,
                        dumps(error) if error else None, run_id))

    def file(self, key):
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("invalid artifact storage key")
        return path
