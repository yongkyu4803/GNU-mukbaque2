"""Tests for the desktop app.

The app is driven directly rather than through `mainloop`: widgets are
created, methods called, and the worker queue drained by hand. That catches
the wiring mistakes reading the code does not -- a callback bound to a
missing method, a column key that no Row field supplies, a worker touching a
widget from the wrong thread.

Skipped wholesale where Tk cannot open a display.
"""

from __future__ import annotations

import csv
import gc
import time

import pytest

tk = pytest.importorskip("tkinter")

from lz.gui import COLUMNS, App, Row  # noqa: E402

from .make_structure import write_dimer  # noqa: E402

GCN4 = "RMKQLEDKVEELLSKNYHLENEVARLKKLVGER"


@pytest.fixture(scope="module")
def root():
    """One Tk root for the whole module.

    Creating and destroying a root per test exhausts something in Tk on
    Windows after a dozen or so: later tests fail with "tk wasn't installed
    properly" from tk.tcl, and which tests fail varies run to run. Sharing
    one root and rebuilding only the App frame keeps it deterministic.
    """
    try:
        r = tk.Tk()
    except tk.TclError as exc:  # no display
        pytest.skip(f"Tk unavailable: {exc}")
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture
def app(root):
    widget = App(root)
    yield widget
    widget.destroy()
    # Finalise the destroyed App's Tk variables here, on the main thread.
    # Left to chance they are collected whenever the next allocation happens
    # -- which, in the tests that start a worker, is on the worker thread,
    # and Variable.__del__ raises "main thread is not in main loop" there.
    gc.collect()


@pytest.fixture
def dimer(tmp_path):
    return write_dimer(tmp_path / "dimer.pdb", GCN4, start_position="g")


def _pump(app, timeout=120.0):
    """Run the app's queue pump until the worker finishes."""
    deadline = time.time() + timeout
    while app._busy and time.time() < deadline:
        app.update()
        time.sleep(0.02)
    app.update()
    assert not app._busy, "worker did not finish in time"


# --- static wiring ---------------------------------------------------------

def test_every_table_column_is_supplied_by_a_row():
    row = Row("n", "s", "SEQ", -1.0, -2.0, 1.0, "v")
    assert len(row.values()) == len(COLUMNS)


def test_buttons_start_sensible(app):
    assert str(app.btn_csv["state"]) == "disabled"
    assert str(app.btn_fasta["state"]) == "disabled"


def test_actions_refuse_without_a_target(app, monkeypatch):
    called = []
    monkeypatch.setattr("lz.gui.messagebox.showinfo",
                        lambda *a, **k: called.append(a))
    app.run_screen()
    app.run_design()
    app.run_orthogonal()
    assert len(called) == 3
    assert not app._busy


# --- loading a target ------------------------------------------------------

def test_loading_a_structure_measures_the_register(app, dimer):
    app.pdb_path = dimer
    app._reanalyse()
    assert app.target is not None
    assert app.target.offset == 6
    assert app.target.sequence == GCN4
    assert "parallel" in app.info.get("1.0", "end")


def test_chain_list_is_populated_from_the_file(app, dimer):
    app.pdb_path = dimer
    app._reanalyse()
    assert list(app.chain_box["values"]) == ["A", "B"]


def test_switching_chain_reanalyses(app, dimer):
    app.pdb_path = dimer
    app._reanalyse()
    app.chain_var.set("B")
    app._reanalyse()
    assert "chain B vs chain A" in app.info.get("1.0", "end")


def test_antiparallel_structure_is_flagged_in_the_panel(app, tmp_path):
    app.pdb_path = write_dimer(tmp_path / "anti.pdb", GCN4, parallel=False)
    app._reanalyse()
    assert "ANTIPARALLEL" in app.info.get("1.0", "end")


def test_unreadable_structure_does_not_crash_the_app(app, tmp_path):
    bad = tmp_path / "bad.pdb"
    bad.write_text("HEADER NOTHING\nEND\n", encoding="utf-8")
    app.pdb_path = bad
    app._reanalyse()
    assert app.target is None
    assert "Could not read" in app.info.get("1.0", "end")


def test_sequence_entry_sets_a_target(app):
    app.seq_var.set(GCN4)
    app.use_sequence()
    assert app.target.sequence == GCN4
    assert "PREDICTED" in app.info.get("1.0", "end")


def test_invalid_sequence_is_reported_not_raised(app, monkeypatch):
    errors = []
    monkeypatch.setattr("lz.gui.messagebox.showerror",
                        lambda *a, **k: errors.append(a))
    app.seq_var.set("not a sequence!!")
    app.use_sequence()
    assert errors
    assert app.target is None


# --- running the analyses --------------------------------------------------

def test_screen_fills_the_table(app, dimer):
    app.pdb_path = dimer
    app._reanalyse()
    app.run_screen()
    _pump(app)

    assert app.rows
    assert len(app.tree.get_children()) == len(app.rows)
    assert str(app.btn_csv["state"]) == "normal"


