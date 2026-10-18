"""Heptad register assignment for coiled-coil sequences.

A parallel two-stranded coiled coil repeats every 7 residues (positions
a-g). Positions a and d point into the dimer interface; e and g flank it and
make the interhelical salt bridges; b, c and f are solvent exposed.

Assigning the register means deciding which sequence index is the first 'a'.
There are only 7 possibilities, so we score all of them and take the best.
"""

from __future__ import annotations

from dataclasses import dataclass

from .params import (
    BURIAL,
    CHARGED,
    HEPTAD_POSITIONS,
    HYDROPHOBIC,
)


class RegisterError(ValueError):
    """Raised when a register cannot be assigned to a sequence."""


@dataclass(frozen=True)
class Register:
    """A heptad assignment for one sequence.

    Attributes:
        sequence: the one-letter amino acid sequence.
        offset: index into "abcdefg" of the FIRST residue of `sequence`.
            offset=0 means sequence[0] sits at position 'a'.
        score: register-assignment score (lower is a better coiled coil).
        confidence: gap in score to the runner-up offset, in the same
            units. Below ~0.5 the assignment is ambiguous.
    """

    sequence: str
    offset: int
    score: float
    confidence: float

    def position(self, i: int) -> str:
        """Heptad position letter of residue `i`."""
        return HEPTAD_POSITIONS[(self.offset + i) % 7]

    def positions(self) -> str:
        """Heptad position letter for every residue, as a string."""
        return "".join(self.position(i) for i in range(len(self.sequence)))

    def indices(self, *wanted: str) -> list[int]:
        """Sequence indices sitting at any of the `wanted` heptad positions."""
        want = set(wanted)
        return [i for i in range(len(self.sequence)) if self.position(i) in want]

    def residues_at(self, *wanted: str) -> str:
        return "".join(self.sequence[i] for i in self.indices(*wanted))

    def annotate(self, width: int = 60) -> str:
        """Human-readable sequence/register alignment block."""
        lines = []
        for start in range(0, len(self.sequence), width):
            chunk = slice(start, start + width)
            lines.append(f"{start + 1:>5}  {self.sequence[chunk]}")
            lines.append(f"{'':>5}  {self.positions()[chunk]}")
            lines.append("")
        return "\n".join(lines).rstrip()


def _offset_score(sequence: str, offset: int) -> float:
    """Score one candidate register. Lower is more coiled-coil-like."""
    total = 0.0
    n = 0
    for i, res in enumerate(sequence):
        pos = HEPTAD_POSITIONS[(offset + i) % 7]
        if pos in ("a", "d"):
            # Core positions should be hydrophobic; burial tables already
            # reward that and punish buried charge.
            total += BURIAL[pos].get(res, 0.0)
            n += 1
        elif pos in ("e", "g"):
            # Flanking positions are usually charged in natural zippers.
            if res in CHARGED:
                total -= 0.15
        else:
            # Exposed positions should NOT be hydrophobic.
            if res in HYDROPHOBIC and res != "A":
                total += 0.20
    if n == 0:
        raise RegisterError("sequence too short to contain a core position")
    # Normalise by length so sequences of different lengths are comparable.
    return total / len(sequence) * 7.0


def assign_register(sequence: str, offset: int | None = None) -> Register:
    """Assign a heptad register to `sequence`.

    Args:
        sequence: one-letter amino acid sequence (case insensitive).
        offset: force a particular register instead of predicting one.
            0 puts the first residue at 'a'.

    Returns:
        A `Register`. Check `.confidence` before relying on a prediction;
        sequences shorter than about three heptads are often ambiguous.
    """
    seq = _clean(sequence)
    if len(seq) < 7:
        raise RegisterError(
            f"need at least one full heptad (7 residues), got {len(seq)}"
        )

    if offset is not None:
        if not 0 <= offset < 7:
            raise RegisterError("offset must be in 0..6")
        return Register(seq, offset, _offset_score(seq, offset), float("nan"))

    scored = sorted((_offset_score(seq, o), o) for o in range(7))
    best_score, best_offset = scored[0]
    runner_up = scored[1][0]
    return Register(seq, best_offset, best_score, runner_up - best_score)


def _clean(sequence: str) -> str:
    """Strip whitespace/FASTA artefacts and validate the alphabet."""
    seq = "".join(sequence.split()).upper()
    if not seq:
        raise RegisterError("empty sequence")
    bad = sorted(set(seq) - set("ACDEFGHIKLMNPQRSTVWY"))
    if bad:
        raise RegisterError(f"unknown residue(s): {', '.join(bad)}")
    return seq


def core_layers(reg: Register) -> list[tuple[str, int]]:
    """Core layers in N-to-C order as (position_letter, sequence_index)."""
    return [(reg.position(i), i) for i in reg.indices("a", "d")]


def ge_pairs(reg: Register) -> list[tuple[int, int]]:
    """Intrahelical index pairs (g_index, e_index_of_next_heptad).

    In a parallel dimer, g of heptad n on one chain faces e of heptad n+1 on
    the *other* chain. In linear sequence terms that is i and i+5.
    """
    out = []
    for i in reg.indices("g"):
        j = i + 5
        if j < len(reg.sequence):
            out.append((i, j))
    return out
