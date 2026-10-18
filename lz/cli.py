"""Command line interface: python -m lz <command>."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .design import design_partner
from .export import TRIAGE_NOTES, write_multimer_fasta
from .heptad import RegisterError, assign_register
from .library import load_library, screen
from .orthogonal import DEFAULT_CROSS_MARGIN, design_orthogonal_set
from .params import DEFAULT_WEIGHTS
from .scoring import score_pair
from .structure import StructureError, analyse


def _read_sequence(value: str) -> str:
    """Accept a raw sequence or a path to a file containing one."""
    p = Path(value)
    if p.exists():
        text = p.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if not ln.startswith(">")]
        return "".join(lines)
    return value


def _target(args: argparse.Namespace):
    """Resolve the target helix from --pdb or from a sequence argument.

    A structure wins when both are given: the register is measured from
    coordinates rather than predicted, which is strictly better information.
    """
    pdb = getattr(args, "pdb", None)
    if pdb:
        analysis, helices, ligands = analyse(pdb, getattr(args, "chain", None))
        if analysis is None:
            seg = helices[0]
            reg = assign_register(seg.sequence)
            print(
                f"note: only one helix in {Path(pdb).name} (chain "
                f"{seg.chain}), so there is no partner to measure a register "
                f"against. Falling back to sequence prediction "
                f"(offset {reg.offset}, confidence {reg.confidence:.2f}).\n",
                file=sys.stderr,
            )
            return reg

        print(analysis.report(), file=sys.stderr)
        if not analysis.parallel:
            print(
                "\nWARNING: this bundle is ANTIPARALLEL. Every score below "
                "assumes a PARALLEL dimer, so they do not apply to this "
                "structure. Treat the ranking as meaningless until the "
                "scoring model is extended.",
                file=sys.stderr,
            )
        warning = analysis.register_warning
        if warning:
            print(f"\nWARNING: {warning}.", file=sys.stderr)
        if ligands:
            names = ", ".join(sorted({l.name for l in ligands}))
            print(f"\nligands present in the file: {names}", file=sys.stderr)
        print(file=sys.stderr)
        return assign_register(analysis.segment.sequence, analysis.offset)

    if not getattr(args, "target", None):
        raise SystemExit("error: give a target sequence, or --pdb FILE")
    return assign_register(_read_sequence(args.target))


def cmd_register(args: argparse.Namespace) -> int:
    reg = assign_register(_read_sequence(args.sequence), args.offset)
    print(reg.annotate())
    print()
    print(f"offset      {reg.offset} (first residue sits at '{reg.position(0)}')")
    print(f"score       {reg.score:+.3f}")
    if reg.confidence == reg.confidence:  # not NaN
        verdict = "ambiguous" if reg.confidence < 0.5 else "clear"
        print(f"confidence  {reg.confidence:.3f} ({verdict})")
    print(f"core (a/d)  {reg.residues_at('a', 'd')}")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    s = score_pair(
        _read_sequence(args.helix1),
        _read_sequence(args.helix2),
        _weights(args),
    )
    print(s.report())
    if args.tm:
        model = json.loads(Path(args.weights).read_text(encoding="utf-8")) if args.weights else {}
        if model.get("tm_slope") is not None and model.get("tm_intercept") is not None:
            from .calibration import tm_from_score
            print(f"\napparent Tm  {tm_from_score(s, model):.1f} C  (calibrated; training fit)")
        else:
            print(f"\napparent Tm  {s.predicted_tm:.1f} C  (UNCALIBRATED)")
    return 0


def cmd_pdb(args: argparse.Namespace) -> int:
    """Inspect a structure without scoring anything."""
    analysis, helices, ligands = analyse(args.file, args.chain)

    print(f"helices found: {len(helices)}")
    for h in helices:
        print(
            f"  chain {h.chain}  {len(h):>3} res  "
            f"{h.residues[0].label}-{h.residues[-1].label}  {h.sequence}"
        )
    print()

    if analysis is None:
        print("Only one helix, so the heptad register cannot be measured.")
        print("Pass the sequence to `lz screen` to use the predictor instead.")
    else:
        print(analysis.report())

    if ligands:
        print("\nbound non-polymer groups:")
        for l in ligands:
            print(f"  {l.name:<5} chain {l.chain} {l.seq_id:<5} "
                  f"{l.n_atoms} atoms")
    return 0


def cmd_screen(args: argparse.Namespace) -> int:
    target = _target(args)
    hits = screen(target, load_library(args.library), _weights(args))
    hits = hits[: args.top]

    print(f"{'name':<14}{'hetero':>9}{'self':>9}{'spec':>9}  verdict")
    print("-" * 64)
    for h in hits:
        verdict = "binds" if h.specificity < 0 else "loses to homodimer"
        print(
            f"{h.zipper.name:<14}"
            f"{h.score.total:>+9.2f}"
            f"{h.self_score.total:>+9.2f}"
            f"{h.specificity:>+9.2f}  {verdict}"
        )
    print("\nspec = heterodimer - candidate homodimer; negative is good.")
    print("Scores are uncalibrated rankings, not energies.")

    if args.json:
        payload = [
            {
                "name": h.zipper.name,
                "sequence": h.zipper.sequence,
                "hetero": h.score.total,
                "self": h.self_score.total,
                "specificity": h.specificity,
                "reference": h.zipper.reference,
                "recall": h.zipper.recall,
            }
            for h in hits
        ]
        Path(args.json).write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        print(f"\nwrote {args.json}")
    return 0


def cmd_design(args: argparse.Namespace) -> int:
    target = _target(args)
    designs = design_partner(
        target,
        length=args.length,
        offset=args.offset,
        n_restarts=args.restarts,
        n_steps=args.steps,
        weights=_weights(args),
        seed=args.seed,
    )
    designs = designs[: args.top]

    for i, d in enumerate(designs, 1):
        print(f"--- design {i} ---")
        print(d.summary())
        print()

    ok = [d for d in designs if d.specificity < 0]
    print(f"{len(ok)}/{len(designs)} designs beat the competing homodimers.")
    print("Next step: fold the top designs with the target in AlphaFold-")
    print("Multimer or ColabFold before synthesising anything.")

    if args.fasta:
        lines = []
        for i, d in enumerate(designs, 1):
            lines.append(f">design_{i} objective={d.objective:.2f} "
                         f"spec={d.specificity:.2f}")
            lines.append(d.sequence)
        Path(args.fasta).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nwrote {args.fasta}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Write a ColabFold / AlphaFold-Multimer FASTA for phase C."""
    target_reg = _target(args)
    target = target_reg.sequence
    candidates: dict[str, str] = {}

    if args.candidates:
        for z in load_library(args.candidates):
            candidates[z.name] = z.sequence
    else:
        designs = design_partner(
            target_reg,
            length=args.length,
            n_restarts=args.restarts,
            n_steps=args.steps,
            weights=_weights(args),
            seed=args.seed,
        )
        for i, d in enumerate(designs[: args.top], 1):
            candidates[f"design_{i}"] = d.sequence

    if not candidates:
        print("error: no candidates to export", file=sys.stderr)
        return 1

    out = write_multimer_fasta(args.out, target, candidates)
    n_records = len(candidates) * 2 + 1
    print(f"wrote {out}  ({len(candidates)} candidates, {n_records} complexes)")
    print()
    print(TRIAGE_NOTES)
    return 0


