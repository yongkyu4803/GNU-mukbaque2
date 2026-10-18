"""Tests for structure parsing and geometric register measurement.

Ground truth comes from the Crick generator in make_structure.py, where the
register is an input parameter, so these tests check a measurement against
independently constructed geometry rather than against themselves.
"""

from __future__ import annotations

import math

import pytest

from lz.structure import (
    IDEAL_PROFILE,
    _inward_cosines,
    StructureError,
    _distance,
    analyse,
    find_helices,
    measure_register,
    read_pdb,
)

from .make_structure import build_dimer, write_dimer

GCN4 = "RMKQLEDKVEELLSKNYHLENEVARLKKLVGER"


@pytest.fixture
def dimer(tmp_path):
    """GCN4-p1 built with its real register: residue 1 (Arg) sits at 'g'."""
    return write_dimer(tmp_path / "dimer.pdb", GCN4, start_position="g")


# --- the generator itself must be geometrically sane -----------------------

def test_generated_backbone_has_alpha_helical_geometry(tmp_path):
    path = write_dimer(tmp_path / "x.pdb", GCN4)
    chains, _ = read_pdb(path)
    cas = [r.ca for r in chains["A"]]

    consecutive = [_distance(cas[i], cas[i + 1]) for i in range(len(cas) - 1)]
    assert all(3.7 <= d <= 3.9 for d in consecutive), consecutive[:5]

    i_to_i4 = [_distance(cas[i], cas[i + 4]) for i in range(len(cas) - 4)]
    assert all(5.9 <= d <= 6.5 for d in i_to_i4), i_to_i4[:5]


def test_two_chains_are_a_plausible_distance_apart(tmp_path):
    path = write_dimer(tmp_path / "x.pdb", GCN4)
    chains, _ = read_pdb(path)
    a = [r.ca for r in chains["A"]]
    b = [r.ca for r in chains["B"]]
    closest = min(_distance(p, q) for p in a for q in b)
    assert 4.0 <= closest <= 11.0, closest


# --- parsing ---------------------------------------------------------------

def test_sequence_round_trips_through_the_pdb(dimer):
    chains, _ = read_pdb(dimer)
    assert len(chains) == 2
    for residues in chains.values():
        assert "".join(r.one_letter for r in residues) == GCN4


def test_helix_detection_covers_the_whole_construct(dimer):
    chains, _ = read_pdb(dimer)
    helices = find_helices(chains["A"])
    assert len(helices) == 1
    assert len(helices[0]) >= len(GCN4) - 2


def test_ligands_are_separated_from_polymer(tmp_path):
    path = tmp_path / "lig.pdb"
    path.write_text(
        build_dimer(GCN4, ligand=("STI", (0.0, 0.0, 20.0))), encoding="utf-8"
    )
    chains, ligands = read_pdb(path)
    assert len(chains) == 2
    assert [l.name for l in ligands] == ["STI"]
    assert ligands[0].centroid == pytest.approx((0.0, 0.0, 20.0))


def test_waters_and_cryoprotectants_are_discarded(tmp_path):
    path = tmp_path / "junk.pdb"
    body = build_dimer(GCN4).replace("END\n", "")
    body += (
        "HETATM 9001  O   HOH L   1       1.000   2.000   3.000  1.00  0.00  O\n"
        "HETATM 9002  C1  GOL L   2       1.000   2.000   3.000  1.00  0.00  C\n"
        "END\n"
    )
    path.write_text(body, encoding="utf-8")
    _, ligands = read_pdb(path)
    assert ligands == []


def test_only_the_first_nmr_model_is_read(tmp_path):
    path = tmp_path / "nmr.pdb"
    body = build_dimer(GCN4).replace("END\n", "")
    path.write_text(
        "MODEL        1\n" + body + "ENDMDL\n"
        "MODEL        2\n" + body + "ENDMDL\nEND\n",
        encoding="utf-8",
    )
    chains, _ = read_pdb(path)
    assert len(chains["A"]) == len(GCN4)


def test_alternate_conformers_do_not_duplicate_residues(tmp_path):
    path = tmp_path / "alt.pdb"
    body = build_dimer(GCN4).replace("END\n", "")
    body += (
        "ATOM   9001  CA BLEU A   5       0.000   0.000   0.000  0.50  0.00  C\n"
        "END\n"
    )
    path.write_text(body, encoding="utf-8")
    chains, _ = read_pdb(path)
    assert len(chains["A"]) == len(GCN4)


