"""msa.engine.scenarios: Sobol replicate scrambling (spec 13.3)."""

import numpy as np

from msa.engine.scenarios import sobol_replicates

DIMENSIONS = 2
POINTS = 8
REPLICATES = 8


# -- sobol_replicates() -----------------------------------------------------------------


def test_sobol_replicates_deterministic_for_same_seed():
    a = sobol_replicates(DIMENSIONS, seed=1, points=POINTS, replicates=REPLICATES)
    b = sobol_replicates(DIMENSIONS, seed=1, points=POINTS, replicates=REPLICATES)
    assert all(np.array_equal(x, y) for x, y in zip(a, b, strict=True))


def test_sobol_replicates_share_nothing_across_seeds():
    a = sobol_replicates(DIMENSIONS, seed=1, points=POINTS, replicates=REPLICATES)
    b = sobol_replicates(DIMENSIONS, seed=2, points=POINTS, replicates=REPLICATES)
    assert not any(np.array_equal(x, y) for x in a for y in b)