def cmd_dockprep(args: argparse.Namespace) -> int:
    """Box the interface and write docking inputs. Does not dock anything."""
    from .dockprep import find_site, write_receptor, write_vina_config

    analysis, _, ligands = analyse(args.file, args.chain)
    if analysis is None:
        print(
            "error: only one helix in this file, so there is no interface to "
            "box. Docking needs the assembled coiled coil.",
            file=sys.stderr,
        )
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    site = find_site(analysis, padding=args.padding)
    receptor = write_receptor(args.file, out_dir / "receptor.pdb")
    config = write_vina_config(
        out_dir / "vina.conf", receptor, site, args.exhaustiveness
    )

    print(analysis.report())
    print()
    print(f"docking box center  "
          f"{site.center[0]:.2f} {site.center[1]:.2f} {site.center[2]:.2f}")
    print(f"docking box size    "
          f"{site.size[0]:.1f} x {site.size[1]:.1f} x {site.size[2]:.1f} A")
    print(f"interface atoms     {site.n_core_atoms}")
    print(f"hydrophobic core    {site.hydrophobic_fraction:.0%}")
    print()
    print(f"wrote {receptor}")
    print(f"wrote {config}")

    if ligands:
        print("\nNote: this file already contains non-polymer groups "
              f"({', '.join(sorted({l.name for l in ligands}))}). They were "
              "removed from the receptor; check whether any of them occupies "
              "the site you just boxed.")

    print("\nWhat this site looks like:")
    print(site.druggability_note)
    print(
        "\nThis command prepared inputs. It did NOT dock or rank anything, "
        "and `lz` has no scoring function for small molecules. Run Vina or "
        "another engine with your own compound library, then treat the "
        "output as a shortlist for experiment."
    )
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from .gui import main as gui_main

    if args.selftest is not None:
        return gui_main(["--selftest", args.selftest])
    # Explicit empty argv: the GUI entry point parses sys.argv when given
    # nothing, and here sys.argv still holds this subcommand's own words.
    return gui_main([])


