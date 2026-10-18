"""Application services shared by HTTP and the persistent worker."""
import csv
import importlib.metadata
import io
import json
import math
import platform
import secrets
import subprocess
from dataclasses import asdict
from pathlib import Path

from lz.calibration import fit_tm
from lz.design import design_partner
from lz.export import multimer_fasta
from lz.heptad import assign_register
from lz.library import Zipper, load_library, screen
from lz.orthogonal import design_orthogonal_set
from lz.params import DEFAULT_WEIGHTS
from lz.scoring import score_pair
from lz.structure import analyse

from .store import Conflict, Missing, digest, dumps, new_id


def register_data(reg, source=None):
    return {"sequence": reg.sequence, "offset": reg.offset, "positions": reg.positions(),
            "confidence": reg.confidence if math.isfinite(reg.confidence) else None,
            "register_source": source or ("explicit" if math.isnan(reg.confidence) else "sequence"),
            "score": reg.score}


def as_register(target):
    return assign_register(target["sequence"], target["offset"])


def initialize_catalog(store):
    for kind, entity_id, data in (
        ("model", "default", {"name": "Uncalibrated ranking v1", "weights": DEFAULT_WEIGHTS,
                              "tm_slope": None, "tm_intercept": None}),
        ("library", "default", {"name": "Bundled zippers", "members": [asdict(z) for z in load_library()],
                                "verification": "unverified_reference_sequences"}),
    ):
        try:
            store.get(kind, entity_id)
        except Missing:
            import sqlite3
            try:
                store.put(kind, data, entity_id)
            except sqlite3.IntegrityError:
                pass  # Another API/worker initialized this immutable version.


def structure_result(path, chain=None):
    analysis, helices, ligands = analyse(path, chain)
    selected = analysis.segment if analysis else next(
        h for h in helices if chain is None or h.chain == chain)
    reg = assign_register(selected.sequence, analysis.offset if analysis else None)
    warnings = []
    if analysis is None:
        warnings.append("No partner helix; register predicted from sequence.")
    else:
        if not analysis.parallel:
            warnings.append("Antiparallel structure; parallel-dimer scores do not apply.")
        if analysis.register_warning:
            warnings.append(analysis.register_warning)
    return {
        **register_data(reg, "structure" if analysis else "sequence"),
        "chain": selected.chain,
        "residue_range": [selected.residues[0].label, selected.residues[-1].label],
        "orientation": analysis.orientation if analysis else None,
        "register_fit": analysis.register_quality if analysis else None,
        "register_margin": analysis.margin if analysis else None,
        "helices": [{"chain": h.chain, "sequence": h.sequence, "length": len(h)} for h in helices],
        "ligands": [asdict(l) for l in ligands], "warnings": warnings,
    }


def create_target(store, request):
    if request.helix is not None:
        h = request.helix
        result = register_data(assign_register(h.sequence, h.offset))
        result["warnings"] = []
    else:
        item = store.get("input", request.input_id)
        if item["format"] == "pdb":
            result = structure_result(store.file(item["key"]), request.chain)
        elif item["format"] in ("fasta", "fa", "faa", "txt"):
            members = load_library(store.file(item["key"])) if item["format"] != "txt" else []
            if item["format"] == "txt":
                seq = store.file(item["key"]).read_text(encoding="utf-8-sig")
            elif len(members) == 1:
                seq = members[0].sequence
            else:
                raise ValueError("target FASTA must contain exactly one record")
            result = {**register_data(assign_register(seq)), "warnings": []}
        else:
            raise ValueError("target input must be PDB, FASTA or sequence text")
    if len(result["sequence"]) > 500:
        raise ValueError("target exceeds 500 residues")
    return store.put("target", {**result, "name": request.name, "input_id": request.input_id})


