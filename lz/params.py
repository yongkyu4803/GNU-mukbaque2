"""Biophysical parameter tables for coiled-coil scoring.

IMPORTANT — provenance of numbers
---------------------------------
Two different kinds of constants live in this file and they must not be
confused:

1. MEASURED scales, taken from the literature as published:
     - `HELIX_PROPENSITY`  : Pace & Scholtz (1998) Biophys J 75:422.
                             Units kcal/mol, relative to Ala = 0.0.
                             Higher = worse helix former.

2. HEURISTIC scores, written by hand to encode well-established *qualitative*
   rules (Leu at d favours the parallel dimer; Ile at a with Leu at d
   specifies a dimer, Harbury et al. 1993 Science 262:1401; a buried Asn at a
   enforces dimer + parallel orientation, as in GCN4 Asn16; buried charge is
   destabilising; g/e' salt bridges tune partner choice, O'Shea et al. 1993
   Curr Biol 3:658).
   These are NOT fitted to any dataset. They are a starting point whose job
   is to rank candidates sensibly. Calibrate them with `lz calibrate` against
   your own Tm measurements before trusting any absolute number.

Sign convention throughout: NEGATIVE = stabilising.
"""

from __future__ import annotations

AA = "ACDEFGHIKLMNPQRSTVWY"

# --- residue classes -------------------------------------------------------

HYDROPHOBIC = set("AVLIMFWYC")
POLAR = set("STNQHGY")
POSITIVE = set("KR")
NEGATIVE = set("DE")
CHARGED = POSITIVE | NEGATIVE

# Side-chain volume, A^3 (Zamyatnin 1972). Used for the core packing
# complementarity term: a dimer core tolerates a fairly narrow volume range,
# and large mismatches between the two partners cost energy.
VOLUME = {
    "A": 88.6, "C": 108.5, "D": 111.1, "E": 138.4, "F": 189.9,
    "G": 60.1, "H": 153.2, "I": 166.7, "K": 168.6, "L": 166.7,
    "M": 162.9, "N": 114.1, "P": 112.7, "Q": 143.8, "R": 173.4,
    "S": 89.0, "T": 116.1, "V": 140.0, "W": 227.8, "Y": 193.6,
}

# --- MEASURED: helix propensity, Pace & Scholtz (1998) ---------------------
# kcal/mol, Ala = 0.0, larger = less helix-favourable.
HELIX_PROPENSITY = {
    "A": 0.00, "L": 0.21, "R": 0.21, "M": 0.24, "K": 0.26,
    "Q": 0.39, "E": 0.40, "I": 0.41, "W": 0.49, "S": 0.50,
    "Y": 0.53, "F": 0.54, "H": 0.61, "V": 0.61, "N": 0.65,
    "T": 0.66, "C": 0.68, "D": 0.69, "G": 1.00, "P": 3.16,
}

# --- HEURISTIC: core packing ----------------------------------------------
# Baseline burial reward per residue at a core position. Dimer cores are
# small, so very large residues are penalised back via VOLUME_PENALTY.
_BURIAL_A = {  # 'a' layer: parallel/beta-branched-tolerant
    "I": -0.75, "V": -0.60, "L": -0.50, "M": -0.45, "A": -0.25,
    "F": -0.35, "T": -0.20, "N": -0.15, "C": -0.30, "W": -0.15,
    "Y": -0.15, "S": -0.05, "Q": -0.05, "G": 0.10, "H": 0.15,
    "K": 0.55, "R": 0.55, "E": 0.60, "D": 0.70, "P": 1.50,
}
_BURIAL_D = {  # 'd' layer: Leu-optimal in a parallel two-stranded coil
    "L": -0.90, "M": -0.60, "I": -0.30, "A": -0.30, "V": -0.22,
    "F": -0.38, "C": -0.33, "N": -0.05, "Q": -0.05, "T": 0.05,
    "W": -0.10, "Y": -0.10, "S": 0.05, "G": 0.20, "H": 0.20,
    "K": 0.60, "R": 0.60, "E": 0.65, "D": 0.75, "P": 1.50,
}
BURIAL = {"a": _BURIAL_A, "d": _BURIAL_D}