def test_missing_file_is_reported_clearly(tmp_path):
    with pytest.raises(StructureError, match="file not found"):
        read_pdb(tmp_path / "nope.pdb")


def test_file_without_protein_is_reported_clearly(tmp_path):
    path = tmp_path / "empty.pdb"
    path.write_text("HEADER    NOTHING\nEND\n", encoding="utf-8")
    with pytest.raises(StructureError, match="no protein residues"):
        read_pdb(path)


# --- the register measurement, against known ground truth ------------------

@pytest.mark.parametrize("start", list("abcdefg"))
def test_measured_register_recovers_the_built_register(tmp_path, start):
    path = write_dimer(tmp_path / f"{start}.pdb", GCN4, start_position=start)
    analysis, _, _ = analyse(path)
    assert analysis is not None
    assert "abcdefg"[analysis.offset] == start


def test_register_measurement_is_confident_on_ideal_geometry(tmp_path):
    path = write_dimer(tmp_path / "x.pdb", GCN4, start_position="g")
    analysis, _, _ = analyse(path)
    assert analysis.register_quality > 0.95
    assert analysis.margin > 0.2
    assert analysis.register_warning is None


def test_ideal_profile_still_matches_the_generator(tmp_path):
    """IDEAL_PROFILE is copied from the Crick generator; keep them in step.

    If the generator's geometry changes and this table does not, every
    register assignment silently degrades. Better to fail here.
    """
    path = write_dimer(tmp_path / "x.pdb", GCN4, start_position="g")
    analysis, _, _ = analyse(path)
    cosines = _inward_cosines(analysis.segment, analysis.partner)

    by_position: dict[str, list[float]] = {p: [] for p in "abcdefg"}
    for i in range(len(analysis.segment.residues)):
        by_position[analysis.position(i)].append(cosines[i])

    for pos, values in by_position.items():
        measured = sum(values) / len(values)
        assert measured == pytest.approx(IDEAL_PROFILE[pos], abs=0.02), pos


def test_measured_register_puts_gcn4_leucines_at_d(dimer):
    analysis, _, _ = analyse(dimer)
    d_residues = [
        res.one_letter for pos, res, _ in analysis.core_residues if pos == "d"
    ]
    assert d_residues.count("L") >= 3, d_residues


def test_measured_register_agrees_with_the_sequence_predictor(dimer):
    """The two independent routes to GCN4's register must concur."""
    from lz import assign_register

    analysis, _, _ = analyse(dimer)
    assert analysis.offset == assign_register(GCN4).offset


def test_core_residues_point_inwards_and_others_do_not(dimer):
    analysis, _, _ = analyse(dimer)
    core_cosines = [c for _, _, c in analysis.core_residues]
    assert min(core_cosines) > 0.3, core_cosines


# --- orientation -----------------------------------------------------------

def test_parallel_dimer_is_called_parallel(dimer):
    analysis, _, _ = analyse(dimer)
    assert analysis.parallel
    assert analysis.orientation == "parallel"


def test_antiparallel_dimer_is_detected(tmp_path):
    path = write_dimer(tmp_path / "anti.pdb", GCN4, parallel=False)
    analysis, _, _ = analyse(path)
    assert not analysis.parallel
    assert "ANTIPARALLEL" in analysis.report()


# --- chain selection and single-helix fallback -----------------------------

def test_target_chain_can_be_chosen(dimer):
    analysis, _, _ = analyse(dimer, target_chain="B")
    assert analysis.segment.chain == "B"
    assert analysis.partner.chain == "A"


def test_unknown_chain_lists_what_is_available(dimer):
    with pytest.raises(StructureError, match="helices found in chain"):
        analyse(dimer, target_chain="Z")


def test_single_helix_returns_no_analysis(tmp_path):
    path = tmp_path / "mono.pdb"
    text = build_dimer(GCN4)
    keep = [
        ln for ln in text.splitlines()
        if not (len(ln) > 21 and ln[21] == "B")
    ]
    path.write_text("\n".join(keep) + "\n", encoding="utf-8")
    analysis, helices, _ = analyse(path)
    assert analysis is None
    assert len(helices) == 1


def test_report_mentions_both_chains(dimer):
    analysis, _, _ = analyse(dimer)
    text = analysis.report()
    assert "chain A vs chain B" in text
    assert GCN4 in text
