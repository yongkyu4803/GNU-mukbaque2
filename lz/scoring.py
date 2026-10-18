"""Pairwise interaction scoring for parallel two-stranded coiled coils.

The model is deliberately a transparent sum of three physically separable
terms, so that any single number can be traced back to a residue pair:

    score = w_core * E_core + w_elec * E_elec + w_helix * E_helix

All terms are in kcal/mol-like units with NEGATIVE = stabilising. The weights
and the underlying tables live in `params.py`; see the provenance note there.
The absolute values are not calibrated energies. Use them to RANK, and run
`lz calibrate` on your own Tm data before quoting a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .heptad import Register, assign_register
from .params import (
    BURIAL,
    BURIED_LIKE_CHARGE,
    CHARGED,
    DEFAULT_WEIGHTS,
    HELIX_PROPENSITY,
    IDEAL_LAYER_VOLUME,
    NEGATIVE,
    PAIR_BONUS,
    POLAR,
    POLAR_CHARGE_CONTACT,
    POSITIVE,
    SALT_BRIDGE_ATTRACT,
    SALT_BRIDGE_REPEL,
    TM_INTERCEPT,
    TM_SLOPE,
    UNSATISFIED_POLAR,
    VOLUME,
    VOLUME_PENALTY,
)

# Two heptads' worth of a/d layers. Below this there is not enough interface
# to say anything about a coiled coil, so scoring refuses rather than guesses.
MIN_OVERLAP_LAYERS = 4

# How far the two chains may slide out of maximal registration, in heptads.
# Without this bound, `score_pair` would "rescue" a badly matched pair by
# sliding it until only a couple of good layers remained -- a shorter but
# cleaner interface can out-score a full-length bad one, which made
# core-disrupting mutations look harmless. Real two-stranded coiled coils
# slip by at most about one heptad.
MAX_SLIP_HEPTADS = 1


@dataclass
class Contact:
    """One scored residue-residue interaction across the interface."""

    kind: str          # "core" or "elec"
    position: str      # "a", "d", or "g-e'"
    heptad: int
    res1: str
    res2: str
    energy: float

    def __str__(self) -> str:
        return (
            f"{self.kind:<4} h{self.heptad:<2} {self.position:<4} "
            f"{self.res1}-{self.res2}  {self.energy:+.2f}"
        )


@dataclass
class PairScore:
    """Result of scoring two helices as a parallel dimer."""

    total: float
    core: float
    electrostatic: float
    helix: float
    shift: int
    n_layers: int
    contacts: list[Contact] = field(default_factory=list)

    @property
    def predicted_tm(self) -> float:
        """Apparent Tm in degC. Meaningless until the model is calibrated."""
        return TM_INTERCEPT + TM_SLOPE * self.total

    def report(self) -> str:
        lines = [
            f"total        {self.total:+.2f}",
            f"  core       {self.core:+.2f}",
            f"  electro    {self.electrostatic:+.2f}",
            f"  helix      {self.helix:+.2f}",
            f"  layers     {self.n_layers} (heptad shift {self.shift:+d})",
            "",
            "contacts:",
        ]
        lines += ["  " + str(c) for c in self.contacts]
        return "\n".join(lines)


def _layer_map(reg: Register) -> dict[tuple[int, str], str]:
    """Map (heptad_number, position_letter) -> residue."""
    out = {}
    for i, res in enumerate(reg.sequence):
        abs_pos = reg.offset + i
        out[(abs_pos // 7, reg.position(i))] = res
    return out


def core_layer_energy(pos: str, r1: str, r2: str) -> float:
    """Energy of one a/a' or d/d' layer."""
    # Additive, never substitutive: burial of both side chains, then a
    # pair-specific correction. See the PAIR_BONUS comment in params.py.
    e = BURIAL[pos].get(r1, 0.0) + BURIAL[pos].get(r2, 0.0)
    e += PAIR_BONUS.get((pos, frozenset({r1, r2})), 0.0)

    # Packing complementarity: the two side chains must jointly fill the core.
    deviation = abs(VOLUME[r1] + VOLUME[r2] - IDEAL_LAYER_VOLUME)
    e += VOLUME_PENALTY * deviation

    # Two like charges buried together is the single worst thing you can do.
    if (r1 in POSITIVE and r2 in POSITIVE) or (r1 in NEGATIVE and r2 in NEGATIVE):
        e += BURIED_LIKE_CHARGE

    # A buried polar residue facing a pure hydrophobe leaves an unsatisfied
    # hydrogen bond. Facing another polar residue, it is satisfied.
    p1, p2 = r1 in POLAR or r1 in "NQ", r2 in POLAR or r2 in "NQ"
    if p1 != p2:
        e += UNSATISFIED_POLAR

    return e


def ge_energy(g_res: str, e_res: str) -> float:
    """Energy of one interhelical g <-> e' pair."""
    if g_res in CHARGED and e_res in CHARGED:
        same = (g_res in POSITIVE) == (e_res in POSITIVE)
        return SALT_BRIDGE_REPEL if same else SALT_BRIDGE_ATTRACT
    if (g_res in CHARGED and e_res in POLAR) or (
        e_res in CHARGED and g_res in POLAR
    ):
        return POLAR_CHARGE_CONTACT
    return 0.0


