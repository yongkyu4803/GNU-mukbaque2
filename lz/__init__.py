"""lz -- leucine zipper partner discovery and design.

Phase A of the pipeline: sequence-level scoring, library screening and de
novo design of coiled-coil partner helices. Phase C hands the surviving
candidates to a structure predictor for validation.

Typical use:

    from lz import assign_register, score_pair, screen, design_partner

    reg = assign_register("RMKQLEDKVEELLSKNYHLENEVARLKKLVGER")
    print(reg.annotate())
    print(score_pair(reg, reg).report())
"""

from .design import Design, design_partner
from .heptad import Register, RegisterError, assign_register
from .library import Hit, Zipper, load_library, screen
from .scoring import Contact, PairScore, score_pair
from .structure import (
    HelixSegment,
    InterfaceAnalysis,
    Ligand,
    StructureError,
    analyse,
)

__version__ = "0.1.0"

__all__ = [
    "Contact",
    "Design",
    "HelixSegment",
    "Hit",
    "InterfaceAnalysis",
    "Ligand",
    "PairScore",
    "Register",
    "RegisterError",
    "StructureError",
    "Zipper",
    "analyse",
    "assign_register",
    "design_partner",
    "load_library",
    "score_pair",
    "screen",
]
