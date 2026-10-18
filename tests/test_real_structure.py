"""Regression tests against a real crystal structure.

Everything else in the structure test suite runs on Crick-generated ideal
coordinates, where the register is known because it was an input. That
proves the measurement is correct; it does not prove it survives contact
with a real PDB entry -- full side chains, capping groups, non-helical
termini, refinement noise.

2ZTA is the GCN4 leucine zipper (O'Shea et al. 1991, Science 254:539), the
structure the whole field treats as the reference parallel two-stranded
coiled coil. Its register is independently known from the literature: Arg1
sits at 'g', the four heptad leucines at 'd', Asn16 at 'a'.

The file is not committed. Fetch it with:
    python tools/fetch_structure.py 2ZTA
These tests skip when it is absent, so the suite still runs offline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lz import assign_register, screen
from lz.structure import AMBIGUOUS_FIT, AMBIGUOUS_MARGIN, analyse

STRUCTURE = Path(__file__).resolve().parent.parent / "structures" / "2ZTA.pdb"

pytestmark = pytest.mark.skipif(
    not STRUCTURE.exists(),
    reason="structures/2ZTA.pdb not downloaded (python tools/fetch_structure.py 2ZTA)",
)

# Known from the literature, not from this program.
EXPECTED_OFFSET = 6          # residue 1 (Arg) sits at 'g'
EXPECTED_CORE_LEUCINES = [5, 12, 19, 26]
ASN_AT_A = 16


@pytest.fixture(scope="module")
def analysis():
    result, _, _ = analyse(STRUCTURE)
    assert result is not None
    return result


def test_both_chains_are_found_as_helices(analysis):
    assert analysis.segment.chain == "A"
    assert analysis.partner.chain == "B"


def test_structure_is_parallel(analysis):
    assert analysis.parallel


def test_measured_register_matches_the_literature(analysis):
    assert analysis.offset == EXPECTED_OFFSET


def test_the_heptad_leucines_land_at_d(analysis):
    at_d = [
        res.seq_id for pos, res, _ in analysis.core_residues
        if pos == "d" and res.one_letter == "L"
    ]
    assert at_d == EXPECTED_CORE_LEUCINES


def test_asn16_lands_at_a(analysis):
    at_a = {
        res.seq_id: res.one_letter
        for pos, res, _ in analysis.core_residues if pos == "a"
    }
    assert at_a.get(ASN_AT_A) == "N"


def test_the_canonical_zipper_raises_no_warning(analysis):
    """The thresholds must not cry wolf on the reference structure.

    This is why they were recalibrated: the original a/d-only register score
    left 2ZTA with a margin of 0.098 against a warning threshold of 0.1, so
    the textbook leucine zipper was reported as having ambiguous geometry.
    """
    assert analysis.register_warning is None, analysis.report()
    assert analysis.register_quality > AMBIGUOUS_FIT
    assert analysis.margin > AMBIGUOUS_MARGIN


def test_fit_is_high_on_a_real_structure(analysis):
    # Ideal geometry scores ~0.999; a real one should still be clearly good.
    assert analysis.register_quality > 0.85


def test_the_wrong_register_is_beaten_by_a_real_margin(analysis):
    # The near-degenerate alternative (shifted by 3 or 4 residues) is the
    # one to beat, and it is genuinely similar, so the bar is modest.
    assert analysis.margin > 0.08


def test_acetyl_caps_are_reported_as_non_polymer():
    _, _, ligands = analyse(STRUCTURE)
    assert {l.name for l in ligands} == {"ACE"}


def test_geometric_and_sequence_registers_agree(analysis):
    """Two independent routes to the same answer on real coordinates."""
    predicted = assign_register(analysis.segment.sequence)
    assert predicted.offset == analysis.offset


def test_the_modelled_helix_is_a_truncation_of_the_library_sequence(analysis):
    """A crystal structure gives the ORDERED region, not the construct.

    2ZTA models 31 residues; the GCN4-p1 sequence in the library is the full
    33-mer. Anyone comparing a structure-derived target against a library
    entry is comparing two different molecules, and this is the usual reason
    the numbers do not line up the way intuition expects.
    """
    from lz import load_library

    library_gcn4 = next(
        z.sequence for z in load_library() if z.name == "GCN4-p1"
    )
    assert library_gcn4.startswith(analysis.segment.sequence)
    assert len(library_gcn4) - len(analysis.segment.sequence) == 2


def test_screening_runs_end_to_end_on_the_real_target(analysis):
    target = assign_register(analysis.segment.sequence, analysis.offset)
    hits = screen(target)

    assert len(hits) == 5
    assert [h.specificity for h in hits] == sorted(h.specificity for h in hits)
    # GCN4 is this target's own cognate partner, so it must bind strongly,
    # whatever its specificity ranking (which is meaningless for a sequence
    # that is essentially itself).
    gcn4 = next(h for h in hits if h.zipper.name == "GCN4-p1")
    assert gcn4.score.total < -8.0


def test_truncation_explains_the_gcn4_specificity(analysis):
    """Why GCN4-p1 does not score as a tie against its own structure.

    The library's 33-mer homodimer buries Arg33 at a 'd' position -- two
    like charges in the core, the worst layer the model knows. The 31-residue
    crystal helix stops before that layer, so pairing it with the 33-mer
    beats the 33-mer's own homodimer. Pinning this stops the next person
    reading it as a scoring bug.
    """
    from lz import load_library, score_pair

    target = assign_register(analysis.segment.sequence, analysis.offset)
    full = next(z for z in load_library() if z.name == "GCN4-p1")
    full_reg = full.register()

    truncated_pair = score_pair(target, full_reg).total
    full_homodimer = score_pair(full_reg, full_reg).total
    assert truncated_pair < full_homodimer

    worst_layer = [
        c for c in score_pair(full_reg, full_reg).contacts
        if c.res1 == "R" and c.res2 == "R" and c.position == "d"
    ]
    assert worst_layer, "expected a buried Arg/Arg layer in the 33-mer"
    assert worst_layer[0].energy > 0