# Ideal summed volume of the two side chains facing each other in one layer.
# Roughly 2 x Leu. Deviations cost energy (over-packing or cavity formation).
IDEAL_LAYER_VOLUME = 2 * VOLUME["L"]
VOLUME_PENALTY = 0.012  # kcal/mol per A^3 of |deviation|

# Pair-specific corrections, keyed (layer, frozenset({res1, res2})).
#
# These are ADDED to the summed per-residue burial terms, never substituted
# for them. An earlier version of this file substituted, which silently made
# heterotypic layers incomparable with homotypic ones -- e.g. an Ile/Leu 'd'
# layer scored better than Leu/Leu, so the designer happily replaced the
# defining leucines of a leucine zipper with isoleucine. Keep this additive.
PAIR_BONUS = {
    # Ile/Ile at d drives trimers and tetramers rather than the dimer we
    # want (Harbury et al. 1993), so it is penalised for a dimer design.
    ("d", frozenset({"I"})): 0.85,
    ("d", frozenset({"M"})): 0.30,
    ("d", frozenset({"V"})): 0.40,
    # Buried polar pair that hydrogen bonds across the interface. Note the
    # net layer energy stays UNFAVOURABLE even with this bonus -- a buried
    # Asn destabilises GCN4; what it buys is dimer and orientation
    # specificity, not stability.
    ("a", frozenset({"N"})): -0.70,
    ("a", frozenset({"Q"})): -0.50,
}

# Penalty when a buried polar residue has no polar partner across the layer
# (an unsatisfied H-bond donor/acceptor in a hydrophobic environment).
UNSATISFIED_POLAR = 0.60

# Like-charge pair buried in the core.
BURIED_LIKE_CHARGE = 1.10

# --- HEURISTIC: g <-> e' electrostatics ------------------------------------
# One interhelical pair, in kcal/mol.
SALT_BRIDGE_ATTRACT = -0.45   # K/R  <->  D/E
SALT_BRIDGE_REPEL = 0.40      # like charges
# Partial credit for a polar (Q/N/S/T/H) residue facing a charge.
POLAR_CHARGE_CONTACT = -0.10

# --- model combination weights --------------------------------------------
# These multiply the three component scores before summing. They are the
# knobs that `lz calibrate` fits. Defaults are 1.0 / 1.0 / 0.5: helix
# propensity is down-weighted because it affects both the folded and the
# unfolded reference state.
DEFAULT_WEIGHTS = {
    "core": 1.0,
    "electrostatic": 1.0,
    "helix": 0.5,
    # Negative-design penalty strengths, used by the designer only.
    "self_competition": 1.0,    # candidate homodimer competing
    "target_competition": 0.5,  # target homodimer competing
}

# How far (kcal/mol) the heterodimer must beat a competing homodimer before
# the negative-design penalty switches off.
#
# The penalty is a hinge, max(0, hetero + margin - homodimer), NOT a linear
# term. With a linear term the designer discovers it can lower the objective
# without bound by wrecking the candidate's own homodimer, and it pays for
# that by abandoning the heterodimer interface -- in testing it replaced
# every core leucine with isoleucine, which is exactly backwards for a
# two-stranded coil. The hinge makes "already beaten" worth nothing more, so
# optimisation pressure returns to the heterodimer once the margin is met.
SPECIFICITY_MARGIN = 1.0

# Empirical map from model score to an apparent Tm, used only for reporting a
# human-readable number. Intercept/slope are placeholders: run `lz calibrate`.
TM_INTERCEPT = 25.0   # degC at score 0
TM_SLOPE = -4.0       # degC per kcal/mol of score

HEPTAD_POSITIONS = "abcdefg"
CORE_POSITIONS = ("a", "d")