def score_result(a, b, model):
    result = asdict(score_pair(a, b, model["weights"]))
    result["score_kind"] = "calibrated_ranking" if model["tm_slope"] is not None else "uncalibrated_ranking"
    result["predicted_tm"] = (model["tm_intercept"] + model["tm_slope"] * result["total"]
                              if model["tm_slope"] is not None else None)
    result["model_id"] = model["id"]
    return result


def screen_result(target, model, library, top):
    reg, weights = as_register(target), model["weights"]
    if target.get("orientation") == "ANTIPARALLEL":
        raise ValueError("parallel-dimer screening does not apply to an antiparallel target")
    if len(reg.sequence) * sum(len(z["sequence"]) for z in library["members"]) > 1000000:
        raise ValueError("synchronous screening budget exceeded; split the library into smaller versions")
    target_self = score_pair(reg, reg, weights).total
    hits = screen(reg, [Zipper(**z) for z in library["members"]], weights)
    return {"specificity_definition": "hetero - candidate_self",
            "both_homodimers_definition": "hetero - min(candidate_self, target_self)",
            "score_kind": "ranking", "warnings": target.get("warnings", []),
            "target_id": target["id"], "model_id": model["id"], "library_id": library["id"],
            "candidates": [{"name": h.zipper.name, "sequence": h.zipper.sequence,
                            "hetero": h.score.total, "candidate_self": h.self_score.total,
                            "target_self": target_self, "specificity": h.specificity,
                            "specificity_both": h.score.total - min(target_self, h.self_score.total),
                            "reference": h.zipper.reference, "recall": h.zipper.recall}
                           for h in hits[:top]]}


