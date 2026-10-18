"""Fit and persist a Tm model; no GUI or command-line dependencies."""
import math

from .scoring import score_pair


def fit_tm(rows):
    import numpy as np

    if len(rows) < 5:
        raise ValueError("calibration needs at least 5 measurements; aim for 20+")
    components, values = [], []
    for row in rows:
        tm = float(row["tm"])
        if not math.isfinite(tm):
            raise ValueError("Tm values must be finite")
        s = score_pair(row["sequence1"], row["sequence2"],
                       {"core": 1., "electrostatic": 1., "helix": 1.})
        components.append([s.core, s.electrostatic, s.helix, 1.])
        values.append(tm)
    matrix, observed = np.asarray(components), np.asarray(values)
    coef, _, rank, _ = np.linalg.lstsq(matrix, observed, rcond=None)
    if rank < 4:
        raise ValueError("calibration matrix is rank deficient; more diverse pairs are required")
    if coef[0] >= -1e-8:
        raise ValueError("core coefficient must be negative to preserve negative-is-better scoring")
    predicted = matrix @ coef
    residual = float(((observed - predicted)**2).sum())
    variance = float(((observed - observed.mean())**2).sum())
    return {
        "weights": {"core": 1., "electrostatic": float(coef[1] / coef[0]),
                    "helix": float(coef[2] / coef[0])},
        "tm_slope": float(coef[0]), "tm_intercept": float(coef[3]),
        "metrics": {"n": len(rows), "r2": 1-residual/variance if variance else None,
                    "rmse": math.sqrt(residual/len(rows)), "evaluation": "training_only"},
        "warnings": ["Training fit only; no independent validation or experimental confirmation."],
    }


def tm_from_score(score, model):
    return model["tm_intercept"] + model["tm_slope"] * score.total