def test_design_produces_rows_that_prefer_the_target(app, dimer):
    app.pdb_path = dimer
    app._reanalyse()
    app.run_design()
    _pump(app)

    assert app.rows
    assert any(r.spec < 0 for r in app.rows)
    assert all(r.source == "designed" for r in app.rows)


def test_orthogonal_run_excludes_the_fixed_target_from_the_table(app, dimer):
    app.pdb_path = dimer
    app._reanalyse()
    app.pairs_var.set(2)
    app.run_orthogonal()
    _pump(app)

    assert app.rows
    assert all(r.name != "TARGET" for r in app.rows)
    # 2 pairs = 4 chains, minus the pinned target.
    assert len(app.rows) == 3


def test_worker_errors_surface_as_a_dialog(app, monkeypatch):
    shown = []
    monkeypatch.setattr("lz.gui.messagebox.showerror",
                        lambda *a, **k: shown.append(a))
    app.target = object()  # not a Register, so the worker will raise

    def boom():
        raise RuntimeError("deliberate")

    app._start("testing", boom)
    _pump(app, timeout=10)
    assert shown
    assert "deliberate" in shown[0][1]
    assert str(app.btn_screen["state"]) == "normal"


# --- table behaviour -------------------------------------------------------

def test_table_starts_in_pairwise_mode(app):
    from lz.gui import PAIRWISE

    assert app.mode is PAIRWISE
    assert app.tree.heading("spec")["text"] == "specificity"
    assert "binds target - self-pairs" in app.footnote_var.get()


def test_screen_and_design_label_the_table_pairwise(app, dimer):
    from lz.gui import PAIRWISE

    app.pdb_path = dimer
    app._reanalyse()
    app.run_screen()
    _pump(app)
    assert app.mode is PAIRWISE
    assert app.tree.heading("hetero")["text"] == "binds target"


def test_orthogonal_relabels_the_table_for_a_set(app, dimer):
    """The fix for the mislabelling: set-wide results get set-wide headings.

    `spec` holds the margin against the best competing interaction anywhere
    in the set, not binding minus homodimer, so it must not be called
    "specificity" or described by the pairwise footnote.
    """
    from lz.gui import SET_WIDE

    app.pdb_path = dimer
    app._reanalyse()
    app.pairs_var.set(2)
    app.run_orthogonal()
    _pump(app)

    assert app.mode is SET_WIDE
    assert app.tree.heading("spec")["text"] == "margin vs set"
    assert app.tree.heading("hetero")["text"] == "cognate pair"
    assert app.tree.heading("name")["text"] == "chain"
    footnote = app.footnote_var.get()
    assert "best unwanted interaction" in footnote.lower()
    assert "binds target - self-pairs" not in footnote


def test_switching_back_to_screening_restores_pairwise_labels(app, dimer):
    from lz.gui import PAIRWISE

    app.pdb_path = dimer
    app._reanalyse()
    app.pairs_var.set(1)
    app.run_orthogonal()
    _pump(app)
    app.run_screen()
    _pump(app)

    assert app.mode is PAIRWISE
    assert app.tree.heading("spec")["text"] == "specificity"


def test_every_mode_labels_every_column_explicitly():
    """No column may fall back to its internal key as a heading.

    `Mode.heading` returns the key when a mode forgets a column, which would
    silently show "hetero" or "spec" in the UI. Requiring an explicit entry
    means adding a column forces every mode to say what it means there.
    """
    from lz.gui import PAIRWISE, SET_WIDE

    for mode in (PAIRWISE, SET_WIDE):
        for key, _, _ in COLUMNS:
            assert key in mode.headings, (mode.key, key)


def test_the_two_modes_disagree_on_the_numeric_columns():
    """If the modes labelled these the same, there was nothing to fix."""
    from lz.gui import PAIRWISE, SET_WIDE

    for key in ("hetero", "spec"):
        assert PAIRWISE.heading(key) != SET_WIDE.heading(key), key
    assert PAIRWISE.footnote != SET_WIDE.footnote


def test_status_line_matches_the_mode(app, dimer):
    app.pdb_path = dimer
    app._reanalyse()
    app.run_screen()
    _pump(app)
    assert "own homodimer" in app.status_var.get()

    app.pairs_var.set(2)
    app.run_orthogonal()
    _pump(app)
    assert "competing interaction" in app.status_var.get()


def test_sorting_toggles_direction(app):
    app.rows = [
        Row("a", "s", "AAA", -1.0, 0.0, -1.0, "v"),
        Row("b", "s", "BBB", -3.0, 0.0, -3.0, "v"),
    ]
    app._sort_by("spec")
    first = app.tree.item(app.tree.get_children()[0])["values"][0]
    app._sort_by("spec")
    second = app.tree.item(app.tree.get_children()[0])["values"][0]
    assert first != second


