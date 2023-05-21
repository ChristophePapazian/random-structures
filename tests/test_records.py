import pytest
import random_structures


def compute_depth(record):
    res = 0
    while record is not None:
        res += 1
        record = record.get("sub")
    return res


@pytest.mark.parametrize(
    "depth",
    [1, 5, 20, 50, 2000],
)
def test_depth(depth):
    specif = {
        "type": "record",
        "store_ref": "ref_name",
        "max_depth": depth,
        "keys": [{"name": "sub", "type": {"load_ref": "ref_name"}}],
    }
    generator = random_structures.Structure_Generator(specif)
    res = generator.generate()
    assert compute_depth(res) == depth


@pytest.mark.parametrize(
    "girth",
    [1, 5, 20, 50, 2000],
)
def test_girth_and_enum(girth):
    specif = {
        "type": "record",
        "keys": [
            {
                "name": {
                    "type": "string",
                    "method": "enum",
                    "pattern": "key_%04d",
                },
                "repeat": girth,
                "type": {"type": "null"},
            }
        ],
    }
    generator = random_structures.Structure_Generator(specif)
    res = generator.generate()
    assert all(key.startswith("key_") for key in res)
    assert len(res) == girth, res
