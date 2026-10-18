"""Desktop front end: load a structure, get a ranked list of partners.

Tkinter rather than a web UI, for three reasons that matter here: it ships
with Python so there is nothing to install, it gets a native file dialog for
the PDB the user wants to open, and it runs with no server and no network --
which is what you want for unpublished structures.

Everything slow runs on a worker thread. Tk is not thread-safe, so workers
never touch widgets; they post results back through a queue that the main
thread drains on a timer.
"""

from __future__ import annotations

import csv
import queue
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .design import design_partner
from .export import TRIAGE_NOTES, write_multimer_fasta
from .heptad import assign_register
from .library import load_library, screen
from .orthogonal import DEFAULT_CROSS_MARGIN, design_orthogonal_set
from .structure import StructureError, analyse

APP_TITLE = "lz - Leucine Zipper Partner Finder"

# Treeview columns: (key, width, anchor). Headings come from the Mode,
# because the same three numeric columns answer different questions
# depending on which button produced them.
COLUMNS = [
    ("name", 120, "w"),
    ("source", 90, "w"),
    ("sequence", 300, "w"),
    ("hetero", 95, "e"),
    ("self", 95, "e"),
    ("spec", 110, "e"),
    ("verdict", 200, "w"),
]


@dataclass(frozen=True)
class Mode:
    """How to label a result set.

    Screening and partner design answer "does this candidate prefer the
    target over itself?", a two-body question. Orthogonal set design answers
    "does each pair beat every other interaction in the set?", which is a
    property of the whole set and is computed against a different
    competitor. Both fill the same three numeric columns with genuinely
    different quantities, so each mode supplies its own headings. Labelling
    them all "specificity = binding - homodimer" was true for two modes out
    of three and quietly wrong for the third.
    """

    key: str
    headings: dict[str, str]
    footnote: str

    def heading(self, column: str) -> str:
        return self.headings.get(column, column)


PAIRWISE = Mode(
    key="pairwise",
    headings={
        "name": "name",
        "source": "source",
        "sequence": "sequence",
        "hetero": "binds target",
        "self": "self-pairs",
        "spec": "specificity",
        "verdict": "verdict",
    },
    footnote=(
        "binds target = this candidate paired with your target.   "
        "self-pairs = the same candidate paired with itself.   "
        "specificity = binds target - self-pairs, so negative means the "
        "candidate prefers your target over its own homodimer. "
        "All three are uncalibrated rankings, NOT energies or affinities."
    ),
)

SET_WIDE = Mode(
    key="set",
    headings={
        "name": "chain",
        "source": "pair",
        "sequence": "sequence",
        "hetero": "cognate pair",
        "self": "self-pairs",
        "spec": "margin vs set",
        "verdict": "intended partner / worst cross-talk",
    },
    footnote=(
        "cognate pair = this chain with its intended partner.   "
        "self-pairs = this chain with itself.   "
        "margin vs set = the pair's cognate score minus the BEST unwanted "
        "interaction anywhere in the set, which is often a different chain "
        "rather than the homodimer. Negative means the intended pair wins; "
        "it must beat the competition by the design margin to be usable. "
        "Uncalibrated rankings, NOT energies or affinities."
    ),
)


@dataclass
class Row:
    """One ranked candidate, as shown in the table and written to CSV."""

    name: str
    source: str
    sequence: str
    hetero: float
    self_score: float
    spec: float
    verdict: str

    def values(self) -> tuple:
        return (
            self.name,
            self.source,
            self.sequence,
            f"{self.hetero:+.2f}",
            f"{self.self_score:+.2f}",
            f"{self.spec:+.2f}",
            self.verdict,
        )


