"""FastAPI application factory. Start using python -m lz serve."""
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from lz.heptad import assign_register
from lz.library import load_library

from . import services
from .schemas import Helix, RunRequest, ScoreRequest, ScreenRequest, TargetRequest
from .store import Conflict, Missing, Store, digest, new_id

MAX_UPLOAD = 5 * 1024 * 1024


def public_run(run):
    return {k: v for k, v in run.items() if k not in ("worker_id", "heartbeat")}


def create_app(data_dir=None, client_dir=None):
    store = Store(data_dir or os.environ.get("LZ_DATA_DIR", "var"))
    root = Path(__file__).resolve().parent.parent
    client_dist = Path(client_dir) if client_dir else (
        root / "client" / "dist" if (root / "client" / "dist" / "index.html").is_file() else root / "web")

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        services.initialize_catalog(store)
        yield

    app = FastAPI(title="LZ Research API", version="1.0.0", lifespan=lifespan,
                  description="Leucine zipper screening and persistent CPU design jobs. Local single-user service.")
    app.state.store = store

    def error(code, message, status, field=None):
        return JSONResponse(status_code=status, content={"error": {
            "code": code, "message": message, "field": field, "retryable": False}})

    @app.exception_handler(Missing)
    async def missing_handler(_, exc):
        return error("not_found", str(exc), 404)

    @app.exception_handler(Conflict)
    async def conflict_handler(_, exc):
        return error("state_conflict", str(exc), 409)

    @app.exception_handler(ValueError)
    async def value_handler(_, exc):
        return error("invalid_input", str(exc), 422)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_, exc):
        details = [{"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()]
        return error("validation_error", details, 422)

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_, exc):
        return error("http_error", exc.detail, exc.status_code)

    @app.get("/", include_in_schema=False)
    def home():
        if (client_dist / "index.html").is_file():
            return FileResponse(client_dist / "index.html", headers={"Cache-Control": "no-cache"})
        return RedirectResponse("/docs")

    api = APIRouter(prefix="/api/v1")

    @api.get("/health/live", tags=["Health"])
    def live():
        return {"status": "ok"}

    @api.get("/health/ready", tags=["Health"])
    def ready():
        try:
            healthy = store.ready()
        except sqlite3.Error:
            healthy = False
        return JSONResponse(status_code=200 if healthy else 503,
                            content={"ready": healthy, "worker": healthy})

    @api.post("/inputs", status_code=201, tags=["Inputs"])
    async def upload(file: UploadFile = File(...)):
        name = Path((file.filename or "input").replace("\\", "/")).name
        extension = Path(name).suffix.lower().lstrip(".")
        if extension not in {"pdb", "fasta", "fa", "faa", "txt", "json", "csv"}:
            raise HTTPException(422, "supported formats: pdb, fasta, fa, faa, txt, json, csv")
        input_id = new_id("input")
        path = store.file(f"inputs/{input_id}.{extension}")
        try:
            size = 0
            with path.open("wb") as out:
                while chunk := await file.read(65536):
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, "file exceeds 5 MiB")
                    out.write(chunk)
            if not size:
                raise ValueError("empty file")
            raw = path.read_bytes()
            text = raw.decode("utf-8-sig")
            if extension == "pdb":
                # Bound work before any geometry operation; arbitrary full proteomes are out of scope.
                lines = text.splitlines()
                atoms = [line for line in lines if line.startswith(("ATOM  ", "HETATM"))]
                if not atoms or len(atoms) > 20000:
                    raise ValueError("PDB must contain 1..20000 atom records")
                chains = {}
                for line in atoms:
                    if line[12:16].strip() == "CA":
                        chains[line[21:22]] = chains.get(line[21:22], 0) + 1
                if len(chains) > 16 or any(n > 500 for n in chains.values()):
                    raise ValueError("PDB limit: 16 chains, 500 CA records per chain")
            item = store.put("input", {"name": name, "format": extension,
                              "key": str(path.relative_to(store.root)), "size": size,
                              "sha256": digest(raw)}, input_id)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
        return item

    @api.get("/inputs/{input_id}", tags=["Inputs"])
    def input_detail(input_id: str):
        return store.get("input", input_id)

    @api.post("/targets", status_code=201, tags=["Targets"])
    def target_create(request: TargetRequest):
        return services.create_target(store, request)

    @api.get("/targets", tags=["Targets"])
    def targets(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
        return store.list("target", limit, offset)

    @api.get("/targets/{target_id}", tags=["Targets"])
    def target_detail(target_id: str):
        return store.get("target", target_id)

    @api.post("/analyses/register", tags=["Analyses"])
    def register(request: Helix):
        return services.register_data(assign_register(request.sequence, request.offset))

    @api.post("/analyses/score", tags=["Analyses"])
    def score(request: ScoreRequest):
        a = assign_register(request.helix1.sequence, request.helix1.offset)
        b = assign_register(request.helix2.sequence, request.helix2.offset)
        return services.score_result(a, b, store.get("model", request.model_id))

    @api.post("/analyses/screen", tags=["Analyses"])
    def screen(request: ScreenRequest):
        return services.screen_result(store.get("target", request.target_id),
                                      store.get("model", request.model_id),
                                      store.get("library", request.library_id), request.top)

    @api.get("/libraries", tags=["Catalog"])
    def libraries():
        return store.list("library", 500)

    @api.post("/libraries", status_code=201, tags=["Catalog"])
    def library_create(input_id: str):
        item = store.get("input", input_id)
        if item["format"] not in {"json", "fasta", "fa", "faa"}:
            raise ValueError("library must be JSON or FASTA")
        try:
            members = load_library(store.file(item["key"]))
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("invalid library structure; expected zipper entries") from exc
        if not 1 <= len(members) <= 500:
            raise ValueError("library must contain 1..500 entries")
        from dataclasses import asdict
        names = set()
        for member in members:
            if not isinstance(member.name, str) or not member.name.strip():
                raise ValueError("library names must be nonempty strings")
            if not isinstance(member.sequence, str):
                raise ValueError("library sequences must be strings")
            reg = member.register()
            if not 14 <= len(reg.sequence) <= 500 or member.name in names:
                raise ValueError("library names must be unique and sequences must span 14..500 residues")
            names.add(member.name)
            member.sequence = reg.sequence
        return store.put("library", {"name": item["name"], "input_id": input_id,
                                     "sha256": item["sha256"], "verification": "user_supplied",
                                     "members": [asdict(z) for z in members]})

    @api.get("/models", tags=["Catalog"])
    def models():
        return store.list("model", 500)

    @api.get("/models/{model_id}", tags=["Catalog"])
    def model_detail(model_id: str):
        return store.get("model", model_id)

    @api.post("/runs", status_code=202, tags=["Runs"])
    def submit(request: RunRequest):
        return public_run(services.submit(store, request))

    @api.get("/runs", tags=["Runs"])
    def runs(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        return [public_run(r) for r in store.runs(limit, offset)]

    @api.get("/runs/{run_id}", tags=["Runs"])
    def run_detail(run_id: str):
        return public_run(store.run(run_id))

    @api.get("/runs/{run_id}/results", tags=["Runs"])
    def results(run_id: str):
        return services.read_result(store, run_id)

    @api.post("/runs/{run_id}/cancel", status_code=202, tags=["Runs"])
    def cancel(run_id: str):
        return public_run(store.cancel(run_id))

    @api.post("/runs/{run_id}/retry", status_code=202, tags=["Runs"])
    def retry(run_id: str):
        source = store.run(run_id)
        if source["status"] not in {"failed", "cancelled"}:
            raise Conflict("only failed or cancelled runs can be retried")
        # Reuse the exact immutable snapshot and seed; never mutate the previous attempt.
        return public_run(store.create_run(source["request"], source["snapshot"], parent_id=run_id))

    @api.get("/runs/{run_id}/artifacts", tags=["Artifacts"])
    def artifacts(run_id: str):
        store.run(run_id)
        with store.connect() as db:
            return [json.loads(r[0]) for r in db.execute(
                "SELECT data FROM entities WHERE kind='artifact' AND json_extract(data,'$.run_id')=?",
                (run_id,))]

    @api.get("/artifacts/{artifact_id}/download", tags=["Artifacts"])
    def download(artifact_id: str):
        artifact = store.get("artifact", artifact_id)
        path = store.file(artifact["key"])
        if not path.is_file():
            raise Missing("artifact file is missing")
        return FileResponse(path, filename=artifact["name"])

    app.include_router(api)
    if client_dist.is_dir():
        app.mount("/", StaticFiles(directory=client_dist, html=True), name="client")
    return app


app = create_app()
