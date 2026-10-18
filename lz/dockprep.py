"""Prepare a coiled-coil structure for small-molecule docking.

Read this before using it
-------------------------
This module does NOT rank small molecules, and nothing else in `lz` does
either. Ranking ligands against a protein requires a docking engine
(AutoDock Vina, Smina, Glide, rDock) and a compound library. What this
module does is the fiddly, error-prone part that sits in front of that: find
the coiled-coil interface in the coordinates, put a correctly sized box
around it, and write a clean receptor plus a ready-to-run config.

A harder truth about the target
-------------------------------
A leucine zipper interface is close to a worst case for a small molecule. It
is a long, shallow, solvent-exposed hydrophobic stripe with no enclosed
pocket, which is the textbook description of an "undruggable"
protein-protein interface. Docking scores on a surface like this are
dominated by how much greasy surface a compound can smear over, so they
reward large lipophilic molecules and correlate poorly with real binding.
Expect a high false-positive rate and treat any hit list as a shortlist for
experiment, never as an answer.

If the goal is to link two proteins together, a designed partner HELIX is
the far better tool, and `lz design` produces those with a scoring model
that suits the target geometry. Dock small molecules only if the goal is
specifically to DISRUPT a zipper rather than to use one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .params import HYDROPHOBIC
from .structure import (
    InterfaceAnalysis,
    StructureError,
    Vec,
    _centroid,
    _distance,
)

MIN_BOX_EDGE = 18.0   # Vina needs room to place a ligand at all
DEFAULT_PADDING = 5.0


@dataclass
class DockingSite:
    """A docking box covering a coiled-coil interface."""

    center: Vec
    size: Vec
    n_core_atoms: int
    hydrophobic_fraction: float
    groove_length: float

    @property
    def druggability_note(self) -> str:
        """A blunt, rule-based read on what this site is like."""
        notes = []
        if self.hydrophobic_fraction > 0.7:
            notes.append(
                "The interface is strongly hydrophobic "
                f"({self.hydrophobic_fraction:.0%} of core residues). Docking "
                "will favour large greasy compounds that are unlikely to be "
                "selective or soluble."
            )
        if self.groove_length > 25.0:
            notes.append(
                f"The groove is {self.groove_length:.0f} A long and shallow "
                "rather than pocket-like. No single small molecule covers "
                "that much interface; a peptide does."
            )
        if max(self.size) > 30.0:
            notes.append(
                "The box is large, so docking will be slow and the scores "
                "noisy. Consider splitting it into overlapping sub-boxes."
            )
        if not notes:
            notes.append(
                "The site is unusually compact for a coiled coil, which is "
                "mildly encouraging. Still confirm any hit experimentally."
            )
        return "\n".join(f"  - {n}" for n in notes)


# A residue counts as lining the interface when its CB comes this close to
# the opposite helix's axis.
INTERFACE_CUTOFF = 10.0


def _interface_atoms(segment, other_axis: list[Vec]) -> list[Vec]:
    """Atoms of residues that line the interface, for ONE helix."""
    atoms: list[Vec] = []
    for res in segment.residues:
        cb = res.cb
        if cb is None:
            continue
        if min(_distance(cb, p) for p in other_axis) < INTERFACE_CUTOFF:
            atoms.extend(res.atoms.values())
    return atoms


def find_site(
    analysis: InterfaceAnalysis, padding: float = DEFAULT_PADDING
) -> DockingSite:
    """Box the interface lining of BOTH helices.

    Both chains must be selected by the same criterion. An earlier version
    took only the target's measured core residues but every near residue of
    the partner, which pulled the box centre about 2 A off the groove and
    towards the partner helix -- enough to bias every docking run done with
    it.
    """
    atoms = _interface_atoms(analysis.segment, analysis.partner.axis)
    atoms += _interface_atoms(analysis.partner, analysis.segment.axis)
    if not atoms:
        raise StructureError("no interface atoms found to box")

    hydrophobic = sum(
        1 for _, res, _ in analysis.core_residues
        if (res.one_letter or "X") in HYDROPHOBIC
    )
    total = len(analysis.core_residues)
    partner_axis = analysis.partner.axis

    center = _centroid(atoms)
    size = tuple(  # type: ignore[assignment]
        max(
            MIN_BOX_EDGE,
            max(a[i] for a in atoms) - min(a[i] for a in atoms) + 2 * padding,
        )
        for i in range(3)
    )
    groove = _distance(partner_axis[0], partner_axis[-1])

    return DockingSite(
        center=center,
        size=size,
        n_core_atoms=len(atoms),
        hydrophobic_fraction=hydrophobic / total if total else 0.0,
        groove_length=groove,
    )


def write_receptor(source: str | Path, out: str | Path) -> Path:
    """Copy polymer atoms only, dropping ligands, waters and alt conformers.

    Line-level filtering rather than re-serialising the parsed structure, so
    side-chain atoms, occupancies and element columns survive untouched --
    docking engines need all of them.
    """
    kept: list[str] = []
    in_first_model = True
    for line in Path(source).read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        if line[:6] == "MODEL ":
            in_first_model = not kept
            continue
        if line[:6] == "ENDMDL":
            in_first_model = False
            continue
        if line[:6] != "ATOM  " or not in_first_model:
            continue
        if len(line) > 16 and line[16] not in (" ", "A"):
            continue
        kept.append(line)

    if not kept:
        raise StructureError(f"no ATOM records to write from {source}")
    kept.append("END")
    p = Path(out)
    p.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return p


def write_vina_config(
    out: str | Path,
    receptor: str | Path,
    site: DockingSite,
    exhaustiveness: int = 16,
) -> Path:
    """Write an AutoDock Vina config file for the boxed interface."""
    cx, cy, cz = site.center
    sx, sy, sz = site.size
    text = f"""\
# AutoDock Vina configuration, generated by `lz dockprep`.
#
# The box covers the coiled-coil interface measured from the structure.
# Convert the receptor to PDBQT first, e.g.
#     obabel {Path(receptor).name} -O receptor.pdbqt -xr
# then run
#     vina --config {Path(out).name} --ligand LIGAND.pdbqt --out poses.pdbqt
#
# Read the caveats in lz/dockprep.py before believing any score this
# produces. A coiled-coil groove is a hard, false-positive-prone site.

receptor = {Path(receptor).name}

center_x = {cx:.3f}
center_y = {cy:.3f}
center_z = {cz:.3f}

size_x = {sx:.1f}
size_y = {sy:.1f}
size_z = {sz:.1f}

exhaustiveness = {exhaustiveness}
num_modes = 9
"""
    p = Path(out)
    p.write_text(text, encoding="utf-8")
    return p