def cmd_orthogonal(args: argparse.Namespace) -> int:
    fixed = None
    if args.pdb or args.target:
        fixed = _target(args)

    result = design_orthogonal_set(
        n_pairs=args.pairs,
        length=args.length,
        fixed=fixed,
        n_restarts=args.restarts,
        n_steps=args.steps,
        margin=args.margin,
        weights=_weights(args),
        seed=args.seed,
    )
    print(result.matrix_report())
    print()
    print(result.report())

    if args.fasta:
        Path(args.fasta).write_text(result.to_fasta(), encoding="utf-8")
        print(f"\nwrote {args.fasta}")
    return 0 if result.is_orthogonal() else 1


def cmd_calibrate(args: argparse.Namespace) -> int:
    """Fit and save a complete Tm model, including its scale and intercept."""
    from .calibration import fit_tm

    with open(args.data, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows or not {"sequence1", "sequence2", "tm"} <= set(rows[0]):
        raise ValueError("CSV requires sequence1,sequence2,tm columns")
    try:
        model = fit_tm(rows)
    except ImportError:
        print("calibrate needs numpy: pip install numpy", file=sys.stderr)
        return 1
    metrics = model["metrics"]
    print(f"n = {metrics['n']}   R^2 = {metrics['r2']}   RMSE = {metrics['rmse']:.1f} C")
    print("Training fit only; independent validation is required.")
    print(json.dumps(model, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(model, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


def _weights(args: argparse.Namespace) -> dict[str, float] | None:
    path = getattr(args, "weights", None)
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data = data.get("weights", data)  # Full calibration model or legacy weight-only JSON.
    unknown = set(data) - set(DEFAULT_WEIGHTS)
    if unknown:
        raise SystemExit(f"unknown weight key(s): {', '.join(sorted(unknown))}")
    return data


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lz",
        description="Leucine zipper partner discovery and design.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="start the FastAPI research server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--data-dir", default=None)
    serve.set_defaults(func=cmd_serve)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--weights", help="JSON file of scoring weights (from `lz calibrate`)"
    )

    # Shared by every command that needs a target helix. Either a sequence or
    # a structure; the structure gives a measured register and wins if both
    # are supplied.
    tgt = argparse.ArgumentParser(add_help=False)
    tgt.add_argument("target", nargs="?",
                     help="target sequence, or a FASTA/text file")
    tgt.add_argument("--pdb", help="PDB file of the target coiled coil")
    tgt.add_argument("--chain", help="chain to treat as the target (with --pdb)")

    r = sub.add_parser("register", parents=[common],
                       help="assign the heptad register of one helix")
    r.add_argument("sequence", help="sequence, or path to a FASTA/text file")
    r.add_argument("--offset", type=int, help="force an offset (0 = 'a')")
    r.set_defaults(func=cmd_register)

    s = sub.add_parser("score", parents=[common],
                       help="score two helices as a parallel dimer")
    s.add_argument("helix1")
    s.add_argument("helix2")
    s.add_argument("--tm", action="store_true", help="also print apparent Tm")
    s.set_defaults(func=cmd_score)

    pdb = sub.add_parser("pdb", help="inspect a structure: helices, register, "
                                     "orientation, bound ligands")
    pdb.add_argument("file", help="PDB file")
    pdb.add_argument("--chain", help="chain to treat as the target")
    pdb.set_defaults(func=cmd_pdb)

    sc = sub.add_parser("screen", parents=[common, tgt],
                        help="rank a library of known zippers against a target")
    sc.add_argument("--library", help="JSON or FASTA library file")
    sc.add_argument("--top", type=int, default=20)
    sc.add_argument("--json", help="write results to this JSON file")
    sc.set_defaults(func=cmd_screen)

    d = sub.add_parser("design", parents=[common, tgt],
                       help="design new partner helices for a target")
    d.add_argument("--length", type=int, help="partner length (default: target)")
    d.add_argument("--offset", type=int, default=0)
    d.add_argument("--restarts", type=int, default=8)
    d.add_argument("--steps", type=int, default=4000)
    d.add_argument("--top", type=int, default=5)
    d.add_argument("--seed", type=int, help="RNG seed for reproducibility")
    d.add_argument("--fasta", help="write designs to this FASTA file")
    d.set_defaults(func=cmd_design)

    e = sub.add_parser("export", parents=[common, tgt],
                       help="write a ColabFold/AlphaFold-Multimer FASTA")
    e.add_argument("--out", default="complexes.fasta")
    e.add_argument("--candidates",
                   help="library file to export instead of designing new ones")
    e.add_argument("--length", type=int)
    e.add_argument("--restarts", type=int, default=8)
    e.add_argument("--steps", type=int, default=4000)
    e.add_argument("--top", type=int, default=5)
    e.add_argument("--seed", type=int)
    e.set_defaults(func=cmd_export)

    g = sub.add_parser("gui", help="open the desktop app")
    g.add_argument("--selftest", metavar="REPORT",
                   help="verify a build headlessly and write a report file "
                        "instead of opening the window")
    g.set_defaults(func=cmd_gui)

    o = sub.add_parser("orthogonal", parents=[common, tgt],
                       help="design a set of mutually orthogonal pairs")
    o.add_argument("--pairs", type=int, default=2)
    o.add_argument("--length", type=int)
    o.add_argument("--restarts", type=int, default=4)
    o.add_argument("--steps", type=int, default=6000)
    o.add_argument("--margin", type=float, default=DEFAULT_CROSS_MARGIN,
                   help="separation a cognate pair must achieve "
                        f"(default {DEFAULT_CROSS_MARGIN})")
    o.add_argument("--seed", type=int)
    o.add_argument("--fasta", help="write all chains to this FASTA file")
    o.set_defaults(func=cmd_orthogonal)

    dp = sub.add_parser("dockprep",
                        help="box the interface and write AutoDock Vina "
                             "inputs (does not dock)")
    dp.add_argument("file", help="PDB file of the assembled coiled coil")
    dp.add_argument("--chain", help="chain to treat as the target")
    dp.add_argument("--out-dir", default="docking")
    dp.add_argument("--padding", type=float, default=5.0,
                    help="A of padding around the interface (default 5)")
    dp.add_argument("--exhaustiveness", type=int, default=16)
    dp.set_defaults(func=cmd_dockprep)

    c = sub.add_parser("calibrate",
                       help="fit scoring weights to measured Tm values")
    c.add_argument("data", help="CSV with columns sequence1,sequence2,tm")
    c.add_argument("--out", help="write fitted weights to this JSON file")
    c.set_defaults(func=cmd_calibrate)

    return p


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn
    from server.main import create_app

    uvicorn.run(create_app(args.data_dir), host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (RegisterError, StructureError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