def _helix_energy(seq1: str, seq2: str) -> float:
    """Mean helix propensity cost of both chains (Pace & Scholtz, Ala = 0)."""
    both = seq1 + seq2
    if not both:
        return 0.0
    return sum(HELIX_PROPENSITY.get(r, 0.5) for r in both) / len(both)


def _score_at_shift(
    m1: dict[tuple[int, str], str],
    m2: dict[tuple[int, str], str],
    shift: int,
) -> tuple[float, float, int, list[Contact]]:
    """Core + electrostatic energy with chain 2 slid by `shift` heptads."""
    core = 0.0
    elec = 0.0
    contacts: list[Contact] = []
    n_layers = 0

    for (h, pos), r1 in sorted(m1.items()):
        if pos not in ("a", "d"):
            continue
        r2 = m2.get((h + shift, pos))
        if r2 is None:
            continue
        e = core_layer_energy(pos, r1, r2)
        core += e
        n_layers += 1
        contacts.append(Contact("core", pos, h, r1, r2, e))

    # g of chain 1, heptad h  <->  e of chain 2, heptad h+1
    for (h, pos), r1 in sorted(m1.items()):
        if pos != "g":
            continue
        r2 = m2.get((h + shift + 1, "e"))
        if r2 is None:
            continue
        e = ge_energy(r1, r2)
        if e:
            elec += e
            contacts.append(Contact("elec", "g-e'", h, r1, r2, e))

    # ...and the reciprocal set: g of chain 2 <-> e of chain 1.
    for (h, pos), r2 in sorted(m2.items()):
        if pos != "g":
            continue
        r1 = m1.get((h - shift + 1, "e"))
        if r1 is None:
            continue
        e = ge_energy(r2, r1)
        if e:
            elec += e
            contacts.append(Contact("elec", "e-g'", h, r1, r2, e))

    return core, elec, n_layers, contacts


def score_pair(
    helix1: str | Register,
    helix2: str | Register,
    weights: dict[str, float] | None = None,
    shift: int | None = None,
) -> PairScore:
    """Score two helices as a parallel, in-register two-stranded coiled coil.

    The relative heptad shift between the two chains is optimised, so the
    sequences do not need to be the same length or start at the same point.

    Args:
        helix1, helix2: sequences, or `Register` objects if you want to pin
            the heptad assignment yourself.
        weights: override `params.DEFAULT_WEIGHTS`.
        shift: pin the relative heptad shift instead of searching for it.
            Pass 0 when both helices share a length and heptad offset, as in
            a designed set -- the search is then a pure waste, and it
            dominates the cost of anything that scores a whole matrix of
            pairs repeatedly.

    Returns:
        A `PairScore`; more negative means a better predicted partner.
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    reg1 = helix1 if isinstance(helix1, Register) else assign_register(helix1)
    reg2 = helix2 if isinstance(helix2, Register) else assign_register(helix2)

    m1, m2 = _layer_map(reg1), _layer_map(reg2)
    span1 = max(h for h, _ in m1) + 1
    span2 = max(h for h, _ in m2) + 1

    # Score every shift first, then decide which ones were allowed to
    # compete. The overlap floor is measured against the best overlap
    # actually achievable for this pair, because partial heptads at either
    # terminus mean the theoretical maximum is often unreachable.
    candidates = [shift] if shift is not None else range(-span2, span1 + 1)
    scored = [(s, *_score_at_shift(m1, m2, s)) for s in candidates]
    best_overlap = max((n for _, _, _, n, _ in scored), default=0)
    floor = max(MIN_OVERLAP_LAYERS, best_overlap - 2 * MAX_SLIP_HEPTADS)

    best: tuple[float, float, float, int, int, list[Contact]] | None = None
    for s, core, elec, n_layers, contacts in scored:
        if n_layers < floor:
            continue
        # Longer interfaces are genuinely more stable, so do NOT normalise
        # by length here; the raw sum is the physical quantity.
        subtotal = w["core"] * core + w["electrostatic"] * elec
        if best is None or subtotal < best[0]:
            best = (subtotal, core, elec, s, n_layers, contacts)

    if best is None:
        raise ValueError(
            f"interface too small to score: best overlap is {best_overlap} "
            f"core layers, need {MIN_OVERLAP_LAYERS}. Both helices must span "
            "at least two heptads."
        )

    subtotal, core, elec, best_shift, n_layers, contacts = best
    helix = _helix_energy(reg1.sequence, reg2.sequence)
    total = subtotal + w["helix"] * helix
    return PairScore(total, core, elec, helix, best_shift, n_layers, contacts)
