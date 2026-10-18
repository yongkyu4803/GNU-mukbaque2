"""Tests for orthogonal set design."""

from __future__ import annotations

import pytest

from lz import assign_register, design_partner, score_pair
from lz.design import ALPHABET
from lz.orthogonal import DEFAULT_CROSS_MARGIN, design_orthogonal_set

GCN4 = "RMKQLEDKVEELLSKNYHLENEVARLKKLVGER"

FAST = dict(n_restarts=2, n_steps=1500, seed=1)


@pytest.fixture(scope="module")
def two_pairs():
    return design_orthogonal_set(n_pairs=2, n_restarts=3, n_steps=4000, seed=7)


# --- matrix mechanics ------------------------------------------------------

def test_matrix_is_square_and_symmetric(two_pairs):
    n = len(two_pairs.sequences)
    assert n == 4
    for i in range(n):
        for j in range(n):
            assert two_pairs.matrix[i][j] == two_pairs.matrix[j][i]


def test_cognate_pairing_is_adjacent_chains(two_pairs):
    assert two_pairs.cognate(0) == 1
    assert two_pairs.cognate(1) == 0
    assert two_pairs.cognate(2) == 3
    assert two_pairs.cognate(3) == 2


def test_cognate_score_matches_the_matrix(two_pairs):
    for p in range(two_pairs.n_pairs):
        assert two_pairs.cognate_score(p) == two_pairs.matrix[2 * p][2 * p + 1]


def test_matrix_entries_reproduce_score_pair(two_pairs):
    """The stored matrix must be the real score, not a stale cache."""
    regs = [
        assign_register(s, two_pairs.offset) for s in two_pairs.sequences
    ]
    for i in range(len(regs)):
        for j in range(len(regs)):
            expected = score_pair(regs[i], regs[j], shift=0).total
            assert two_pairs.matrix[i][j] == pytest.approx(expected)


def test_worst_offtarget_never_returns_a_cognate_pair(two_pairs):
    for p in range(two_pairs.n_pairs):
        _, n1, n2 = two_pairs.worst_offtarget(p)
        a, b = two_pairs.names[2 * p], two_pairs.names[2 * p + 1]
        assert {n1, n2} != {a, b}


def test_margin_is_cognate_minus_worst_offtarget(two_pairs):
    for p in range(two_pairs.n_pairs):
        worst = two_pairs.worst_offtarget(p)[0]
        assert two_pairs.margin_for(p) == pytest.approx(
            two_pairs.cognate_score(p) - worst
        )


# --- does it actually achieve orthogonality? -------------------------------

def test_two_pairs_come_out_orthogonal(two_pairs):
    assert two_pairs.is_orthogonal(), two_pairs.report()


def test_every_cognate_pair_beats_both_its_homodimers(two_pairs):
    m = two_pairs.matrix
    for p in range(two_pairs.n_pairs):
        a, b = 2 * p, 2 * p + 1
        assert m[a][b] < m[a][a]
        assert m[a][b] < m[b][b]


