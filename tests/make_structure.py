"""Build ideal coiled-coil PDB files with a KNOWN heptad register.

Testing `lz.structure` against a real PDB entry would be circular in the
worst way: we would be checking the measurement against our own reading of
the literature. Instead we generate coordinates from the Crick
parameterisation, where the register is an INPUT. The ground truth comes
from the geometry, not from the code under test.

Crick (1953) backbone equations for a residue at index t on strand with
superhelical phase phi0 and minor-helix phase phi1:

  x = R0 cos(w0 t + p0) + R1 cos(w0 t + p0) cos(w1 t + p1)
                        - R1 cos(a) sin(w0 t + p0) sin(w1 t + p1)
  y = R0 sin(w0 t + p0) + R1 sin(w0 t + p0) cos(w1 t + p1)
                        + R1 cos(a) cos(w0 t + p0) sin(w1 t + p1)
  z = dz t - R1 sin(a) sin(w1 t + p1)

Why PHI1_FOR_A is what it is
----------------------------
With 3.5 residues per minor-helix turn, w1 = 2*pi/3.5 per residue, so
positions 'a' (t=0) and 'd' (t=3) sit 360 - 3*(360/3.5) = 51.4 degrees apart
on the minor helix. A core layer points at the partner when the minor-helix
phase is 180 degrees (the -R1 cos term pulls the CA towards the superhelical
axis). Straddling 180 symmetrically puts 'a' at 180 + 25.7 and 'd' at
180 - 25.7, so phase of 'a' = 205.7 degrees. That is PHI1_FOR_A, and it
agrees with the Crick angles measured in real parallel dimers (a near +20,
d near -25 degrees relative to the interface).
"""

from __future__ import annotations

import math
from pathlib import Path

R0 = 4.9            # superhelix radius, A
R1 = 2.26           # alpha-helix radius, A
RESIDUES_PER_TURN = 3.5
PITCH = 140.0       # superhelical pitch, A (typical two-stranded coil)
DZ = 1.48           # rise per residue along the superhelical axis, A

W1 = 2 * math.pi / RESIDUES_PER_TURN           # minor helix, +102.86 deg/res
W0 = -2 * math.pi * DZ / PITCH                 # supercoil, left-handed
ALPHA = math.atan2(W0 * R0, DZ)                # pitch angle (negative)

PHI1_FOR_A = math.radians(205.7)  # see module docstring

Vec = tuple[float, float, float]


def _ca(t: int, phi0: float, phi1: float) -> Vec:
    a0 = W0 * t + phi0
    a1 = W1 * t + phi1
    x = (
        R0 * math.cos(a0)
        + R1 * math.cos(a0) * math.cos(a1)
        - R1 * math.cos(ALPHA) * math.sin(a0) * math.sin(a1)
    )
    y = (
        R0 * math.sin(a0)
        + R1 * math.sin(a0) * math.cos(a1)
        + R1 * math.cos(ALPHA) * math.cos(a0) * math.sin(a1)
    )
    z = DZ * t - R1 * math.sin(ALPHA) * math.sin(a1)
    return (x, y, z)


def _superhelix_point(t: int, phi0: float) -> Vec:
    """Point on the minor-helix axis, i.e. the superhelical curve itself."""
    a0 = W0 * t + phi0
    return (R0 * math.cos(a0), R0 * math.sin(a0), DZ * t)


def _cb(t: int, phi0: float, phi1: float) -> Vec:
    """CB placed 1.5 A outward along the CA radial vector.

    A real CB also tilts towards the N-terminus, but the radial component is
    what the interface measurement uses, and this keeps the fixture honest
    about what it does and does not model.
    """
    ca = _ca(t, phi0, phi1)
    axis = _superhelix_point(t, phi0)
    d = (ca[0] - axis[0], ca[1] - axis[1], ca[2] - axis[2])
    n = math.sqrt(sum(c * c for c in d)) or 1.0
    return tuple(ca[i] + 1.5 * d[i] / n for i in range(3))  # type: ignore


THREE = {
    "A": "ALA", "R": "ARG", "N": "ASN", "D": "ASP", "C": "CYS",
    "Q": "GLN", "E": "GLU", "G": "GLY", "H": "HIS", "I": "ILE",
    "L": "LEU", "K": "LYS", "M": "MET", "F": "PHE", "P": "PRO",
    "S": "SER", "T": "THR", "W": "TRP", "Y": "TYR", "V": "VAL",
}


def build_dimer(
    sequence: str,
    start_position: str = "a",
    parallel: bool = True,
    ligand: tuple[str, Vec] | None = None,
) -> str:
    """Return PDB text for a two-stranded coiled coil.

    Args:
        sequence: sequence of BOTH chains (a homodimer).
        start_position: heptad position of residue 1. This is the ground
            truth that `lz.structure.measure_register` must recover.
        parallel: if False, chain B runs the opposite way, which the
            orientation check must detect.
        ligand: optional (residue_name, xyz) HETATM group to embed.

    Returns:
        PDB-format text with CA and CB atoms for two chains.
    """
    offset = "abcdefg".index(start_position)
    # Residue 0 sits at `start_position`, so shift the minor-helix phase so
    # that whichever index lands on 'a' carries PHI1_FOR_A.
    phi1 = PHI1_FOR_A - W1 * (-offset % 7)

    lines: list[str] = []
    serial = 1

    for chain, phi0 in (("A", 0.0), ("B", math.pi)):
        residues = sequence
        indices = range(len(sequence))
        if chain == "B" and not parallel:
            # Keep the coordinates, reverse the direction of the chain: the
            # same helical tube now runs C-to-N relative to chain A.
            residues = sequence[::-1]
            indices = range(len(sequence) - 1, -1, -1)

        for seq_id, t in enumerate(indices, start=1):
            aa = residues[seq_id - 1]
            resname = THREE[aa]
            atoms = [("CA", _ca(t, phi0, phi1))]
            if aa != "G":
                atoms.append(("CB", _cb(t, phi0, phi1)))
            for atom, (x, y, z) in atoms:
                lines.append(
                    f"ATOM  {serial:>5}  {atom:<3}{resname:>4} {chain}"
                    f"{seq_id:>4}    {x:>8.3f}{y:>8.3f}{z:>8.3f}"
                    f"  1.00  0.00           {atom[0]:>2}"
                )
                serial += 1
        lines.append(f"TER   {serial:>5}      {THREE[residues[-1]]:>4} "
                     f"{chain}{len(sequence):>4}")
        serial += 1

    if ligand is not None:
        name, (x, y, z) = ligand
        lines.append(
            f"HETATM{serial:>5}  C1 {name:>4} L   1    "
            f"{x:>8.3f}{y:>8.3f}{z:>8.3f}  1.00  0.00           C"
        )
        serial += 1

    lines.append("END")
    return "\n".join(lines) + "\n"


def write_dimer(path: str | Path, sequence: str, **kwargs) -> Path:
    p = Path(path)
    p.write_text(build_dimer(sequence, **kwargs), encoding="utf-8")
    return p
