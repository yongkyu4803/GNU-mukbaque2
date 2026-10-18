"""De novo design of a partner helix for a given target helix.

The objective is not simply "bind the target tightly". A partner that binds
tightly but also homodimerises, or that merely re-creates the target's own
homodimer, is useless in a protein-linkage system. So the designer minimises

    objective = E(hetero)
              + w_self   * max(0, E(hetero) + margin - E(partner homodimer))
              + w_target * max(0, E(hetero) + margin - E(target homodimer))

The two added terms are negative design: each penalises a homodimer that is
still competitive with the designed heterodimer in solution. They are hinges
rather than linear terms, so once a competitor is beaten by `margin` there is
nothing further to gain from degrading it and the search goes back to
improving the real interface. This is the same logic used to build orthogonal
coiled-coil sets experimentally.

Search is simulated annealing over position-restricted residue alphabets --
exhaustive enumeration is impossible (20^30), and the energy landscape is
rugged enough that greedy descent gets stuck.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .heptad import Register, assign_register
from .params import DEFAULT_WEIGHTS, HEPTAD_POSITIONS, SPECIFICITY_MARGIN
from .scoring import PairScore, score_pair

# Which residues the designer may place at each heptad position. Restricting
# the alphabet encodes design rules directly and shrinks the search space by
# many orders of magnitude.
ALPHABET = {
    "a": "ILVNAM",      # core; N available for dimer specificity
    "b": "EKQARS",      # exposed, helix-favourable, soluble
    "c": "EKQARS",
    "d": "LMAIV",       # core; Leu strongly preferred
    "e": "EKQR",        # interhelical electrostatics
    "f": "EKQARSG",     # exposed
    "g": "EKQR",        # interhelical electrostatics
}


@dataclass
class Design:
    """One designed partner sequence and its scores."""

    sequence: str
    offset: int
    objective: float
    hetero: PairScore
    partner_self: PairScore
    target_self: PairScore

    @property
    def specificity(self) -> float:
        """Margin over the best competing homodimer (negative is good)."""
        return self.hetero.total - min(
            self.partner_self.total, self.target_self.total
        )

    def register(self) -> Register:
        return assign_register(self.sequence, self.offset)

    def summary(self) -> str:
        return (
            f"{self.sequence}\n"
            f"  objective     {self.objective:+.2f}\n"
            f"  heterodimer   {self.hetero.total:+.2f}\n"
            f"  partner self  {self.partner_self.total:+.2f}\n"
            f"  target self   {self.target_self.total:+.2f}\n"
            f"  specificity   {self.specificity:+.2f}  "
            f"({'OK' if self.specificity < 0 else 'FAILS: homodimer wins'})"
        )


def _objective(
    target: Register,
    partner: Register,
    target_self: PairScore,
    weights: dict[str, float],
) -> tuple[float, PairScore, PairScore]:
    hetero = score_pair(target, partner, weights)
    partner_self = score_pair(partner, partner, weights)
    obj = (
        hetero.total
        + weights["self_competition"] * _hinge(hetero.total, partner_self.total)
        + weights["target_competition"] * _hinge(hetero.total, target_self.total)
    )
    return obj, hetero, partner_self


def _hinge(hetero: float, competitor: float) -> float:
    """Penalty for a homodimer that is still competitive with the target pair.

    Zero once `competitor` is worse than `hetero` by SPECIFICITY_MARGIN, so
    there is nothing to gain from degrading it further. See the note on
    SPECIFICITY_MARGIN in params.py for why this must not be linear.
    """
    return max(0.0, hetero + SPECIFICITY_MARGIN - competitor)


def _seed(length: int, offset: int, rng: random.Random) -> str:
    return "".join(
        rng.choice(ALPHABET[HEPTAD_POSITIONS[(offset + i) % 7]])
        for i in range(length)
    )


def design_partner(
    target: str | Register,
    length: int | None = None,
    offset: int = 0,
    n_restarts: int = 8,
    n_steps: int = 4000,
    t_start: float = 1.2,
    t_end: float = 0.02,
    weights: dict[str, float] | None = None,
    seed: int | None = None,
    fixed: dict[int, str] | None = None,
    progress=None,
) -> list[Design]:
    """Design partner helices for `target`, best objective first.

    Args:
        target: the helix to bind.
        length: partner length in residues; defaults to the target's length.
        offset: heptad offset of the partner's first residue (0 = 'a').
        n_restarts: independent annealing runs. More restarts, more diversity.
        n_steps: moves per run.
        t_start, t_end: annealing temperature schedule (geometric).
        weights: override `params.DEFAULT_WEIGHTS`.
        seed: RNG seed for reproducible designs.
        fixed: residues to pin, as {sequence_index: residue}.

    Returns:
        One `Design` per restart, sorted by objective. Check `.specificity`
        on each -- a design with specificity >= 0 is predicted to lose to a
        homodimer and should be discarded.
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    treg = target if isinstance(target, Register) else assign_register(target)
    n = length or len(treg.sequence)
    if n < 14:
        raise ValueError("partner must be at least two heptads (14 residues)")
    rng = random.Random(seed)
    pinned = dict(fixed or {})
    if n_restarts < 1 or n_steps < 1 or t_start <= 0 or t_end <= 0:
        raise ValueError("restarts, steps and temperatures must be positive")
    if any(i < 0 or i >= n or len(r) != 1 or r not in "ACDEFGHIKLMNPQRSTVWY"
           for i, r in pinned.items()):
        raise ValueError("invalid fixed residue or position")
    mutable = [i for i in range(n) if i not in pinned]
    if not mutable:
        raise ValueError("at least one residue must be mutable")

    target_self = score_pair(treg, treg, w)
    results: list[Design] = []

    for restart in range(n_restarts):
        seq = list(_seed(n, offset, rng))
        for i, r in pinned.items():
            seq[i] = r
        preg = assign_register("".join(seq), offset)
        obj, hetero, pself = _objective(treg, preg, target_self, w)

        best = (obj, "".join(seq), hetero, pself)
        cooling = (t_end / t_start) ** (1.0 / max(n_steps - 1, 1))
        temp = t_start

        for step in range(n_steps):
            if progress is not None and step % 100 == 0:
                progress((restart * n_steps + step) / (n_restarts * n_steps),
                         f"restart {restart + 1}/{n_restarts}, step {step}/{n_steps}")
            i = rng.randrange(n)
            while i in pinned:
                i = rng.randrange(n)
            pos = HEPTAD_POSITIONS[(offset + i) % 7]
            old = seq[i]
            new = rng.choice(ALPHABET[pos])
            if new == old:
                temp *= cooling
                continue

            seq[i] = new
            cand = assign_register("".join(seq), offset)
            cand_obj, cand_hetero, cand_self = _objective(
                treg, cand, target_self, w
            )

            delta = cand_obj - obj
            if delta <= 0 or rng.random() < _boltzmann(delta, temp):
                obj, hetero, pself = cand_obj, cand_hetero, cand_self
                if obj < best[0]:
                    best = (obj, "".join(seq), hetero, pself)
            else:
                seq[i] = old
            temp *= cooling

        results.append(
            Design(
                sequence=best[1],
                offset=offset,
                objective=best[0],
                hetero=best[2],
                partner_self=best[3],
                target_self=target_self,
            )
        )

    results.sort(key=lambda d: d.objective)
    if progress is not None:
        progress(1.0, "design complete")
    return _dedupe(results)


def _boltzmann(delta: float, temp: float) -> float:
    if temp <= 0:
        return 0.0
    x = -delta / temp
    if x < -700:  # avoid underflow in exp
        return 0.0
    import math

    return math.exp(x)


def _dedupe(designs: list[Design]) -> list[Design]:
    """Drop exact duplicate sequences, keeping the best-scoring copy."""
    seen: set[str] = set()
    out = []
    for d in designs:
        if d.sequence in seen:
            continue
        seen.add(d.sequence)
        out.append(d)
    return out
