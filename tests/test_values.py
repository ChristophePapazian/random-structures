import pytest
import random_structures
import itertools


@pytest.mark.parametrize("anything", ["test", 1, True, 1.0, None, [], {}])
def test_constant(anything):
    specif = {"type": "constant", "value": anything}
    generator = random_structures.Structure_Generator(specif)
    for _ in range(10):
        res = generator.generate()
        assert res == anything


def test_string_choice():
    specif = {"type": "string", "method": "choice", "parameters": ["a", "b", "c"]}
    generator = random_structures.Structure_Generator(specif)
    for _ in range(200):
        res = generator.generate()
        assert isinstance(res, str)
        assert len(res) == 1
        assert res in specif["parameters"]


@pytest.mark.parametrize("min_length", [0, 1, 2, 3, 4, 5])
@pytest.mark.parametrize("max_length", [5, 6, 7, 8, 9, 10])
@pytest.mark.parametrize("fixed_alphabet", ["abc", "ABC", "123", "abcABC123", "a,b,c"])
def test_string(min_length, max_length, fixed_alphabet):
    specif = {
        "type": "string",
        "parameters": {
            "min_length": min_length,
            "max_length": max_length,
            "fixed_alphabet": fixed_alphabet,
        },
    }
    generator = random_structures.Structure_Generator(specif)
    for _ in range(200):
        res = generator.generate()
        assert isinstance(res, str)
        assert min_length <= len(res) <= max_length
        assert all(c in fixed_alphabet for c in res)


@pytest.mark.parametrize(
    "regex, expected",
    [
        ("ab|cd", ["ab", "cd"]),
        ("a*", lambda s: all(c == "a" for c in s)),
        (
            "(st|uv)+",
            lambda s: len(s) % 2 == 0
            and all(c in [("s", "t"), ("u", "v")] for c in itertools.batched(s, 2)),
        ),
    ],
)
def test_string_regex(regex, expected):
    specif = {"type": "string", "method": "regex", "parameters": {"regex": regex}}
    generator = random_structures.Structure_Generator(specif)
    all_res = set()
    for _ in range(200):
        res = generator.generate()
        assert isinstance(res, str)
        all_res.add(res)
    match expected:
        case list():
            assert sorted(all_res) == expected
        case _:
            assert all(expected(res) for res in all_res), [
                c for c in all_res if not expected(c)
            ]