def test_rows_are_tagged_by_verdict(app):
    app.rows = [
        Row("good", "s", "AAA", -3.0, 0.0, -3.0, "v"),
        Row("bad", "s", "BBB", -1.0, -2.0, 1.0, "v"),
    ]
    app._refresh_table()
    tags = {
        app.tree.item(i)["values"][0]: app.tree.item(i)["tags"][0]
        for i in app.tree.get_children()
    }
    assert tags["good"] == "good"
    assert tags["bad"] == "bad"


# --- export ----------------------------------------------------------------

def _read_csv(path):
    """Read an exported CSV, returning (comment, rows)."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        comment = next(reader)[0]
        header = next(reader)
        rows = [dict(zip(header, r)) for r in reader]
    return comment, rows


def test_csv_export_round_trips(app, tmp_path, monkeypatch):
    app.rows = [Row("x", "designed", "SEQSEQ", -5.0, -2.0, -3.0, "binds")]
    out = tmp_path / "out.csv"
    monkeypatch.setattr("lz.gui.filedialog.asksaveasfilename",
                        lambda **k: str(out))
    app.save_csv()

    comment, rows = _read_csv(out)
    assert comment.startswith("#")
    assert rows[0]["name"] == "x"
    assert float(rows[0]["specificity"]) == pytest.approx(-3.0)


def test_csv_header_follows_the_mode(app, tmp_path, monkeypatch):
    """The exported header must say which question the numbers answer.

    Exporting set-wide results under the pairwise header was the same
    mislabelling as the on-screen one, preserved in a file that outlives the
    session.
    """
    from lz.gui import SET_WIDE

    app.rows = [Row("A'", "set pair 1", "SEQ", -18.0, -14.0, -3.5, "x")]
    app._apply_mode(SET_WIDE)
    out = tmp_path / "set.csv"
    monkeypatch.setattr("lz.gui.filedialog.asksaveasfilename",
                        lambda **k: str(out))
    app.save_csv()

    comment, rows = _read_csv(out)
    assert "set" in comment
    assert "margin_vs_set" in rows[0]
    assert "specificity" not in rows[0]
    assert float(rows[0]["margin_vs_set"]) == pytest.approx(-3.5)


def test_fasta_export_pairs_each_candidate_with_the_target(
    app, dimer, tmp_path, monkeypatch
):
    app.pdb_path = dimer
    app._reanalyse()
    app.rows = [Row("cand", "designed", "SEQ", -5.0, -2.0, -3.0, "binds")]
    out = tmp_path / "complexes.fasta"
    monkeypatch.setattr("lz.gui.filedialog.asksaveasfilename",
                        lambda **k: str(out))
    monkeypatch.setattr("lz.gui.messagebox.showinfo", lambda *a, **k: None)
    app.save_fasta()

    text = out.read_text(encoding="utf-8")
    assert f"{GCN4}:SEQ" in text
    assert "cand__homodimer" in text


# --- packaging self-test ---------------------------------------------------
# These need no display: `selftest` must work in a windowed .exe, where there
# is no console and no way to click anything.

def test_selftest_passes_from_a_source_checkout(tmp_path):
    from lz.gui import selftest

    report = tmp_path / "report.txt"
    assert selftest(report) == 0
    text = report.read_text(encoding="utf-8")
    assert text.rstrip().endswith("OK")
    assert "FAIL" not in text


def test_selftest_checks_the_bundled_library(tmp_path):
    from lz.gui import selftest

    report = tmp_path / "report.txt"
    selftest(report)
    text = report.read_text(encoding="utf-8")
    # The data file is the thing that silently breaks when frozen, so the
    # report must name its resolved path and say whether it loaded.
    assert "library path:" in text
    assert "library loads" in text
    assert "zippers" in text


def test_selftest_reports_failure_when_the_library_is_missing(
    tmp_path, monkeypatch
):
    """A broken build must exit non-zero, not quietly claim success."""
    import lz.gui as gui_mod

    monkeypatch.setattr(
        gui_mod, "load_library",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("gone")),
    )
    report = tmp_path / "report.txt"
    assert gui_mod.selftest(report) != 0
    text = report.read_text(encoding="utf-8")
    assert "FAIL" in text
    assert "CHECK(S) FAILED" in text


def test_gui_main_dispatches_selftest_without_opening_a_window(tmp_path):
    from lz.gui import main as gui_main

    report = tmp_path / "report.txt"
    assert gui_main(["--selftest", str(report)]) == 0
    assert report.exists()


def test_cli_gui_selftest_flag_is_wired(tmp_path):
    from lz.cli import main as cli_main

    report = tmp_path / "report.txt"
    assert cli_main(["gui", "--selftest", str(report)]) == 0
    assert report.exists()


def test_icon_is_found_in_the_source_tree():
    from lz.gui import _icon_path

    # The icon is generated by tools/make_icon.py; if it is missing the app
    # must still start, so this only records which state we are in.
    path = _icon_path()
    assert path is None or path.suffix == ".ico"
