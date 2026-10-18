"""Tests for the lz package.

These check mechanics (registers land where they should, scores respond to
the right perturbations) and a few qualitative biophysical expectations. They
do NOT assert absolute energies -- the model is uncalibrated, so any such
assertion would be testing a placeholder constant.
"""

from __future__ import annotations

import pytest

from lz import assign_register, design_partner, load_library, score_pair, screen
from lz.heptad import RegisterError, ge_pairs
from lz.scoring import core_layer_energy, ge_energy

GCN4 = "RMKQLEDKVEELLSKNYHLENEVARLKKLVGER"


# --- register assignment ---------------------------------------------------

def test_gcn4_register_puts_leucines_at_d():
    reg = assign_register(GCN4, offset=6)
    # The four heptad leucines of GCN4-p1 must land at 'd'.
    d_residues = reg.residues_at("d")
    assert d_residues.count("L") >= 3, d_residues


def test_gcn4_register_is_predicted_correctly():
    predicted = assign_register(GCN4)
    assert predicted.offset == 6
    assert predicted.confidence > 0


def test_asn16_sits_at_an_a_position():
    reg = assign_register(GCN4, offset=6)
    # Asn16 in 1-based GCN4-p1 numbering is index 15 here.
    assert reg.sequence[15] == "N"
    assert reg.position(15) == "a"


def test_positions_string_matches_per_residue_lookup():
    reg = assign_register(GCN4)
    assert reg.positions() == "".join(
        reg.position(i) for i in range(len(GCN4))
    )


def test_ge_pairs_are_five_apart():
    reg = assign_register(GCN4)
    for g, e in ge_pairs(reg):
        assert e - g == 5
        assert reg.position(g) == "g"
        assert reg.position(e) == "e"


@pytest.mark.parametrize("bad", ["", "ACDXQ", "MKQL"])
def test_invalid_sequences_rejected(bad):
    with pytest.raises(RegisterError):
        assign_register(bad)


def test_forced_offset_must_be_in_range():
    with pytest.raises(RegisterError):
        assign_register(GCN4, offset=9)


def test_whitespace_and_case_are_tolerated():
    a = assign_register(GCN4)
    b = assign_register(GCN4.lower()[:10] + " " + GCN4[10:])
    assert a.sequence == b.sequence


# --- layer energetics ------------------------------------------------------

def test_leucine_pair_is_best_at_d():
    at_d = {r: core_layer_energy("d", r, r) for r in "LIVAMF"}
    assert min(at_d, key=at_d.get) == "L"


def test_isoleucine_beats_leucine_at_a():
    # Harbury 1993: Ile at a / Leu at d specifies the parallel dimer.
    assert core_layer_energy("a", "I", "I") < core_layer_energy("a", "L", "L")


def test_buried_like_charges_are_penalised():
    assert core_layer_energy("a", "K", "K") > core_layer_energy("a", "K", "E")
    assert core_layer_energy("d", "E", "E") > 0


def test_salt_bridge_signs():
    assert ge_energy("K", "E") < 0
    assert ge_energy("E", "E") > 0
    assert ge_energy("A", "L") == 0


# --- pair scoring ----------------------------------------------------------

def test_gcn4_homodimer_is_favourable():
    assert score_pair(GCN4, GCN4).total < 0


def test_scoring_is_symmetric():
    lib = {z.name: z.sequence for z in load_library()}
    a, b = lib["c-Jun-LZ"], lib["c-Fos-LZ"]
    assert score_pair(a, b).total == pytest.approx(score_pair(b, a).total)


def test_core_charge_substitution_destabilises():
    """Replacing core leucines with glutamate must make the score worse."""
    reg = assign_register(GCN4, offset=6)
    mutant = list(reg.sequence)
    for i in reg.indices("d"):
        mutant[i] = "E"
    worse = score_pair("".join(mutant), GCN4).total
    assert worse > score_pair(GCN4, GCN4).total


def test_contacts_sum_to_the_component_scores():
    s = score_pair(GCN4, GCN4)
    core = sum(c.energy for c in s.contacts if c.kind == "core")
    elec = sum(c.energy for c in s.contacts if c.kind == "elec")
    assert core == pytest.approx(s.core)
    assert elec == pytest.approx(s.electrostatic)


def test_too_short_to_score_raises():
    with pytest.raises(ValueError):
        score_pair("MKQLEDK", "MKQLEDK")


# --- library ---------------------------------------------------------------

def test_library_loads_and_every_entry_registers():
    lib = load_library()
    assert len(lib) >= 5
    for z in lib:
        reg = z.register()
        assert len(reg.sequence) == len(z.sequence.replace(" ", ""))


def test_every_library_entry_declares_provenance():
    for z in load_library():
        assert z.reference, f"{z.name} has no reference"
        assert z.recall in ("high", "medium"), f"{z.name} has no recall tag"


def test_screen_returns_sorted_hits():
    hits = screen(GCN4)
    assert len(hits) == len(load_library())
    specs = [h.specificity for h in hits]
    assert specs == sorted(specs)


def test_fasta_library_parses():
    from lz.library import _parse_fasta

    zippers = _parse_fasta(f">one\n{GCN4[:20]}\n{GCN4[20:]}\n>two\n{GCN4}\n")
    assert [z.name for z in zippers] == ["one", "two"]
    assert zippers[0].sequence == GCN4


# --- design ----------------------------------------------------------------

def test_design_is_reproducible_with_a_seed():
    kw = dict(n_restarts=2, n_steps=300, seed=7)
    a = design_partner(GCN4, **kw)
    b = design_partner(GCN4, **kw)
    assert [d.sequence for d in a] == [d.sequence for d in b]


def test_designs_respect_the_position_alphabets():
    from lz.design import ALPHABET

    for d in design_partner(GCN4, n_restarts=2, n_steps=300, seed=1):
        reg = d.register()
        for i, res in enumerate(reg.sequence):
            assert res in ALPHABET[reg.position(i)]


def test_design_puts_leucine_in_the_d_layer():
    best = design_partner(GCN4, n_restarts=4, n_steps=2000, seed=3)[0]
    reg = best.register()
    d_res = reg.residues_at("d")
    assert d_res.count("L") / len(d_res) >= 0.5, d_res


def test_design_beats_a_random_partner():
    best = design_partner(GCN4, n_restarts=4, n_steps=2000, seed=5)[0]
    scrambled = "AEQKSRAEQKSRAEQKSRAEQKSRAEQKSRAEQK"[: len(best.sequence)]
    assert best.hetero.total < score_pair(GCN4, scrambled).total


def test_design_rejects_sequences_shorter_than_two_heptads():
    with pytest.raises(ValueError):
        design_partner(GCN4, length=10)


def test_fixed_residues_are_honoured():
    pinned = {0: "A", 7: "A"}
    for d in design_partner(GCN4, n_restarts=2, n_steps=200, seed=2,
                            fixed=pinned):
        for i, r in pinned.items():
            assert d.sequence[i] == r