def provenance():
    root = Path(__file__).resolve().parent.parent
    files = sorted([*root.joinpath("lz").glob("*.py"), *root.joinpath("server").glob("*.py")])
    code = digest(b"".join(str(p.relative_to(root)).encode() + p.read_bytes() for p in files))
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root,
                                         stderr=subprocess.DEVNULL, timeout=2).decode().strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    packages = {}
    for name in ("fastapi", "pydantic", "numpy", "uvicorn"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    from lz import params
    return {"code_commit": commit, "source_sha256": code,
            "parameter_sha256": digest(Path(params.__file__).read_bytes()),
            "python": platform.python_version(), "dependencies": packages,
            "evaluation_version": "shift-search-v1"}


def submit(store, request, parent_id=None):
    data = request.model_dump()
    snapshot = {"provenance": provenance()}
    if hasattr(request, "target_id") and request.target_id:
        target = store.get("target", request.target_id)
        if target.get("orientation") == "ANTIPARALLEL":
            raise ValueError("this model cannot design for an antiparallel target")
        if len(target["sequence"]) < 14 or len(target["sequence"]) > 100:
            raise ValueError("design target must span 14..100 residues")
        snapshot["target"] = target
    if hasattr(request, "model_id"):
        snapshot["model"] = store.get("model", request.model_id)
    if hasattr(request, "seed"):
        data["seed"] = request.seed if request.seed is not None else secrets.randbits(63)
    if request.kind in ("design", "orthogonal"):
        p = data["parameters"]
        if p["n_restarts"] * p["n_steps"] * p.get("n_pairs", 1) > 400000:
            raise ValueError("requested design exceeds the 400000 work-unit budget")
        if request.kind == "design":
            n = p["length"] or len(snapshot["target"]["sequence"])
            if any(int(i) >= n for i in p["fixed"]) or len(p["fixed"]) >= n:
                raise ValueError("fixed residues must be in range and leave a mutable position")
        elif request.target_id and p["length"] not in (None, len(snapshot["target"]["sequence"])):
            raise ValueError("orthogonal chains must share the target length")
    if hasattr(request, "input_id"):
        item = store.get("input", request.input_id)
        allowed = ("csv",) if request.kind == "calibration" else ("pdb",)
        if item["format"] not in allowed:
            raise ValueError(f"{request.kind} requires {allowed[0]} input")
        snapshot["input"] = item
    if request.kind == "export":
        source = store.run(request.source_run_id)
        if source["status"] != "succeeded" or source["kind"] not in ("design", "orthogonal"):
            raise Conflict("export source must be a successful design or orthogonal run")
        snapshot["source"] = source
        snapshot["result"] = read_result(store, source["id"])
    return store.create_run(data, snapshot, parent_id)


def read_result(store, run_id):
    run = store.run(run_id)
    if run["status"] != "succeeded":
        raise Conflict("results are available only after success")
    return json.loads(store.file(f"runs/{run_id}/result.json").read_text())


def orthogonal_result(result, weights):
    regs = [assign_register(seq, result.offset) for seq in result.sequences]
    search_matrix = result.matrix
    search_margins = [result.margin_for(i) for i in range(result.n_pairs)]
    n = len(regs)
    final, shifts = [[0.] * n for _ in regs], [[0] * n for _ in regs]
    for i in range(n):
        for j in range(i, n):
            score = score_pair(regs[i], regs[j], weights)
            final[i][j] = final[j][i] = score.total
            shifts[i][j], shifts[j][i] = score.shift, -score.shift
    result.matrix = final
    pairs = [{"pair": i, "names": result.names[2*i:2*i+2],
              "cognate": result.cognate_score(i), "margin": result.margin_for(i),
              "worst_competitor": list(result.worst_offtarget(i))}
             for i in range(result.n_pairs)]
    return {"names": result.names, "sequences": result.sequences, "offset": result.offset,
            "matrix": final, "shifts": shifts, "search_matrix": search_matrix,
            "search_margins": search_margins, "search_objective": result.objective,
            "pairs": pairs, "margin_required": result.margin,
            "specificity_definition": "cognate - strongest unwanted interaction involving pair",
            "evaluation": {"passed": result.is_orthogonal(), "policy": "all_allowed_shifts",
                           "scope": "parallel_dimer_ranking_model"}}


def complex_fasta(result):
    """Every unordered pair, INCLUDING all homodimers, for an orthogonal set."""
    lines, complexes = [], []
    names, seqs = result["names"], result["sequences"]
    for i in range(len(names)):
        for j in range(i, len(names)):
            cid = f"complex_{i}_{j}"
            lines += [f">{cid}", f"{seqs[i]}:{seqs[j]}"]
            complexes.append({"id": cid, "chain1": names[i], "chain2": names[j],
                              "intended": i % 2 == 0 and j == i+1,
                              "homodimer": i == j})
    return "\n".join(lines) + "\n", complexes


def write_csv(path, rows):
    if not rows:
        path.write_text("")
        return
    keys = list(rows[0])
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for row in rows:
            w.writerow({k: dumps(v) if isinstance(v, (list, dict)) else v for k, v in row.items()})


def execute(store, run, progress):
    """Executed exclusively in a disposable child process. Publishes no DB result."""
    request, snap = run["request"], run["snapshot"]
    folder = store.file(f"runs/{run['id']}")
    folder.mkdir(parents=True, exist_ok=True)
    kind = request["kind"]
    progress(0, "starting")
    model = None
    if kind == "design":
        params = request["parameters"].copy()
        params["fixed"] = {int(k): v for k, v in params["fixed"].items()}
        designs = design_partner(as_register(snap["target"]), weights=snap["model"]["weights"],
                                 seed=request["seed"], progress=progress, **params)
        rows = [{"name": f"design_{i+1}", "sequence": d.sequence, "offset": d.offset,
                 "objective": d.objective, "hetero": d.hetero.total,
                 "candidate_self": d.partner_self.total, "target_self": d.target_self.total,
                 "specificity": d.specificity,
                 "passed": d.specificity < 0} for i, d in enumerate(designs)]
        result = {"candidates": rows, "specificity_definition": "hetero - min(candidate_self, target_self)",
                  "evaluation": {"passed": any(r["passed"] for r in rows), "scope": "ranking_model"}}
        (folder / "complexes.fasta").write_text(multimer_fasta(
            snap["target"]["sequence"], {r["name"]: r["sequence"] for r in rows}))
        write_csv(folder / "candidates.csv", rows)
    elif kind == "orthogonal":
        result = orthogonal_result(design_orthogonal_set(
            fixed=as_register(snap["target"]) if "target" in snap else None,
            weights=snap["model"]["weights"], seed=request["seed"], progress=progress,
            **request["parameters"]), snap["model"]["weights"])
        fasta, complexes = complex_fasta(result)
        (folder / "complexes.fasta").write_text(fasta)
        (folder / "complexes.json").write_text(dumps(complexes))
        write_csv(folder / "pairs.csv", result["pairs"])
    elif kind in ("structure", "dockprep"):
        path = store.file(snap["input"]["key"])
        result = structure_result(path, request["chain"])
        if kind == "dockprep":
            from lz.dockprep import find_site, write_receptor, write_vina_config
            analysis, _, _ = analyse(path, request["chain"])
            if analysis is None:
                raise ValueError("dockprep requires two helices")
            site = find_site(analysis)
            write_receptor(path, folder / "receptor.pdb")
            write_vina_config(folder / "vina.conf", "receptor.pdbqt", site)
            result["docking_site"] = asdict(site)
            result["warnings"].append("Convert receptor.pdb to receptor.pdbqt; docking has not been run.")
    elif kind == "calibration":
        text = store.file(snap["input"]["key"]).read_text(encoding="utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        if len(rows) > 5000:
            raise ValueError("calibration is limited to 5000 rows")
        if not rows or not {"sequence1", "sequence2", "tm"} <= set(rows[0]):
            raise ValueError("CSV requires sequence1,sequence2,tm columns")
        if any(len(row[k]) > 500 for row in rows for k in ("sequence1", "sequence2")):
            raise ValueError("calibration sequences exceed 500 residues")
        model = {**fit_tm(rows), "id": new_id("model"), "name": f"Calibration {run['id']}",
                 "source_run_id": run["id"], "input_sha256": snap["input"]["sha256"]}
        result = {"model": model}
        (folder / "model.json").write_text(dumps(model))
    elif kind == "export":
        source, result = snap["source"], snap["result"]
        if source["kind"] == "orthogonal":
            fasta, complexes = complex_fasta(result)
            (folder / "complexes.json").write_text(dumps(complexes))
        else:
            fasta = multimer_fasta(source["snapshot"]["target"]["sequence"],
                                   {r["name"]: r["sequence"] for r in result["candidates"]})
        (folder / "complexes.fasta").write_text(fasta)
        result = {"source_run_id": source["id"], "format": "colabfold_colon_fasta"}
    else:
        raise ValueError("unsupported run kind")
    result["warnings"] = list(dict.fromkeys(result.get("warnings", []) +
        snap.get("target", {}).get("warnings", []) +
        (["Model rankings are not measured affinity or experimental validation."]
         if kind in ("design", "orthogonal") else [])))
    (folder / "result.json").write_text(dumps(result), encoding="utf-8")
    artifacts = []
    for path in sorted(folder.iterdir()):
        if path.is_file():
            artifacts.append({"id": new_id("artifact"), "run_id": run["id"],
                              "name": path.name, "key": str(path.relative_to(store.root)),
                              "sha256": digest(path.read_bytes()), "size": path.stat().st_size})
    manifest = {"run_id": run["id"], "request": request, "snapshot": snap, "artifacts": artifacts}
    path = folder / "manifest.json"
    path.write_text(dumps(manifest), encoding="utf-8")
    artifacts.append({"id": new_id("artifact"), "run_id": run["id"], "name": path.name,
                      "key": str(path.relative_to(store.root)), "sha256": digest(path.read_bytes()),
                      "size": path.stat().st_size})
    # The parent only publishes after the child exits successfully.
    (folder / ".completion.json").write_text(dumps({"artifacts": artifacts, "model": model}))
