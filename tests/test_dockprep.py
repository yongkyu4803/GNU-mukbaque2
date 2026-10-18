"""Tests for docking-input preparation and the structure-aware CLI paths."""

from __future__ import annotations

import pytest

from lz.cli import main
from lz.dockprep import find_site, write_receptor, write_vina_config
from lz.structure import StructureError, _distance, analyse

from .make_structure import build_dimer, write_dimer

GCN4 = "RMKQLEDKVEELLSKNYHLENEVARLKKLVGER"


@pytest.fixture
def dimer(tmp_path):
    return write_dimer(tmp_path / "dimer.pdb", GCN4, start_position="g")


# --- site definition -------------------------------------------------------

def test_box_is_centred_between_the_two_helices(dimer):
    analysis, _, _ = analyse(dimer)
    site = find_site(analysis)

    a_axis = analysis.segment.axis
    b_axis = analysis.partner.axis
    to_a = min(_distance(site.center, p) for p in a_axis)
    to_b = min(_distance(site.center, p) for p in b_axis)
    # Boxing only one helix's residues would put the centre inside it; the
    # box must straddle the groove, so the two distances should be similar.
    assert abs(to_a - to_b) < 1.0, (to_a, to_b)


def test_box_is_never_smaller_than_vina_can_use(dimer):
    analysis, _, _ = analyse(dimer)
    site = find_site(analysis, padding=0.0)
    assert min(site.size) >= 18.0


def test_padding_grows_the_box(dimer):
    analysis, _, _ = analyse(dimer)
    small = find_site(analysis, padding=2.0)
    large = find_site(analysis, padding=10.0)
    assert max(large.size) > max(small.size)


def test_gcn4_interface_reads_as_hydrophobic(dimer):
    analysis, _, _ = analyse(dimer)
    assert find_site(analysis).hydrophobic_fraction > 0.5


def test_long_shallow_groove_is_called_out(dimer):
    analysis, _, _ = analyse(dimer)
    note = find_site(analysis).druggability_note
    assert "peptide" in note


# --- receptor and config files ---------------------------------------------

def test_receptor_keeps_protein_and_drops_everything_else(tmp_path):
    src = tmp_path / "lig.pdb"
    src.write_text(
        build_dimer(GCN4, ligand=("STI", (0.0, 0.0, 20.0))), encoding="utf-8"
    )
    out = write_receptor(src, tmp_path / "receptor.pdb")
    text = out.read_text(encoding="utf-8")

    assert "HETATM" not in text
    assert text.count("ATOM  ") == build_dimer(GCN4).count("ATOM  ")
    assert text.rstrip().endswith("END")


def test_receptor_rejects_a_file_with_no_atoms(tmp_path):
    src = tmp_path / "empty.pdb"
    src.write_text("HEADER  NOTHING\nEND\n", encoding="utf-8")
    with pytest.raises(StructureError):
        write_receptor(src, tmp_path / "out.pdb")


def test_vina_config_has_the_keys_vina_requires(dimer, tmp_path):
    analysis, _, _ = analyse(dimer)
    site = find_site(analysis)
    conf = write_vina_config(tmp_path / "vina.conf", dimer, site)
    text = conf.read_text(encoding="utf-8")

    for key in ("receptor", "center_x", "center_y", "center_z",
                "size_x", "size_y", "size_z", "exhaustiveness"):
        assert f"{key} = " in text, key
    # The config must reference the receptor by bare filename, since Vina
    # resolves it relative to the config's own directory.
    assert "receptor = dimer.pdb" in text


def test_vina_config_carries_the_caveat(dimer, tmp_path):
    analysis, _, _ = analyse(dimer)
    conf = write_vina_config(
        tmp_path / "vina.conf", dimer, find_site(analysis)
    )
    assert "false-positive" in conf.read_text(encoding="utf-8")


# --- CLI -------------------------------------------------------------------

def test_cli_screen_accepts_a_pdb(dimer, capsys):
    assert main(["screen", "--pdb", str(dimer)]) == 0
    out = capsys.readouterr()
    assert "GCN4-p1" in out.out
    assert "heptad offset 6" in out.err  # structure report goes to stderr


def test_cli_screen_requires_a_target(capsys):
    with pytest.raises(SystemExit):
        main(["screen"])


def test_cli_design_accepts_a_pdb(dimer, capsys):
    assert main(["design", "--pdb", str(dimer), "--restarts", "2",
                 "--steps", "200", "--seed", "1"]) == 0
    assert "specificity" in capsys.readouterr().out


def test_cli_pdb_inspect_runs(dimer, capsys):
    assert main(["pdb", str(dimer)]) == 0
    out = capsys.readouterr().out
    assert "orientation   parallel" in out
    assert "ASN16" in out


def test_cli_dockprep_writes_both_files(dimer, tmp_path, capsys):
    out_dir = tmp_path / "docking"
    assert main(["dockprep", str(dimer), "--out-dir", str(out_dir)]) == 0
    assert (out_dir / "receptor.pdb").exists()
    assert (out_dir / "vina.conf").exists()
    assert "did NOT dock" in capsys.readouterr().out


def test_cli_dockprep_refuses_a_single_helix(tmp_path, capsys):
    path = tmp_path / "mono.pdb"
    keep = [
        ln for ln in build_dimer(GCN4).splitlines()
        if not (len(ln) > 21 and ln[21] == "B")
    ]
    path.write_text("\n".join(keep) + "\n", encoding="utf-8")
    assert main(["dockprep", str(path)]) == 1
    assert "no interface" in capsys.readouterr().err


def test_cli_warns_loudly_about_antiparallel_structures(tmp_path, capsys):
    path = write_dimer(tmp_path / "anti.pdb", GCN4, parallel=False)
    main(["screen", "--pdb", str(path)])
    assert "ANTIPARALLEL" in capsys.readouterr().err


def test_cli_reports_a_missing_structure_cleanly(tmp_path, capsys):
    assert main(["pdb", str(tmp_path / "nope.pdb")]) == 1
    assert "file not found" in capsys.readouterr().err