class App(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=8)
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        self.pdb_path: Path | None = None
        self.target = None          # Register
        self.rows: list[Row] = []
        self.mode: Mode = PAIRWISE
        self.sort_key: str | None = None
        self.sort_desc = False
        self._queue: queue.Queue = queue.Queue()
        self._busy = False

        self._build_file_bar()
        self._build_structure_panel()
        self._build_actions()
        self._build_table()
        self._build_status()

        self.after(100, self._drain)

    # --- layout ------------------------------------------------------------

    def _build_file_bar(self) -> None:
        bar = ttk.LabelFrame(self, text="1. target structure", padding=6)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        bar.columnconfigure(1, weight=1)

        ttk.Button(bar, text="Open PDB...", command=self.open_pdb).grid(
            row=0, column=0, padx=(0, 8)
        )
        self.path_var = tk.StringVar(value="no file loaded")
        ttk.Label(bar, textvariable=self.path_var).grid(row=0, column=1, sticky="w")

        ttk.Label(bar, text="chain:").grid(row=0, column=2, padx=(8, 2))
        self.chain_var = tk.StringVar()
        self.chain_box = ttk.Combobox(
            bar, textvariable=self.chain_var, width=5, state="readonly"
        )
        self.chain_box.grid(row=0, column=3)
        self.chain_box.bind("<<ComboboxSelected>>", lambda _e: self._reanalyse())

        ttk.Label(bar, text="  or sequence:").grid(row=0, column=4, padx=(8, 2))
        self.seq_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self.seq_var, width=28).grid(row=0, column=5)
        ttk.Button(bar, text="Use", command=self.use_sequence).grid(
            row=0, column=6, padx=(4, 0)
        )

    def _build_structure_panel(self) -> None:
        frame = ttk.LabelFrame(self, text="2. measured geometry", padding=6)
        frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        frame.columnconfigure(0, weight=1)

        self.info = tk.Text(frame, height=9, wrap="none",
                            font=("Consolas", 9), state="disabled")
        self.info.grid(row=0, column=0, sticky="ew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.info.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.info.configure(yscrollcommand=scroll.set)
        self.info.tag_configure("warn", foreground="#b00020")

    def _build_actions(self) -> None:
        frame = ttk.LabelFrame(self, text="3. find partners", padding=6)
        frame.grid(row=2, column=0, sticky="ew", pady=(0, 6))

        self.btn_screen = ttk.Button(
            frame, text="Screen known zippers", command=self.run_screen
        )
        self.btn_screen.grid(row=0, column=0, padx=(0, 6))

        self.btn_design = ttk.Button(
            frame, text="Design partners", command=self.run_design
        )
        self.btn_design.grid(row=0, column=1, padx=(0, 6))

        ttk.Label(frame, text="pairs:").grid(row=0, column=2)
        self.pairs_var = tk.IntVar(value=2)
        ttk.Spinbox(frame, from_=1, to=5, width=3,
                    textvariable=self.pairs_var).grid(row=0, column=3, padx=(2, 6))

        self.btn_ortho = ttk.Button(
            frame, text="Design orthogonal set", command=self.run_orthogonal
        )
        self.btn_ortho.grid(row=0, column=4, padx=(0, 16))

        self.btn_csv = ttk.Button(
            frame, text="Save CSV...", command=self.save_csv, state="disabled"
        )
        self.btn_csv.grid(row=0, column=5, padx=(0, 6))
        self.btn_fasta = ttk.Button(
            frame, text="Save AlphaFold FASTA...", command=self.save_fasta,
            state="disabled",
        )
        self.btn_fasta.grid(row=0, column=6)

    def _build_table(self) -> None:
        frame = ttk.LabelFrame(self, text="4. ranked candidates", padding=6)
        frame.grid(row=3, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            frame, columns=[c[0] for c in COLUMNS], show="headings",
            selectmode="browse",
        )
        for key, width, anchor in COLUMNS:
            self.tree.heading(
                key, text=key, command=lambda k=key: self._sort_by(k)
            )
            self.tree.column(key, width=width, anchor=anchor,
                             stretch=(key == "sequence"))
        self.tree.grid(row=0, column=0, sticky="nsew")

        vs = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        vs.grid(row=0, column=1, sticky="ns")
        hs = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        hs.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)

        self.tree.tag_configure("good", background="#e8f5e9")
        self.tree.tag_configure("bad", background="#fdecea")

        self.footnote_var = tk.StringVar()
        ttk.Label(
            frame, textvariable=self.footnote_var,
            wraplength=1020, foreground="#555", justify="left",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self._apply_mode(PAIRWISE)

    def _build_status(self) -> None:
        bar = ttk.Frame(self)
        bar.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        bar.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="Open a PDB file, or type a sequence.")
        ttk.Label(bar, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(bar, mode="determinate", length=200)
        self.progress.grid(row=0, column=1, sticky="e")

    # --- loading the target ------------------------------------------------

    def open_pdb(self) -> None:
        path = filedialog.askopenfilename(
            title="Open a coiled-coil structure",
            filetypes=[("PDB files", "*.pdb *.ent"), ("All files", "*.*")],
        )
        if not path:
            return
        self.pdb_path = Path(path)
        self.path_var.set(self.pdb_path.name)
        self.chain_var.set("")
        self._reanalyse()

    def _reanalyse(self) -> None:
        if self.pdb_path is None:
            return
        chain = self.chain_var.get() or None
        try:
            analysis, helices, ligands = analyse(self.pdb_path, chain)
        except StructureError as exc:
            self._set_info(f"Could not read this structure:\n\n{exc}", warn=True)
            self.target = None
            self.status_var.set("Structure could not be read.")
            return

        chains = sorted({h.chain for h in helices})
        self.chain_box["values"] = chains
        if not self.chain_var.get():
            self.chain_var.set(analysis.segment.chain if analysis else chains[0])

        lines, warn = [], False
        for h in helices:
            lines.append(
                f"chain {h.chain}  {len(h):>3} res  "
                f"{h.residues[0].label}-{h.residues[-1].label}"
            )
        lines.append("")

        if analysis is None:
            seg = helices[0]
            self.target = assign_register(seg.sequence)
            lines.append(
                "Only one helix in this file, so there is no partner to\n"
                "measure a register against. Falling back to sequence\n"
                f"prediction: offset {self.target.offset}, "
                f"confidence {self.target.confidence:.2f}."
            )
            warn = True
        else:
            lines.append(analysis.report())
            self.target = assign_register(
                analysis.segment.sequence, analysis.offset
            )
            if not analysis.parallel:
                lines.append(
                    "\nWARNING: this bundle is ANTIPARALLEL. Every score in\n"
                    "this program assumes a PARALLEL dimer, so the rankings\n"
                    "below do not apply to this structure."
                )
                warn = True
            register_warning = analysis.register_warning
            if register_warning:
                lines.append(f"\nWARNING: {register_warning}.")
                warn = True

        if ligands:
            names = ", ".join(sorted({l.name for l in ligands}))
            lines.append(f"\nnon-polymer groups in file: {names}")

        self._set_info("\n".join(lines), warn=warn)
        self.status_var.set(
            f"Target: {len(self.target.sequence)} residues, "
            f"heptad offset {self.target.offset}."
        )

    def use_sequence(self) -> None:
        raw = self.seq_var.get().strip()
        if not raw:
            return
        try:
            self.target = assign_register(raw)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self.pdb_path = None
        self.path_var.set("(sequence entered by hand)")
        self.chain_box["values"] = []
        self._set_info(
            self.target.annotate()
            + f"\n\npredicted offset {self.target.offset}, "
              f"confidence {self.target.confidence:.2f}\n\n"
              "Register PREDICTED from sequence. Load a structure to have it\n"
              "measured instead -- that is the more reliable input.",
        )
        self.status_var.set("Target set from sequence.")

    def _set_info(self, text: str, warn: bool = False) -> None:
        self.info.configure(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("1.0", text, ("warn",) if warn else ())
        self.info.configure(state="disabled")

    # --- running work ------------------------------------------------------

    def _require_target(self) -> bool:
        if self.target is None:
            messagebox.showinfo(
                APP_TITLE, "Load a PDB file or enter a sequence first."
            )
            return False
        if self._busy:
            messagebox.showinfo(APP_TITLE, "Still working on the last request.")
            return False
        return True

    def _start(self, label: str, fn) -> None:
        self._busy = True
        for b in (self.btn_screen, self.btn_design, self.btn_ortho):
            b.state(["disabled"])
        self.status_var.set(label)
        self.progress["value"] = 0

        def worker() -> None:
            try:
                self._queue.put(("done", fn()))
            except Exception:
                self._queue.put(("error", traceback.format_exc()))

        threading.Thread(target=worker, daemon=True).start()

    def _drain(self) -> None:
        """Main-thread pump. Workers post here; only this touches widgets.

        Returns without rescheduling once the widget is gone, so closing the
        window while a design is still running does not leave a timer firing
        against destroyed widgets.
        """
        if not self.winfo_exists():
            return
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "progress":
                    fraction, text = payload
                    self.progress["value"] = fraction * 100
                    self.status_var.set(text)
                elif kind == "done":
                    self._finish(payload)
                elif kind == "error":
                    self._busy = False
                    for b in (self.btn_screen, self.btn_design, self.btn_ortho):
                        b.state(["!disabled"])
                    self.status_var.set("Failed.")
                    messagebox.showerror(APP_TITLE, payload)
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _apply_mode(self, mode: Mode) -> None:
        """Relabel the table for the question the current results answer."""
        self.mode = mode
        for key, _, _ in COLUMNS:
            self.tree.heading(key, text=mode.heading(key))
        self.footnote_var.set(mode.footnote)

    def _finish(self, payload: tuple[Mode, list[Row]]) -> None:
        mode, rows = payload
        self._busy = False
        for b in (self.btn_screen, self.btn_design, self.btn_ortho):
            b.state(["!disabled"])
        self.progress["value"] = 100
        self.rows = rows
        self._apply_mode(mode)
        self._refresh_table()

        good = sum(1 for r in rows if r.spec < 0)
        if mode is SET_WIDE:
            self.status_var.set(
                f"{len(rows)} designed chains; {good} ahead of the best "
                "competing interaction in the set."
            )
        else:
            self.status_var.set(
                f"{len(rows)} candidates, {good} predicted to prefer the "
                "target over their own homodimer."
            )
        state = "normal" if rows else "disabled"
        self.btn_csv.configure(state=state)
        self.btn_fasta.configure(state=state)

    def _report_progress(self, fraction: float, text: str) -> None:
        self._queue.put(("progress", (fraction, text)))

    # --- the three analyses ------------------------------------------------

    def run_screen(self) -> None:
        if not self._require_target():
            return
        target = self.target

        def work() -> tuple[Mode, list[Row]]:
            rows = []
            for hit in screen(target, load_library()):
                rows.append(Row(
                    name=hit.zipper.name,
                    source="library",
                    sequence=hit.zipper.sequence,
                    hetero=hit.score.total,
                    self_score=hit.self_score.total,
                    spec=hit.specificity,
                    verdict=("binds target"
                             if hit.specificity < 0 else "loses to homodimer"),
                ))
            return PAIRWISE, rows

        self._start("Screening the library...", work)

    def run_design(self) -> None:
        if not self._require_target():
            return
        target = self.target

        def work() -> tuple[Mode, list[Row]]:
            self._report_progress(0.1, "Designing partners...")
            designs = design_partner(target, n_restarts=8, n_steps=4000)
            self._report_progress(0.9, "Scoring designs...")
            rows = []
            for i, d in enumerate(designs, 1):
                rows.append(Row(
                    name=f"design_{i}",
                    source="designed",
                    sequence=d.sequence,
                    hetero=d.hetero.total,
                    self_score=d.partner_self.total,
                    spec=d.specificity,
                    verdict=("binds target"
                             if d.specificity < 0 else "loses to homodimer"),
                ))
            return PAIRWISE, rows

        self._start("Designing partners...", work)

    def run_orthogonal(self) -> None:
        if not self._require_target():
            return
        target = self.target
        n_pairs = max(1, int(self.pairs_var.get()))

        def work() -> tuple[Mode, list[Row]]:
            result = design_orthogonal_set(
                n_pairs=n_pairs,
                fixed=target,
                n_restarts=3,
                n_steps=5000,
                progress=self._report_progress,
            )
            rows = []
            for i, (name, seq) in enumerate(
                zip(result.names, result.sequences)
            ):
                if i == result.fixed_index:
                    continue
                pair = i // 2
                cognate = result.cognate(i)
                worst, n1, n2 = result.worst_offtarget(pair)
                rows.append(Row(
                    name=name,
                    source=f"set pair {pair + 1}",
                    sequence=seq,
                    hetero=result.matrix[i][cognate],
                    self_score=result.matrix[i][i],
                    spec=result.margin_for(pair),
                    verdict=(
                        f"partner of {result.names[cognate]}; "
                        f"worst cross {n1}-{n2}"
                    ),
                ))
            self._queue.put(("progress", (1.0, result.matrix_report())))
            return SET_WIDE, rows

        self._start(
            f"Designing {n_pairs} orthogonal pair(s) around the target...", work
        )

    # --- table -------------------------------------------------------------

    def _sort_by(self, key: str) -> None:
        if self.sort_key == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = key, False
        self._refresh_table()

    def _refresh_table(self) -> None:
        rows = list(self.rows)
        key = self.sort_key or "spec"
        numeric = key in ("hetero", "self", "spec")

        def sort_value(r: Row):
            return {
                "name": r.name, "source": r.source, "sequence": r.sequence,
                "hetero": r.hetero, "self": r.self_score, "spec": r.spec,
                "verdict": r.verdict,
            }[key]

        rows.sort(key=sort_value, reverse=self.sort_desc)
        if numeric and not self.sort_desc:
            pass  # ascending = most negative = best, which is what we want

        self.tree.delete(*self.tree.get_children())
        for r in rows:
            self.tree.insert(
                "", "end", values=r.values(),
                tags=("good" if r.spec < 0 else "bad",),
            )

    # --- export ------------------------------------------------------------

    def save_csv(self) -> None:
        if not self.rows:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile="lz_candidates.csv",
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            # A comment row carrying the footnote: the numbers mean different
            # things per mode, and a CSV read next month has no other way to
            # say which question it answered.
            w.writerow([f"# {self.mode.key} results - {self.mode.footnote}"])
            w.writerow([
                self.mode.heading(key).replace(" ", "_")
                for key, _, _ in COLUMNS
            ])
            for r in self.rows:
                w.writerow([r.name, r.source, r.sequence,
                            f"{r.hetero:.3f}", f"{r.self_score:.3f}",
                            f"{r.spec:.3f}", r.verdict])
        self.status_var.set(f"Wrote {path}")

    def save_fasta(self) -> None:
        if not self.rows or self.target is None:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".fasta", filetypes=[("FASTA", "*.fasta")],
            initialfile="complexes.fasta",
        )
        if not path:
            return
        candidates = {r.name: r.sequence for r in self.rows}
        write_multimer_fasta(path, self.target.sequence, candidates)
        self.status_var.set(f"Wrote {path}")
        messagebox.showinfo(
            APP_TITLE,
            f"Wrote {Path(path).name} for ColabFold / AlphaFold-Multimer.\n\n"
            + TRIAGE_NOTES,
        )


def _icon_path() -> Path | None:
    """Locate lz.ico next to the source tree, or inside a frozen bundle."""
    import sys

    base = getattr(sys, "_MEIPASS", None)
    candidate = (
        Path(base) / "lz.ico" if base
        else Path(__file__).resolve().parent.parent / "lz.ico"
    )
    return candidate if candidate.exists() else None


def selftest(report_path: str | Path) -> int:
    """Exercise the parts of a frozen build that fail silently, write a report.

    A windowed .exe has no stdout, so a packaging mistake -- most often the
    bundled zipper library not being found -- shows up only as an error
    dialog after someone clicks a button. This runs the same code paths
    headlessly and writes the result to a file, so a build can be verified
    on a machine with no Python installed:

        lz.exe --selftest report.txt
    """
    import sys

    lines: list[str] = []
    failures = 0

    frozen = getattr(sys, "frozen", False)
    lines.append(f"frozen: {frozen}")
    lines.append(f"_MEIPASS: {getattr(sys, '_MEIPASS', '(not set)')}")

    def check(name: str, fn) -> None:
        nonlocal failures
        try:
            result = fn()
            if result is False:
                raise ValueError("check returned False")
            lines.append(f"PASS  {name}: {result}")
        except Exception as exc:
            failures += 1
            lines.append(f"FAIL  {name}: {type(exc).__name__}: {exc}")

    from .library import DEFAULT_LIBRARY

    lines.append(f"library path: {DEFAULT_LIBRARY}")
    check("library file exists", lambda: DEFAULT_LIBRARY.exists())
    check("library loads", lambda: f"{len(load_library())} zippers")

    target = assign_register("RMKQLEDKVEELLSKNYHLENEVARLKKLVGER")
    check("register assignment", lambda: f"offset {target.offset}")
    check("screening", lambda: f"{len(screen(target, load_library()))} hits")
    check(
        "partner design",
        lambda: design_partner(target, n_restarts=1, n_steps=200)[0].sequence,
    )
    check(
        "orthogonal design",
        lambda: design_orthogonal_set(
            n_pairs=2, fixed=target, n_restarts=1, n_steps=200
        ).sequences[1],
    )
    if frozen:
        check("icon bundled", lambda: _icon_path() is not None)
    else:
        lines.append(f"INFO  optional source icon: {_icon_path()}")

    lines.append("")
    lines.append("OK" if failures == 0 else f"{failures} CHECK(S) FAILED")
    Path(report_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    import sys

    args = sys.argv[1:] if argv is None else argv
    if args and args[0] == "--selftest":
        return selftest(args[1] if len(args) > 1 else "lz-selftest.txt")

    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("1100x820")
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass

    icon = _icon_path()
    if icon is not None:
        try:
            root.iconbitmap(default=str(icon))
        except tk.TclError:
            pass  # a missing or malformed icon must never block startup
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
