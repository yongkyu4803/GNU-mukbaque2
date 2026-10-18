"""Design a set of coiled-coil pairs that do not talk to each other.

A single designed partner is rarely enough. A protein-linkage system usually
needs several pairs working side by side in the same cell or the same tube:
A must find A', B must find B', and A must NOT find B'. A set with that
property is called orthogonal.

Orthogonality is not a property of any one pair, so it cannot be obtained by
designing pairs one at a time and hoping. With K pairs there are 2K helices
and K(2K-1) possible interactions, of which only K are wanted. Every one of
the rest -- the off-diagonal heterodimers and every homodimer -- is a
competing state, and the design has to beat all of them at once.

So the whole set is optimised together against the full interaction matrix:

    objective = sum over cognate pairs of  E(A_i, B_i)
              + w_cross * sum over every non-cognate interaction of
                    hinge(E of the cognate pair that it competes with)

Each hinge is max(0, E_cognate + margin - E_offtarget), the same shape used
in `design.py` and for the same reason: once an off-target is beaten by the
margin, further suppressing it must stop earning credit, or the search
abandons the real interfaces to chase it.

The dominant lever the optimiser finds is charge. Making pair A acidic-basic
and pair B basic-acidic at the g and e positions suppresses the A/B' cross
terms while leaving both cognate pairs intact. That is exactly how
orthogonal sets are built experimentally.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .design import ALPHABET, _hinge
from .heptad import Register, assign_register
from .params import DEFAULT_WEIGHTS, HEPTAD_POSITIONS
from .scoring import score_pair

# Both chains of every designed pair share a length and heptad offset, so
# the aligned registration is always shift 0 and searching for it is waste.
FIXED_SHIFT = 0

# How far a cognate pair must beat every off-target before the penalty on
# that off-target switches off.
#
# This default is 3.0, not the 1.0 that `design.py` uses for a lone pair,
# and the difference is not cosmetic. Measured over three seeds at three
# pairs, comparing the worst specificity margin achieved by designing the
# set jointly against designing each pair on its own:
#
#     margin        joint      independent
#       1.0         -1.20         -1.89      <- joint is WORSE
#       2.0         -1.98         -2.07      <- no advantage
#       3.0         -2.72         -1.81
#       4.0         -3.11         -1.41
#
# At 1.0 the hinge switches off almost immediately -- cognate scores run
# around -20, so clearing a competitor by a single unit is trivial -- and
# the search stops before it has differentiated the pairs at all. Joint
# design only earns its keep once the bar is high enough to force it to use
# the levers that actually separate coiled coils: buried polar residues at
# 'a' and opposed charge patterns at e/g. Independent design gets worse as
# the bar rises, because a lone pair has nothing to spend the extra
# optimisation on except wrecking its own homodimer.
DEFAULT_CROSS_MARGIN = 3.0


@dataclass
class OrthogonalSet:
    """K designed pairs plus their full interaction matrix."""

    names: list[str]
    sequences: list[str]
    offset: int
    matrix: list[list[float]]
    objective: float
    fixed_index: int | None = None
    margin: float = DEFAULT_CROSS_MARGIN
    _registers: list[Register] = field(default_factory=list, repr=False)

    @property
    def n_pairs(self) -> int:
        return len(self.sequences) // 2

    def cognate(self, i: int) -> int:
        """Index of the chain that chain `i` is meant to bind."""
        return i + 1 if i % 2 == 0 else i - 1

    def cognate_score(self, pair: int) -> float:
        return self.matrix[2 * pair][2 * pair + 1]

    def worst_offtarget(self, pair: int) -> tuple[float, str, str]:
        """The most competitive unwanted interaction involving this pair."""
        worst = (float("inf"), "", "")
        for x in (2 * pair, 2 * pair + 1):
            for y in range(len(self.sequences)):
                if y == self.cognate(x):
                    continue
                score = self.matrix[x][y]
                if score < worst[0]:
                    worst = (score, self.names[x], self.names[y])
        return worst

    def margin_for(self, pair: int) -> float:
        """How far the cognate pair beats its worst competitor.

        Negative is good. This is the number that decides whether the pair is
        usable, not the raw cognate score.
        """
        return self.cognate_score(pair) - self.worst_offtarget(pair)[0]

    def is_orthogonal(self) -> bool:
        """True when every pair beats its competitors by the design margin.

        The bar is `-self.margin`, not 0. Reporting success at "cognate wins
        by any amount at all" would be a weaker standard than the one the
        search optimised against, and in an uncalibrated model a gap of a
        fraction of a unit is indistinguishable from noise. Sets designed
        independently pass the sloppy test routinely; they fail this one.
        """
        return all(
            self.margin_for(i) <= -self.margin for i in range(self.n_pairs)
        )

    def matrix_report(self) -> str:
        """Full interaction matrix, cognate pairs marked."""
        w = max(len(n) for n in self.names) + 1
        head = " " * w + "".join(f"{n:>9}" for n in self.names)
        lines = [head]
        for i, name in enumerate(self.names):
            row = f"{name:<{w}}"
            for j in range(len(self.names)):
                mark = "*" if j == self.cognate(i) else " "
                row += f"{self.matrix[i][j]:>8.1f}{mark}"
            lines.append(row)
        lines.append("")
        lines.append("* = intended (cognate) pair. Every other cell is an")
        lines.append("  off-target that the cognate pair must beat.")
        return "\n".join(lines)

    def report(self) -> str:
        lines = []
        for p in range(self.n_pairs):
            a, b = 2 * p, 2 * p + 1
            score, n1, n2 = self.worst_offtarget(p)
            margin = self.margin_for(p)
            lines.append(f"pair {p + 1}:  {self.names[a]} / {self.names[b]}")
            lines.append(f"  {self.names[a]:<6} {self.sequences[a]}")
            lines.append(f"  {self.names[b]:<6} {self.sequences[b]}")
            lines.append(f"  cognate        {self.cognate_score(p):+.2f}")
            lines.append(
                f"  worst off-target {score:+.2f}  ({n1}-{n2})"
            )
            if margin <= -self.margin:
                verdict = "OK"
            elif margin < 0:
                verdict = (
                    f"THIN: ahead, but by less than the {self.margin:.1f} "
                    "required"
                )
            else:
                verdict = "FAILS: an off-target is more stable"
            lines.append(f"  margin         {margin:+.2f}  ({verdict})")
            lines.append("")

        if self.is_orthogonal():
            lines.append(
                f"Every pair beats all off-targets by at least "
                f"{self.margin:.1f}."
            )
        else:
            thin = [
                p for p in range(self.n_pairs)
                if -self.margin < self.margin_for(p) < 0
            ]
            failed = [
                p for p in range(self.n_pairs) if self.margin_for(p) >= 0
            ]
            if failed:
                lines.append(
                    f"NOT orthogonal: pair(s) "
                    f"{', '.join(str(p + 1) for p in failed)} lose to an "
                    "off-target outright."
                )
            if thin:
                lines.append(
                    f"Pair(s) {', '.join(str(p + 1) for p in thin)} are ahead "
                    f"but by less than the required {self.margin:.1f}, so the "
                    "separation is within this model's noise."
                )
            lines.append(
                "Try more restarts or steps, fewer pairs, or -- if a fixed "
                "target is pinning the set -- accept that its own homodimer "
                "is hard to beat."
            )
        return "\n".join(lines)

    def to_fasta(self) -> str:
        return "".join(
            f">{n}\n{s}\n" for n, s in zip(self.names, self.sequences)
        )


def _full_matrix(
    registers: list[Register], weights: dict[str, float]
) -> list[list[float]]:
    n = len(registers)
    m = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            s = score_pair(registers[i], registers[j], weights,
                           shift=FIXED_SHIFT).total
            m[i][j] = m[j][i] = s
    return m


def _update_row(
    m: list[list[float]],
    registers: list[Register],
    i: int,
    weights: dict[str, float],
) -> None:
    """Rescore only the interactions involving chain `i`."""
    for j in range(len(registers)):
        s = score_pair(registers[i], registers[j], weights,
                       shift=FIXED_SHIFT).total
        m[i][j] = m[j][i] = s


def _objective(
    m: list[list[float]], n: int, w_cross: float, margin: float
) -> float:
    """Cognate stability plus hinged penalties on every off-target."""
    total = 0.0
    for p in range(n // 2):
        total += m[2 * p][2 * p + 1]

    penalty = 0.0
    for x in range(n):
        cog_x = x + 1 if x % 2 == 0 else x - 1
        e_cog_x = m[x][cog_x]
        for y in range(x, n):
            if y == cog_x:
                continue
            offtarget = m[x][y]
            penalty += _hinge_with(e_cog_x, offtarget, margin)
            if y != x:
                cog_y = y + 1 if y % 2 == 0 else y - 1
                penalty += _hinge_with(m[y][cog_y], offtarget, margin)

    return total + w_cross * penalty


def _hinge_with(cognate: float, competitor: float, margin: float) -> float:
    return max(0.0, cognate + margin - competitor)


def design_orthogonal_set(
    n_pairs: int = 2,
    length: int | None = None,
    offset: int = 0,
    fixed: str | Register | None = None,
    n_restarts: int = 4,
    n_steps: int = 6000,
    t_start: float = 1.5,
    t_end: float = 0.03,
    w_cross: float = 1.0,
    margin: float = DEFAULT_CROSS_MARGIN,
    weights: dict[str, float] | None = None,
    seed: int | None = None,
    progress=None,
) -> OrthogonalSet:
    """Design `n_pairs` mutually orthogonal coiled-coil pairs.

    Args:
        n_pairs: how many independent pairs. Difficulty rises steeply: 2 is
            easy, 3 is reasonable, 4+ needs many more steps and may fail.
        length: helix length in residues. Defaults to the fixed helix's
            length, or 33 (a GCN4-sized zipper).
        offset: heptad offset for the designed chains. Ignored when `fixed`
            is given, since every chain must share the fixed helix's offset
            for shift-0 scoring to be correct.
        fixed: an existing helix to build the set around -- typically the
            target measured from a structure. It becomes chain A1 and is
            never mutated, so the result is a set orthogonal to something
            you already have.
        n_restarts, n_steps, t_start, t_end: annealing control.
        w_cross: strength of the off-target penalties.
        margin: how far a cognate pair must beat an off-target before the
            penalty switches off. See DEFAULT_CROSS_MARGIN -- lowering this
            towards 1.0 makes joint design no better than designing each
            pair separately.
        progress: optional callable(fraction, text) for UI feedback.

    Returns:
        The best `OrthogonalSet` found. Check `.is_orthogonal()`; a set that
        fails is still returned so you can see how close it came.
    """
    if n_pairs < 1:
        raise ValueError("need at least one pair")

    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    rng = random.Random(seed)

    fixed_reg: Register | None = None
    if fixed is not None:
        fixed_reg = fixed if isinstance(fixed, Register) else assign_register(fixed)
        offset = fixed_reg.offset
        length = length or len(fixed_reg.sequence)
    length = length or 33
    if length < 14:
        raise ValueError("helices must be at least two heptads (14 residues)")

    n = 2 * n_pairs
    names = []
    for p in range(n_pairs):
        names += [f"{chr(65 + p)}", f"{chr(65 + p)}'"]
    if fixed_reg is not None:
        names[0] = "TARGET"

    best_set: OrthogonalSet | None = None

    for restart in range(n_restarts):
        seqs = [_seed_chain(length, offset, rng) for _ in range(n)]
        if fixed_reg is not None:
            seqs[0] = fixed_reg.sequence
        regs = [assign_register(s, offset) for s in seqs]

        m = _full_matrix(regs, w)
        obj = _objective(m, n, w_cross, margin)
        best_local = (obj, list(seqs), [row[:] for row in m])

        cooling = (t_end / t_start) ** (1.0 / max(n_steps - 1, 1))
        temp = t_start
        mutable = [i for i in range(n) if not (fixed_reg is not None and i == 0)]

        for step in range(n_steps):
            i = rng.choice(mutable)
            k = rng.randrange(length)
            pos = HEPTAD_POSITIONS[(offset + k) % 7]
            old_res = seqs[i][k]
            new_res = rng.choice(ALPHABET[pos])
            if new_res == old_res:
                temp *= cooling
                continue

            old_seq = seqs[i]
            old_row = m[i][:]
            seqs[i] = old_seq[:k] + new_res + old_seq[k + 1:]
            regs[i] = assign_register(seqs[i], offset)
            _update_row(m, regs, i, w)
            new_obj = _objective(m, n, w_cross, margin)

            delta = new_obj - obj
            if delta <= 0 or rng.random() < _accept(delta, temp):
                obj = new_obj
                if obj < best_local[0]:
                    best_local = (obj, list(seqs), [row[:] for row in m])
            else:
                seqs[i] = old_seq
                regs[i] = assign_register(old_seq, offset)
                for j in range(n):
                    m[i][j] = m[j][i] = old_row[j]
            temp *= cooling

            if progress is not None and step % 500 == 0:
                done = (restart * n_steps + step) / (n_restarts * n_steps)
                progress(done, f"restart {restart + 1}/{n_restarts}, "
                               f"step {step}/{n_steps}")

        candidate = OrthogonalSet(
            names=names,
            sequences=best_local[1],
            offset=offset,
            matrix=best_local[2],
            objective=best_local[0],
            fixed_index=0 if fixed_reg is not None else None,
            margin=margin,
        )
        if best_set is None or candidate.objective < best_set.objective:
            best_set = candidate

    assert best_set is not None
    if progress is not None:
        progress(1.0, "done")
    return best_set


def _seed_chain(length: int, offset: int, rng: random.Random) -> str:
    return "".join(
        rng.choice(ALPHABET[HEPTAD_POSITIONS[(offset + i) % 7]])
        for i in range(length)
    )


def _accept(delta: float, temp: float) -> float:
    if temp <= 0:
        return 0.0
    x = -delta / temp
    if x < -700:
        return 0.0
    import math

    return math.exp(x)
