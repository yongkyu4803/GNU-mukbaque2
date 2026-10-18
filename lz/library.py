"""Loading coiled-coil sequence libraries and screening them against a target."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .heptad import Register, assign_register
from .scoring import PairScore, score_pair


def _data_dir() -> Path:
    """Locate the bundled data directory, frozen or not.

    PyInstaller unpacks a one-file build into a temporary directory and
    points `sys._MEIPASS` at it. Resolving data files relative to
    `__file__` works from a checkout and silently breaks inside the .exe,
    where `__file__` points into a non-existent path in the archive.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base is not None:
        return Path(base) / "data"
    return Path(__file__).resolve().parent.parent / "data"


DEFAULT_LIBRARY = _data_dir() / "zippers.json"


@dataclass
class Zipper:
    """One library member."""

    name: str
    sequence: str
    offset: int | None = None
    organism: str = ""
    partners: tuple[str, ...] = ()
    note: str = ""
    reference: str = ""
    recall: str = ""

    def register(self) -> Register:
        return assign_register(self.sequence, self.offset)


@dataclass
class Hit:
    """A library member scored against the target."""

    zipper: Zipper
    score: PairScore
    self_score: PairScore

    @property
    def specificity(self) -> float:
        """How much the candidate prefers the target over its own homodimer.

        Negative means the heterodimer wins, which is what you want. A
        candidate with a great `score` but a comparably great `self_score`
        will mostly sit in solution as its own homodimer.
        """
        return self.score.total - self.self_score.total


def load_library(path: str | Path | None = None) -> list[Zipper]:
    """Load a library from JSON or FASTA.

    JSON is the richer format (see data/zippers.json). FASTA is accepted for
    convenience; heptad registers are then predicted rather than declared.
    """
    p = Path(path) if path else DEFAULT_LIBRARY
    if not p.exists():
        raise FileNotFoundError(f"library not found: {p}")

    # utf-8-sig, not utf-8: editors on Windows routinely leave a BOM, and
    # json.loads chokes on it with a confusing "Expecting value" error.
    text = p.read_text(encoding="utf-8-sig")
    if p.suffix.lower() in (".fa", ".fasta", ".faa") or text.lstrip().startswith(">"):
        return _parse_fasta(text)
    return _parse_json(text)


def _parse_json(text: str) -> list[Zipper]:
    raw = json.loads(text)
    entries = raw["zippers"] if isinstance(raw, dict) else raw
    out = []
    for e in entries:
        out.append(
            Zipper(
                name=e["name"],
                sequence=e["sequence"],
                offset=e.get("offset"),
                organism=e.get("organism", ""),
                partners=tuple(e.get("partners", ())),
                note=e.get("note", ""),
                reference=e.get("reference", ""),
                recall=e.get("recall", ""),
            )
        )
    return out


def _parse_fasta(text: str) -> list[Zipper]:
    out: list[Zipper] = []
    name: str | None = None
    chunks: list[str] = []

    def flush() -> None:
        if name is not None and chunks:
            out.append(Zipper(name=name, sequence="".join(chunks)))

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            flush()
            name = line[1:].split()[0] if len(line) > 1 else f"seq{len(out) + 1}"
            chunks = []
        else:
            chunks.append(line)
    flush()
    return out


def screen(
    target: str | Register,
    library: list[Zipper] | None = None,
    weights: dict[str, float] | None = None,
) -> list[Hit]:
    """Score every library member against `target`, best first.

    Sorted by `specificity`, not by raw score: a binder that outcompetes its
    own homodimer is more useful than a stickier but promiscuous one.
    """
    reg = target if isinstance(target, Register) else assign_register(target)
    members = library if library is not None else load_library()

    hits = []
    for z in members:
        zreg = z.register()
        hits.append(
            Hit(
                zipper=z,
                score=score_pair(reg, zreg, weights),
                self_score=score_pair(zreg, zreg, weights),
            )
        )
    hits.sort(key=lambda h: (h.specificity, h.score.total))
    return hits
