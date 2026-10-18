"""Read a coiled-coil structure and measure what phase A otherwise guesses.

The point of accepting a PDB file is not convenience. A structure lets us
MEASURE the heptad register instead of predicting it from sequence: the
residues that actually point into the dimer interface are visible in the
coordinates. Register prediction is the weakest step in the sequence-only
pipeline, so replacing it with a measurement is the single biggest accuracy
win available.

The structure also settles three things sequence cannot:
  - whether the two helices are parallel or antiparallel,
  - where the helical segment actually starts and stops,
  - which ligands, if any, are already bound.

Deliberately dependency-free: a PDB ATOM record is a fixed-column format and
parsing it needs no library. Install Biopython if you want mmCIF.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

Vec = tuple[float, float, float]

# Standard residues plus the modified ones common in coiled-coil crystal
# structures. Selenomethionine in particular appears in most of them.
THREE_TO_ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "MSE": "M",  # selenomethionine
    "SEC": "C", "PYL": "K", "HSD": "H", "HSE": "H", "HSP": "H",
    "CSO": "C", "PTR": "Y", "SEP": "S", "TPO": "T", "MLY": "K",
}

# Waters and the usual crystallisation junk: present in almost every file and
# never the ligand anyone means.
IGNORED_HET = {
    "HOH", "DOD", "WAT", "SO4", "PO4", "GOL", "EDO", "PEG", "MPD",
    "ACT", "CL", "NA", "K", "MG", "CA", "ZN", "TRS", "IMD", "DMS",
    "FMT", "ACY", "NO3", "CIT", "EPE", "BME", "IPA", "PGE", "1PE",
}

# Ideal CA(i)->CA(i+4) distance in an alpha helix is 6.2 A. The window is
# generous enough to tolerate the coiled-coil supercoil and moderate
# refinement error, tight enough to exclude 3-10 helix and extended chain.
HELIX_CA4_MIN = 4.8
HELIX_CA4_MAX = 7.2
MIN_HELIX_LENGTH = 7  # one heptad

# Mean inward-facing cosine at each heptad position in an ideal parallel
# two-stranded coiled coil, measured from Crick-parameterised coordinates
# (see tests/make_structure.py). These come from geometry, not from fitting
# any real structure, and test_structure.py regenerates them to make sure
# they cannot drift away from the generator.
#
# Scoring a register against this whole profile, rather than against the
# mean of a and d alone, is what makes the assignment decisive. The a/d-only
# score nearly ties on real data: a register that mistakes g for a still
# collects the true d leucines plus the g residues, which point roughly
# halfway towards the partner. On 2ZTA -- the canonical GCN4 zipper -- that
# left a margin of 0.098 between the right answer and the wrong one, which
# tripped the "ambiguous geometry" warning on a textbook structure. The
# asymmetry between g (outward-ish but positive) and e (near zero) is the
# information that breaks the tie, and only the full profile uses it.
IDEAL_PROFILE = {
    "a": +0.810, "b": -0.671, "c": -0.578, "d": +0.888,
    "e": +0.174, "f": -0.973, "g": +0.262,
}

# Thresholds for calling a register assignment doubtful.
#
# CALIBRATION IS THIN -- these come from exactly two reference points:
#
#                        fit (r)   margin
#   ideal Crick geometry   0.999    0.370
#   2ZTA (GCN4 zipper)     0.912    0.120
#
# The margin is intrinsically small even for a perfect structure, because
# positions a and d sit only about 51 degrees apart on the minor helix, so a
# register shifted by three or four residues genuinely resembles the right
# one (on 2ZTA the runner-up still scores 0.79 against the winner's 0.91).
# That makes the margin a poor primary signal. The absolute fit separates
# much better, so it carries the warning and the margin only catches a near
# tie. Re-tune both with more real structures before trusting them on
# unusual geometry.
AMBIGUOUS_FIT = 0.60
AMBIGUOUS_MARGIN = 0.05


class StructureError(ValueError):
    """Raised when a structure cannot be read or interpreted."""


@dataclass
class Residue:
    chain: str
    seq_id: int
    icode: str
    name: str
    atoms: dict[str, Vec] = field(default_factory=dict)

    @property
    def one_letter(self) -> str | None:
        return THREE_TO_ONE.get(self.name)

    @property
    def ca(self) -> Vec | None:
        return self.atoms.get("CA")

    @property
    def cb(self) -> Vec | None:
        """CB, or CA for glycine (which has no side chain to point anywhere)."""
        return self.atoms.get("CB") or self.atoms.get("CA")

    @property
    def label(self) -> str:
        return f"{self.name}{self.seq_id}{self.icode.strip()}"


@dataclass
class Ligand:
    """A non-polymer HETATM group found in the file."""

    name: str
    chain: str
    seq_id: int
    n_atoms: int
    centroid: Vec


@dataclass
class HelixSegment:
    """One continuous helical stretch of one chain."""

    chain: str
    residues: list[Residue]

    @property
    def sequence(self) -> str:
        return "".join(r.one_letter or "X" for r in self.residues)

    @property
    def axis(self) -> list[Vec]:
        """Local helix axis points, one per residue (ends extrapolated).

        Each interior point is the centroid of four consecutive CA atoms,
        which cancels the helical oscillation and lands on the axis.
        """
        cas = [r.ca for r in self.residues]
        pts: list[Vec] = []
        for i in range(len(cas)):
            window = [c for c in cas[max(0, i - 1): i + 3] if c is not None]
            pts.append(_centroid(window) if window else cas[i])
        return pts

    @property
    def direction(self) -> Vec:
        """N-to-C unit vector of the segment."""
        ax = self.axis
        return _unit(_sub(ax[-1], ax[0]))

    def __len__(self) -> int:
        return len(self.residues)


@dataclass
class InterfaceAnalysis:
    """What the coordinates say about one helix in a two-helix bundle."""

    segment: HelixSegment
    partner: HelixSegment
    offset: int                 # heptad offset of segment.sequence[0]
    parallel: bool
    register_quality: float     # correlation with the ideal heptad profile
    margin: float               # gap to the runner-up offset
    core_residues: list[tuple[str, Residue, float]]  # (position, res, cosine)

    @property
    def orientation(self) -> str:
        return "parallel" if self.parallel else "ANTIPARALLEL"

    def position(self, i: int) -> str:
        """Heptad position letter of residue `i` of the analysed segment."""
        return "abcdefg"[(self.offset + i) % 7]

    @property
    def register_warning(self) -> str | None:
        """Why this register assignment should be distrusted, or None."""
        if self.register_quality < AMBIGUOUS_FIT:
            return (
                f"register fit is only {self.register_quality:.2f}; this "
                "interface does not look like a canonical parallel coiled "
                "coil, so the heptad assignment is unreliable"
            )
        if self.margin < AMBIGUOUS_MARGIN:
            return (
                f"register margin is only {self.margin:.3f}; two different "
                "heptad assignments fit almost equally well"
            )
        return None

    def report(self) -> str:
        lines = [
            f"chain {self.segment.chain} vs chain {self.partner.chain}",
            f"  length        {len(self.segment)} residues "
            f"({self.segment.residues[0].label}"
            f"-{self.segment.residues[-1].label})",
            f"  sequence      {self.segment.sequence}",
            f"  orientation   {self.orientation}",
            f"  heptad offset {self.offset} "
            f"(first residue at '{'abcdefg'[self.offset]}')",
            f"  register fit  {self.register_quality:.3f} "
            f"(margin {self.margin:.3f})",
            "",
            "  measured core residues (cosine 1.0 = pointing straight at partner):",
        ]
        for pos, res, cos in self.core_residues:
            lines.append(f"    {pos}  {res.label:<10} {cos:+.2f}")
        return "\n".join(lines)


# --- vector helpers (kept local so the core package stays stdlib-only) ------

def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a: Vec) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a: Vec) -> Vec:
    n = _norm(a)
    if n == 0:
        return (0.0, 0.0, 0.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def _centroid(points: list[Vec]) -> Vec:
    n = len(points)
    return (
        sum(p[0] for p in points) / n,
        sum(p[1] for p in points) / n,
        sum(p[2] for p in points) / n,
    )


def _distance(a: Vec, b: Vec) -> float:
    return _norm(_sub(a, b))


def _correlate(observed: list[float], expected: list[float]) -> float:
    """Pearson correlation.

    Correlation rather than a sum of squared differences, because real
    structures show the same profile SHAPE as ideal geometry at a smaller
    amplitude -- 2ZTA's core cosines run about 0.1-0.2 lower than Crick
    coordinates predict. A scale-invariant measure scores the shape and
    ignores that offset; a distance measure would penalise every real
    structure for not being ideal.
    """
    n = len(observed)
    if n < 2:
        return 0.0
    mo = sum(observed) / n
    me = sum(expected) / n
    num = sum((o - mo) * (e - me) for o, e in zip(observed, expected))
    do = math.sqrt(sum((o - mo) ** 2 for o in observed))
    de = math.sqrt(sum((e - me) ** 2 for e in expected))
    if do == 0 or de == 0:
        return 0.0
    return num / (do * de)


# --- parsing ---------------------------------------------------------------

def read_pdb(path: str | Path, model: int = 1) -> tuple[
    dict[str, list[Residue]], list[Ligand]
]:
    """Parse a PDB file into polymer residues by chain, plus ligands.

    Only the first MODEL is read by default; NMR ensembles otherwise stack
    every conformer on top of each other and ruin the geometry.
    """
    p = Path(path)
    if not p.exists():
        raise StructureError(f"file not found: {p}")

    chains: dict[str, list[Residue]] = {}
    het_atoms: dict[tuple[str, str, int], list[Vec]] = {}
    index: dict[tuple[str, int, str], Residue] = {}
    current_model = 1
    in_wanted_model = True

    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        record = line[:6]

        if record == "MODEL ":
            try:
                current_model = int(line[10:14])
            except ValueError:
                current_model += 1
            in_wanted_model = current_model == model
            continue
        if record == "ENDMDL":
            in_wanted_model = False
            continue
        if record not in ("ATOM  ", "HETATM") or not in_wanted_model:
            continue
        if len(line) < 54:
            continue

        altloc = line[16]
        if altloc not in (" ", "A"):
            continue  # keep one conformer only

        resname = line[17:20].strip()
        chain = line[21].strip() or "A"
        try:
            seq_id = int(line[22:26])
            xyz = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
        except ValueError:
            continue
        icode = line[26]
        atom = line[12:16].strip()

        is_polymer = resname in THREE_TO_ONE
        if record == "HETATM" and not is_polymer:
            if resname in IGNORED_HET:
                continue
            het_atoms.setdefault((resname, chain, seq_id), []).append(xyz)
            continue
        if not is_polymer:
            continue

        key = (chain, seq_id, icode)
        res = index.get(key)
        if res is None:
            res = Residue(chain, seq_id, icode, resname)
            index[key] = res
            chains.setdefault(chain, []).append(res)
        res.atoms[atom] = xyz

    if not chains:
        raise StructureError(
            f"no protein residues found in {p.name}. Is it a PDB-format file "
            "with ATOM records? mmCIF is not supported."
        )

    ligands = [
        Ligand(name, chain, seq_id, len(pts), _centroid(pts))
        for (name, chain, seq_id), pts in sorted(het_atoms.items())
    ]
    for residues in chains.values():
        residues.sort(key=lambda r: (r.seq_id, r.icode))
    return chains, ligands


# --- helix detection -------------------------------------------------------

def find_helices(residues: list[Residue]) -> list[HelixSegment]:
    """Find alpha-helical runs using CA(i)->CA(i+4) spacing.

    This is a geometric test, not a hydrogen-bond test like DSSP, but for the
    one thing we need it for -- locating a long continuous helix -- it agrees
    with DSSP and needs no external program.
    """
    usable = [r for r in residues if r.ca is not None and r.one_letter]
    flags = [False] * len(usable)

    for i in range(len(usable) - 4):
        # A chain break makes the i..i+4 window meaningless.
        if usable[i + 4].seq_id - usable[i].seq_id != 4:
            continue
        d = _distance(usable[i].ca, usable[i + 4].ca)
        if HELIX_CA4_MIN <= d <= HELIX_CA4_MAX:
            for j in range(i, i + 5):
                flags[j] = True

    segments: list[HelixSegment] = []
    run: list[Residue] = []
    for res, is_helix in zip(usable, flags):
        if is_helix and (not run or res.seq_id - run[-1].seq_id == 1):
            run.append(res)
            continue
        if len(run) >= MIN_HELIX_LENGTH:
            segments.append(HelixSegment(run[0].chain, run))
        run = [res] if is_helix else []
    if len(run) >= MIN_HELIX_LENGTH:
        segments.append(HelixSegment(run[0].chain, run))

    return segments


# --- register measurement --------------------------------------------------

def _inward_cosines(seg: HelixSegment, partner: HelixSegment) -> list[float]:
    """For each residue: how directly its side chain points at the partner.

    +1 means the CB vector points straight from the local helix axis towards
    the partner helix axis -- the definition of a core position. Around 0
    means tangential (e/g), negative means solvent-facing (b/c/f).
    """
    axis = seg.axis
    partner_axis = partner.axis
    out: list[float] = []

    for i, res in enumerate(seg.residues):
        cb = res.cb
        if cb is None:
            out.append(0.0)
            continue
        radial = _unit(_sub(cb, axis[i]))
        # Nearest point on the partner's axis, so the measurement is local
        # and survives the supercoil twisting along the bundle.
        nearest = min(partner_axis, key=lambda q: _distance(axis[i], q))
        toward = _unit(_sub(nearest, axis[i]))
        out.append(_dot(radial, toward))
    return out


def measure_register(
    seg: HelixSegment, partner: HelixSegment
) -> InterfaceAnalysis:
    """Determine the heptad register of `seg` from the coordinates.

    All seven offsets are tested; the winner is the one whose 'a' and 'd'
    positions genuinely point into the interface. This is a measurement, so
    unlike the sequence-based predictor it cannot be fooled by an unusual
    core -- which is exactly why loading a structure is worth the trouble.
    """
    cosines = _inward_cosines(seg, partner)
    if not cosines:
        raise StructureError("helix segment has no usable side-chain geometry")

    scored: list[tuple[float, int]] = []
    for offset in range(7):
        expected = [
            IDEAL_PROFILE["abcdefg"[(offset + i) % 7]]
            for i in range(len(seg.residues))
        ]
        scored.append((_correlate(cosines, expected), offset))
    scored.sort(reverse=True)

    quality, offset = scored[0]
    margin = quality - scored[1][0]

    core_residues = []
    for i, res in enumerate(seg.residues):
        pos = "abcdefg"[(offset + i) % 7]
        if pos in ("a", "d"):
            core_residues.append((pos, res, cosines[i]))

    parallel = _dot(seg.direction, partner.direction) > 0
    return InterfaceAnalysis(
        segment=seg,
        partner=partner,
        offset=offset,
        parallel=parallel,
        register_quality=quality,
        margin=margin,
        core_residues=core_residues,
    )


def analyse(
    path: str | Path,
    target_chain: str | None = None,
) -> tuple[InterfaceAnalysis | None, list[HelixSegment], list[Ligand]]:
    """Read a structure and work out its coiled-coil geometry.

    Returns:
        (analysis, all_helices, ligands). `analysis` is None when the file
        holds only one helix -- there is then no partner to measure a
        register against, and you must fall back on sequence prediction.
    """
    chains, ligands = read_pdb(path)

    helices: list[HelixSegment] = []
    for residues in chains.values():
        helices.extend(find_helices(residues))
    if not helices:
        raise StructureError(
            "no alpha-helical segment of at least "
            f"{MIN_HELIX_LENGTH} residues found. A leucine zipper should "
            "contain one; check that the file is the structure you meant."
        )
    helices.sort(key=len, reverse=True)

    if target_chain:
        wanted = [h for h in helices if h.chain == target_chain]
        if not wanted:
            available = sorted({h.chain for h in helices})
            raise StructureError(
                f"no helix in chain '{target_chain}'; "
                f"helices found in chain(s): {', '.join(available)}"
            )
        target = wanted[0]
    else:
        target = helices[0]

    others = [h for h in helices if h is not target and h.chain != target.chain]
    if not others:
        return None, helices, ligands

    # Partner = the other chain's helix closest to the target.
    partner = min(
        others,
        key=lambda h: min(
            _distance(a, b) for a in target.axis for b in h.axis
        ),
    )
    return measure_register(target, partner), helices, ligands
