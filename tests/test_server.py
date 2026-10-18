"""HTTP -> persistent queue -> real spawned CPU process -> downloadable results."""
import csv
import io
import json
import random
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from lz.design import ALPHABET, design_partner
from lz.heptad import assign_register
from lz.scoring import score_pair
from server.main import create_app
from server.store import Store, dumps
from server.worker import run_one

TARGET = "RMKQLEDKVEELLSKNYHLENEVARLKKLVGER"


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as c:
        yield c


def target(client):
    r = client.post("/api/v1/targets", json={"helix": {"sequence": TARGET}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(client, name, content):
    r = client.post("/api/v1/inputs", files={"file": (name, content)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def submit(client, request):
    r = client.post("/api/v1/runs", json=request)
    assert r.status_code == 202, r.text
    return r.json()


def finish(client, run):
    assert run_one(client.app.state.store, "test-worker", timeout=30)
    state = client.get(f"/api/v1/runs/{run['id']}").json()
    assert state["status"] == "succeeded", state
    return client.get(f"/api/v1/runs/{run['id']}/results").json()


def calibration_csv():
    rng, out = random.Random(11), io.StringIO()
    w = csv.writer(out)
    w.writerow(["sequence1", "sequence2", "tm"])
    for _ in range(30):
        seqs = ["".join(rng.choice(ALPHABET["abcdefg"[j % 7]]) for j in range(28))
                for _ in range(2)]
        s = score_pair(*seqs, {"core": 1., "electrostatic": 1., "helix": 1.})
        w.writerow([*seqs, 80 - 4*s.core - 2*s.electrostatic - 3*s.helix])
    return out.getvalue()


def test_openapi_and_health_without_worker(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/api/v1/health/live").status_code == 200
    assert client.get("/api/v1/health/ready").status_code == 503


def test_register_and_score_match_core_without_nan(client):
    r = client.post("/api/v1/analyses/register", json={"sequence": TARGET, "offset": 6})
    assert r.status_code == 200
    assert r.json()["confidence"] is None
    response = client.post("/api/v1/analyses/score", json={
        "helix1": {"sequence": TARGET}, "helix2": {"sequence": TARGET}})
    assert response.json()["total"] == score_pair(TARGET, TARGET).total
    assert response.json()["predicted_tm"] is None


@pytest.mark.parametrize("payload", [
    {"sequence": "XXXXXXX"}, {"sequence": TARGET, "offset": 7},
    {"sequence": TARGET, "surprise": 1},
])
def test_invalid_inputs_are_structured_422(client, payload):
    r = client.post("/api/v1/analyses/register", json=payload)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_screen_reports_both_specificity_definitions(client):
    r = client.post("/api/v1/analyses/screen", json={"target_id": target(client)})
    assert r.status_code == 200
    fos = next(h for h in r.json()["candidates"] if h["name"] == "c-Fos-LZ")
    assert fos["specificity"] < 0 < fos["specificity_both"]


def test_design_worker_roundtrip_persistence_and_exports(client):
    run = submit(client, {"kind": "design", "target_id": target(client), "seed": 7,
                          "parameters": {"n_restarts": 1, "n_steps": 100}})
    assert run["status"] == "queued"
    assert client.get(f"/api/v1/runs/{run['id']}/results").status_code == 409
    result = finish(client, run)
    assert result["candidates"]
    assert "target_self" in result["specificity_definition"]
    artifacts = client.get(f"/api/v1/runs/{run['id']}/artifacts").json()
    by_name = {a["name"]: a for a in artifacts}
    assert {"manifest.json", "result.json", "candidates.csv", "complexes.fasta"} <= set(by_name)
    manifest = client.get(f"/api/v1/artifacts/{by_name['manifest.json']['id']}/download").json()
    assert manifest["request"]["seed"] == 7
    assert manifest["snapshot"]["provenance"]["source_sha256"]
    with TestClient(create_app(client.app.state.store.root)) as restarted:
        assert restarted.get(f"/api/v1/runs/{run['id']}/results").json() == result


def test_orthogonal_final_shift_regression_and_all_complexes(client):
    run = submit(client, {"kind": "orthogonal", "seed": 20,
                          "parameters": {"n_pairs": 2, "n_restarts": 1, "n_steps": 2000}})
    result = finish(client, run)
    assert result["search_margins"][1] < -3
    assert result["pairs"][1]["margin"] > -3
    assert result["evaluation"]["passed"] is False
    assert client.get(f"/api/v1/runs/{run['id']}").json()["status"] == "succeeded"
    artifacts = client.get(f"/api/v1/runs/{run['id']}/artifacts").json()
    artifact = next(a for a in artifacts if a["name"] == "complexes.json")
    pairs = client.get(f"/api/v1/artifacts/{artifact['id']}/download").json()
    assert len(pairs) == 10
    assert sum(p["intended"] for p in pairs) == 2
    assert sum(p["homodimer"] for p in pairs) == 4
    assert any(p["chain1"] == "B" and p["chain2"] == "B'" for p in pairs)


def test_queue_cancel_retry_keeps_snapshot_and_seed(client):
    run = submit(client, {"kind": "design", "target_id": target(client),
                          "parameters": {"n_restarts": 1, "n_steps": 50}})
    assert isinstance(run["request"]["seed"], int)
    assert client.post(f"/api/v1/runs/{run['id']}/cancel").json()["status"] == "cancelled"
    retry = client.post(f"/api/v1/runs/{run['id']}/retry")
    assert retry.status_code == 202
    retry = retry.json()
    assert retry["parent_id"] == run["id"]
    assert retry["snapshot"] == run["snapshot"]
    assert retry["request"]["seed"] == run["request"]["seed"]
    finish(client, retry)
    assert client.post(f"/api/v1/runs/{retry['id']}/retry").status_code == 409


def test_active_job_cancellation(client):
    run = submit(client, {"kind": "design", "target_id": target(client),
                          "parameters": {"n_restarts": 16, "n_steps": 20000}})
    store = client.app.state.store
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_one, store, "cancel-worker", None, 30)
        deadline = time.monotonic() + 10
        while store.run(run["id"])["status"] == "queued" and time.monotonic() < deadline:
            time.sleep(.02)
        assert client.post(f"/api/v1/runs/{run['id']}/cancel").status_code == 202
        assert future.result(timeout=10)
    assert store.run(run["id"])["status"] == "cancelled"
    assert client.get(f"/api/v1/runs/{run['id']}/artifacts").json() == []


def test_worker_timeout_is_failed_not_scientific_failure(client):
    run = submit(client, {"kind": "design", "target_id": target(client),
                          "parameters": {"n_restarts": 16, "n_steps": 20000}})
    run_one(client.app.state.store, "timeout-worker", timeout=.01)
    state = client.get(f"/api/v1/runs/{run['id']}").json()
    assert state["status"] == "failed"
    assert state["error"]["code"] == "timeout"


def test_stale_recovery_and_atomic_claim(client):
    tid = target(client)
    for seed in (1, 2):
        submit(client, {"kind": "design", "target_id": tid, "seed": seed})
    store = client.app.state.store
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(store.claim, ["w1", "w2"]))
    assert a["id"] != b["id"]
    with store.connect() as db:
        db.execute("UPDATE runs SET heartbeat=0 WHERE id=?", (a["id"],))
    store.recover()
    assert store.run(a["id"])["error"]["code"] == "interrupted"
    assert store.run(b["id"])["status"] == "running"


def test_calibration_saves_model_and_score_uses_it(client):
    iid = upload(client, "measurements.csv", calibration_csv())
    run = submit(client, {"kind": "calibration", "input_id": iid})
    result = finish(client, run)
    model = result["model"]
    assert model["tm_intercept"] == pytest.approx(80)
    assert model["tm_slope"] == pytest.approx(-4)
    assert model["metrics"]["evaluation"] == "training_only"
    response = client.post("/api/v1/analyses/score", json={
        "model_id": model["id"], "helix1": {"sequence": TARGET}, "helix2": {"sequence": TARGET}}).json()
    assert response["predicted_tm"] == pytest.approx(80 - 4 * response["total"])
    assert client.get(f"/api/v1/models/{model['id']}").status_code == 200


def test_calibration_failure_does_not_publish_model_or_artifacts(client):
    iid = upload(client, "bad.csv", "sequence1,sequence2,tm\n" + f"{TARGET},{TARGET},40\n"*5)
    run = submit(client, {"kind": "calibration", "input_id": iid})
    run_one(client.app.state.store, "bad-data-worker", timeout=30)
    state = client.get(f"/api/v1/runs/{run['id']}").json()
    assert state["status"] == "failed"
    assert "rank deficient" in state["error"]["message"]
    assert client.get(f"/api/v1/runs/{run['id']}/artifacts").json() == []
    assert len(client.get("/api/v1/models").json()) == 1


def test_uploaded_fasta_and_library_versions(client):
    iid = upload(client, "target.fasta", f">GCN4\n{TARGET}\n")
    r = client.post("/api/v1/targets", json={"input_id": iid})
    assert r.status_code == 201
    assert r.json()["sequence"] == TARGET
    library = client.post("/api/v1/libraries", params={"input_id": iid})
    assert library.status_code == 201
    assert len(library.json()["members"]) == 1
    multiple = upload(client, "multiple.fasta", f">a\n{TARGET}\n>b\n{TARGET}\n")
    assert client.post("/api/v1/targets", json={"input_id": multiple}).status_code == 422


def test_upload_and_path_boundaries(client):
    assert client.post("/api/v1/inputs", files={"file": ("bad.exe", b"x")}).status_code == 422
    assert client.post("/api/v1/inputs", files={"file": ("huge.txt", b"a"*(5*1024*1024+1))}).status_code == 413
    assert client.post("/api/v1/inputs", files={"file": ("empty.csv", b"")}).status_code == 422
    assert client.get("/api/v1/artifacts/missing/download").status_code == 404
    with pytest.raises(ValueError):
        client.app.state.store.file("../secret.txt")
    assert not list((client.app.state.store.root / "inputs").iterdir())


def test_invalid_work_is_rejected_before_queue(client):
    tid = target(client)
    requests = [
        {"kind": "design", "target_id": tid, "parameters": {"fixed": {i: "A" for i in range(len(TARGET))}}},
        {"kind": "orthogonal", "target_id": tid, "parameters": {"length": 28}},
        {"kind": "design", "target_id": tid, "parameters": {"n_steps": 0}},
    ]
    for request in requests:
        assert client.post("/api/v1/runs", json=request).status_code == 422
    assert client.post("/api/v1/runs", content=(
        '{"kind":"design","target_id":"' + tid +
        '","parameters":{"t_start":NaN}}'),
        headers={"content-type": "application/json"}).status_code == 422
    assert client.get("/api/v1/runs").json() == []


def test_source_change_prevents_silent_reexecution(client):
    run = submit(client, {"kind": "design", "target_id": target(client),
                          "parameters": {"n_restarts": 1, "n_steps": 10}})
    store = client.app.state.store
    snapshot = run["snapshot"]
    snapshot["provenance"]["source_sha256"] = "changed"
    with store.connect() as db:
        db.execute("UPDATE runs SET snapshot=? WHERE id=?", (dumps(snapshot), run["id"]))
    run_one(store, "source-worker", timeout=30)
    assert store.run(run["id"])["status"] == "failed"
    assert "source changed" in store.run(run["id"])["error"]["message"]


def test_all_pinned_core_design_does_not_hang():
    with pytest.raises(ValueError, match="mutable"):
        design_partner(TARGET, fixed={i: "A" for i in range(len(TARGET))})


@pytest.mark.parametrize("kind", ["structure", "dockprep"])
def test_pdb_upload_to_target_and_worker(client, kind):
    from tests.make_structure import build_dimer
    iid = upload(client, "dimer.pdb", build_dimer(TARGET, start_position="g"))
    target_result = client.post("/api/v1/targets", json={"input_id": iid, "chain": "B"})
    assert target_result.status_code == 201, target_result.text
    assert target_result.json()["chain"] == "B"
    assert target_result.json()["register_source"] == "structure"
    assert target_result.json()["offset"] == 6
    run = submit(client, {"kind": kind, "input_id": iid, "chain": "B"})
    result = finish(client, run)
    assert result["orientation"] == "parallel"
    if kind == "dockprep":
        artifacts = client.get(f"/api/v1/runs/{run['id']}/artifacts").json()
        config = next(a for a in artifacts if a["name"] == "vina.conf")
        text = client.get(f"/api/v1/artifacts/{config['id']}/download").text
        assert "receptor = receptor.pdbqt" in text


def test_export_and_queue_survive_api_restart(client):
    run = submit(client, {"kind": "design", "target_id": target(client), "seed": 42,
                          "parameters": {"n_restarts": 1, "n_steps": 50}})
    with TestClient(create_app(client.app.state.store.root)) as restarted:
        assert restarted.get(f"/api/v1/runs/{run['id']}").json()["status"] == "queued"
    finish(client, run)
    export = submit(client, {"kind": "export", "source_run_id": run["id"]})
    result = finish(client, export)
    assert result["source_run_id"] == run["id"]


def test_schema_upgrade_preserves_data_and_scopes_ids(tmp_path):
    store = Store(tmp_path)
    with sqlite3.connect(store.path) as db:
        db.executescript("""CREATE TABLE entities(id TEXT PRIMARY KEY,kind TEXT,data TEXT);
                            PRAGMA user_version=1;""")
        db.execute("INSERT INTO entities VALUES('default','model',?)", (dumps({"id": "default", "weights": {}}),))
    store.initialize()
    store.put("library", {"members": []}, "default")
    assert store.get("model", "default")["weights"] == {}
    assert store.get("library", "default")["members"] == []


def test_cli_calibration_model_roundtrip(tmp_path, capsys):
    from lz.cli import main
    path, model_path = tmp_path / "data.csv", tmp_path / "model.json"
    path.write_text(calibration_csv())
    assert main(["calibrate", str(path), "--out", str(model_path)]) == 0
    capsys.readouterr()
    model = json.loads(model_path.read_text())
    assert model["tm_intercept"] == pytest.approx(80)
    assert main(["score", TARGET, TARGET, "--weights", str(model_path), "--tm"]) == 0
    output = capsys.readouterr().out
    expected = 80 - 4*score_pair(TARGET, TARGET, model["weights"]).total
    assert f"{expected:.1f} C" in output
    assert "UNCALIBRATED" not in output


def test_frozen_selftest_rejects_missing_icon(tmp_path, monkeypatch):
    import sys
    from lz import gui
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(gui, "_icon_path", lambda: None)
    report = tmp_path / "selftest.txt"
    assert gui.selftest(report) == 1
    assert "FAIL  icon bundled" in report.read_text()


def test_web_client_static_routes_leave_api_and_docs_available(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<html lang="ko"><title>Protein Lab</title></html>')
    (dist / "assets" / "app.js").write_text("console.log('client');")
    with TestClient(create_app(tmp_path / "data", client_dir=dist)) as c:
        assert "Protein Lab" in c.get("/").text
        assert c.get("/assets/app.js").status_code == 200
        assert c.get("/api/v1/health/live").json() == {"status": "ok"}
        assert c.get("/docs").status_code == 200


def test_unbuilt_client_falls_back_to_api_docs(tmp_path):
    with TestClient(create_app(tmp_path / "data", client_dir=tmp_path / "missing")) as c:
        response = c.get("/", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/docs"
