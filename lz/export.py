"""Hand candidates off to structure prediction (phase C).

Phase A ranks sequences. It cannot tell you whether a pair actually folds
into a parallel two-stranded coil, whether it slips a heptad, or whether it
prefers an antiparallel or higher-order arrangement -- those are structural
questions and need a structural method.

This module writes the input files for that step. It does not run anything:
ColabFold and AlphaFold-Multimer are large external tools, and which one you
use depends on your compute.
"""

from __future__ import annotations

from pathlib import Path

# AlphaFold-Multimer and ColabFold both read a multi-chain complex as one
# FASTA record whose chains are separated by a colon.
CHAIN_SEPARATOR = ":"


def multimer_fasta(
    target: str,
    candidates: dict[str, str],
    include_homodimers: bool = True,
) -> str:
    """Build a ColabFold / AlphaFold-Multimer FASTA for target:candidate pairs.

    Args:
        target: the target helix sequence.
        candidates: {name: sequence} of candidates to test against it.
        include_homodimers: also emit each candidate's homodimer. Keep this
            on. The homodimer is the competing state the design has to beat,
            so predicting only the heterodimer tells you nothing about
            specificity -- and specificity is the whole point.

    Returns:
        FASTA text, ready to feed to the predictor.
    """
    lines: list[str] = []
    for name, seq in candidates.items():
        lines.append(f">{name}__with__target")
        lines.append(f"{target}{CHAIN_SEPARATOR}{seq}")
        if include_homodimers:
            lines.append(f">{name}__homodimer")
            lines.append(f"{seq}{CHAIN_SEPARATOR}{seq}")
    if include_homodimers:
        lines.append(">target__homodimer")
        lines.append(f"{target}{CHAIN_SEPARATOR}{target}")
    return "\n".join(lines) + "\n"


def write_multimer_fasta(
    path: str | Path,
    target: str,
    candidates: dict[str, str],
    include_homodimers: bool = True,
) -> Path:
    p = Path(path)
    p.write_text(
        multimer_fasta(target, candidates, include_homodimers), encoding="utf-8"
    )
    return p


# What to look at once the predictions come back. These thresholds are the
# community's rough working values for AlphaFold-Multimer complexes, not
# anything derived here.
TRIAGE_NOTES = """\
Reading the predictions:

  ipTM          interface confidence. Above ~0.8 the interface is probably
                real; below ~0.5 treat it as a negative. This is the number
                that matters, not pTM.
  PAE           look at the OFF-DIAGONAL block, chain A against chain B. A
                clean low-error rectangle means the two helices are placed
                confidently relative to each other.
  orientation   check the model is PARALLEL (both N-termini at the same end)
                and in register. A confident antiparallel prediction means
                the phase A score was measuring the wrong thing.
  specificity   compare ipTM for name__with__target against name__homodimer.
                A design only passes if the heterodimer scores clearly
                higher. A design that folds beautifully as a homodimer has
                failed, however good its heterodimer looks on its own.

AlphaFold is biased towards predicting coiled coils and will happily return a
confident-looking dimer for a pair that does not form. Treat agreement
between phase A and phase C as encouraging, not as validation. The real
tests are circular dichroism for helicity and thermal melt, analytical
ultracentrifugation or SEC-MALS for oligomeric state, and a pulldown or ITC
for the actual affinity.
"""
