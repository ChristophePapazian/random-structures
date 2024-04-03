import importlib.util

import pytest
import random_structures

NUMPY_INSTALLED = importlib.util.find_spec("numpy") is not None


@pytest.mark.parametrize(
    "specif, expect, never",
    [
        ({"type": "integer"}, 5, 10),
        ({"type": "number"}, 5, -1),
        (
            {
                "type": "integer",
                "method": "choice",
                "parameters": [0, 1, 2, 3],
            },
            0,
            4,
        ),
        (
            {
                "type": "integer",
                "method": "numpy",
                "parameters": ["binomial", 10, 0.5],
            },
            5,
            -1,
        ),
    ],
)
def test_integer(specif, expect, never):
    if specif.get("method") == "numpy" and not NUMPY_INSTALLED:
        pytest.skip("numpy not installed")
    generator = random_structures.Structure_Generator(specif)
    for _ in range(200):
        res = generator.generate()
        assert isinstance(res, int)
        assert res != never
        if res == expect:
            return
    assert False, "expected value never found in 200 tests"