def _worst_margin(chains: list[str], offset: int) -> float:
    """Worst (least negative) specificity margin over pairs (0,1), (2,3), ...

    Lower is better. This is the continuous quantity behind
    `OrthogonalSet.is_orthogonal`, used here instead of the boolean because
    comparing two design strategies over a handful of seeds needs a measure
    with more resolution than pass/fail.
    """
    regs = [assign_register(s, offset) for s in chains]
    m = [[score_pair(x, y, shift=0).total for y in regs] for x in regs]
    n = len(chains)
    worst = float("-inf")
    for p in range(n // 2):
        cognate = m[2 * p][2 * p + 1]
        worst_off = min(
            m[x][y]
            for x in (2 * p, 2 * p + 1)
            for y in range(n)
            if y != (x + 1 if x % 2 == 0 else x - 1)
        )
        worst = max(worst, cognate - worst_off)
    return worst


def _compare_strategies(margin: float, seeds=(11, 22, 33)) -> tuple[float, float]:
    """Mean worst-margin for joint vs independent design, at one bar."""
    kw = dict(n_restarts=2, n_steps=2500, margin=margin)
    joint, independent = [], []
    for s in seeds:
        js = design_orthogonal_set(n_pairs=3, seed=s, **kw)
        joint.append(max(js.margin_for(p) for p in range(js.n_pairs)))

        chains: list[str] = []
        for p in range(3):
            chains += design_orthogonal_set(
                n_pairs=1, seed=s * 10 + p, **kw
            ).sequences
        independent.append(_worst_margin(chains, js.offset))
    return sum(joint) / len(joint), sum(independent) / len(independent)


def test_joint_design_separates_pairs_better_at_the_default_margin():
    """The reason this module exists -- but only above a threshold bar.

    Two earlier versions of this test were wrong in instructive ways. The
    first reused the joint set's own A chains for the "independent" arm,
    leaking the co-optimisation it was trying to measure. The second compared
    pass/fail, which at two pairs is close to a coin flip: the optimiser
    polarises each pair into acidic/basic, and an independently designed
    second pair lands the opposite way round often enough to pass.

    Fixing those revealed something real -- at the old margin of 1.0, joint
    design was genuinely no better than independent design. See
    DEFAULT_CROSS_MARGIN for the measurements that set the default.
    """
    joint, independent = _compare_strategies(DEFAULT_CROSS_MARGIN)
    assert joint < independent - 0.5, (joint, independent)


def test_a_lenient_margin_erases_the_advantage():
    """Pins the finding that set the default, so it cannot regress silently.

    At margin 1.0 the hinge switches off almost immediately -- cognate
    scores run near -20, so beating a competitor by one unit is nothing --
    and the search stops before differentiating the pairs. If this ever
    starts passing by a wide joint win, the hinge or the score scale has
    changed and DEFAULT_CROSS_MARGIN should be re-measured.
    """
    joint, independent = _compare_strategies(1.0)
    assert joint > independent - 0.5, (joint, independent)


def test_independent_design_fails_the_strict_orthogonality_bar():
    """Independently designed pairs clear "wins at all" but not the real bar.

    This is what motivated tightening `is_orthogonal` to the design margin
    rather than to zero.
    """
    kw = dict(n_restarts=2, n_steps=2500)
    chains: list[str] = []
    for p in range(3):
        chains += design_orthogonal_set(n_pairs=1, seed=110 + p, **kw).sequences

    worst = _worst_margin(chains, 0)
    assert worst < 0, "independent pairs do clear the lenient bar"
    assert worst > -DEFAULT_CROSS_MARGIN, (
        "independent pairs cleared the design margin, so the joint designer "
        "is no longer earning its keep"
    )


# --- building a set around an existing helix -------------------------------

def test_fixed_helix_is_never_mutated():
    s = design_orthogonal_set(n_pairs=2, fixed=GCN4, **FAST)
    assert s.sequences[0] == GCN4
    assert s.names[0] == "TARGET"
    assert s.fixed_index == 0


def test_fixed_helix_forces_its_own_heptad_offset():
    s = design_orthogonal_set(n_pairs=2, fixed=GCN4, **FAST)
    assert s.offset == assign_register(GCN4).offset
    assert all(len(seq) == len(GCN4) for seq in s.sequences)


def test_a_partner_is_designed_for_the_fixed_helix():
    s = design_orthogonal_set(n_pairs=1, fixed=GCN4, n_restarts=3,
                              n_steps=3000, seed=2)
    # The designed partner must beat GCN4's own homodimer, which is the
    # competitor it actually has to displace.
    assert s.matrix[0][1] < s.matrix[0][0]


# --- search mechanics ------------------------------------------------------

def test_designed_chains_respect_the_position_alphabets(two_pairs):
    for i, seq in enumerate(two_pairs.sequences):
        reg = assign_register(seq, two_pairs.offset)
        for k, res in enumerate(seq):
            assert res in ALPHABET[reg.position(k)], (i, k, res)


def test_result_is_reproducible_with_a_seed():
    a = design_orthogonal_set(n_pairs=2, **FAST)
    b = design_orthogonal_set(n_pairs=2, **FAST)
    assert a.sequences == b.sequences


def test_progress_callback_reaches_one():
    seen = []
    design_orthogonal_set(n_pairs=2, n_restarts=1, n_steps=1000, seed=1,
                          progress=lambda f, t: seen.append(f))
    assert seen and seen[-1] == 1.0
    assert all(0.0 <= f <= 1.0 for f in seen)


def test_fasta_export_lists_every_chain(two_pairs):
    fasta = two_pairs.to_fasta()
    assert fasta.count(">") == len(two_pairs.sequences)
    for seq in two_pairs.sequences:
        assert seq in fasta


def test_matrix_report_marks_only_cognate_cells(two_pairs):
    text = two_pairs.matrix_report()
    assert text.count("*") == len(two_pairs.sequences) + 1  # +1 in the legend


@pytest.mark.parametrize("bad", [0, -1])
def test_rejects_nonsense_pair_counts(bad):
    with pytest.raises(ValueError):
        design_orthogonal_set(n_pairs=bad)


def test_rejects_helices_shorter_than_two_heptads():
    with pytest.raises(ValueError):
        design_orthogonal_set(n_pairs=2, length=10)


# --- the scoring fast path these designs depend on -------------------------

def test_pinned_shift_matches_the_searched_result_when_shift_is_optimal():
    a = assign_register(GCN4)
    searched = score_pair(a, a)
    pinned = score_pair(a, a, shift=0)
    assert searched.shift == 0
    assert pinned.total == pytest.approx(searched.total)


def test_pinned_shift_is_not_silently_overridden():
    """A pinned shift must be used even when another one would score better."""
    a = assign_register(GCN4)
    forced = score_pair(a, a, shift=1)
    assert forced.shift == 1
    assert forced.total >= score_pair(a, a, shift=0).total
