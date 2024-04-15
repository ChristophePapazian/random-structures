import collections
import enum
import json
import random
import string
from logging import getLogger
from typing import Any
import re._parser

import pydantic

logger = getLogger(__name__)

specification = dict[str, Any]


_ALPHABETS = {
    name: getattr(string, name)
    for name in [
        "ascii_letters",
        "ascii_lowercase",
        "ascii_uppercase",
        "digits",
        "hexdigits",
        "octdigits",
        "printable",
        "punctuation",
        "whitespace",
    ]
}
_ALPHABETS["ascii_letters_"] = _ALPHABETS["ascii_letters"] + "_"


_CATEGORIES = {
    cat: [chr(i) for i in range(128) if re.fullmatch("\\" + c, chr(i))]
    for c in "dDsSwW"
    for _, [(_, cat)] in re._parser.parse("\\" + c)
}

_CATEGORIES["."] = [chr(i) for i in range(128) if re.fullmatch(".", chr(i))]


def word_from_regex(regex: str, min_length=0) -> str:
    from re._parser import parse
    import re._constants as C

    groups = {}

    def word_from_ast(ast) -> str:
        stack = list(ast[::-1])
        set_start_bounday = False

        def rev_append(lst):
            for e in reversed(lst):
                stack.append(e)

        res = []
        while stack:
            match stack.pop():
                case (C.LITERAL, code):
                    res.append(chr(code))
                case (C.ANY, _):
                    res.append(random.choice(_CATEGORIES["."]))
                case (C.BRANCH, (_, alternatives)):
                    rev_append(random.choice(alternatives))
                case (
                    (C.MAX_REPEAT, (min_, max_, subpattern))
                    | (C.MIN_REPEAT, (min_, max_, subpattern))
                ):
                    if max_ <= 0 or (min_ <= 0 and random.random() < 0.5):
                        continue
                    stack.append((C.MAX_REPEAT, (min_ - 1, max_ - 1, subpattern)))
                    rev_append(subpattern)
                case (C.SUBPATTERN, (group, _, _, subpattern)):
                    if group is None:
                        rev_append(subpattern)
                    else:
                        word = word_from_ast(subpattern)
                        groups[group] = word
                        res.append(word)
                case (C.GROUPREF, group):
                    if group in groups:
                        res.append(groups[group])
                case (C.IN, patterns):
                    if patterns[0] == (C.NEGATE, None):

                        def not_in(i, p):
                            match p:
                                case (C.LITERAL, code):
                                    return i != code
                                case (C.RANGE, (start, end)):
                                    return i < start or i > end
                                case (C.CATEGORY, cat):
                                    return chr(i) not in _CATEGORIES[cat]
                                case unknown:
                                    raise ValueError(f"unknown element {unknown}")

                        choices = [
                            chr(i)
                            for i in range(128)
                            if all(not_in(i, p) for p in patterns[1:])
                        ]
                        if choices:
                            res.append(random.choice(choices))
                    else:
                        p = random.choice(patterns)
                        match p:
                            case (C.LITERAL, code):
                                res.append(chr(code))
                            case (C.RANGE, (start, end)):
                                res.append(chr(random.randint(start, end)))
                            case (C.CATEGORY, cat):
                                if cat in _CATEGORIES:
                                    res.append(random.choice(_CATEGORIES[cat]))
                            case unknown:
                                raise ValueError(f"unknown element {unknown}")
                case (C.NOT_LITERAL, code):
                    while (i := random.randint(0, 127)) == code:
                        pass
                    res.append(chr(i))
                case (C.AT, position):
                    match position:
                        case C.AT_BOUNDARY:
                            if res:
                                if res[-1][-1] in _CATEGORIES[C.CATEGORY_WORD]:
                                    if stack:
                                        res.append(
                                            random.choice(
                                                _CATEGORIES[C.CATEGORY_NOT_WORD]
                                            )
                                        )
                                else:
                                    res.append(
                                        random.choice(_CATEGORIES[C.CATEGORY_WORD])
                                    )
                            else:
                                set_start_bounday = True
                        case C.AT_BEGINNING:
                            res.clear()
                        case C.AT_END:
                            if stack:
                                print("CLEARING")
                            stack.clear()
                        case _:
                            pass
                            # raise ValueError(f"unknown position {position}")

                    # ignore those indications for now
                    pass
                case unknown:
                    pass
                    # raise ValueError(f"unknown element {unknown}")
        word = "".join(res)
        if set_start_bounday:
            if not word or word[0] not in _CATEGORIES[C.CATEGORY_WORD]:
                word = random.choice(_CATEGORIES[C.CATEGORY_WORD]) + word
        return word

    try:
        for _ in range(200):
            result = word_from_ast(parse(regex))
            if len(result) >= min_length and re.search(regex, result):
                return result
    except Exception as e:
        logger.error(f"problem with regex {regex}", exc_info=e)
        return ""
    return result


class State(enum.Enum):
    """state of a specification node on the generating stack"""

    DELAYED = 0
    TO_BUILD = 1
    DONE = 2
    TRUNCATED = 3


class Scope:
    def __init__(self):
        self.enums = collections.Counter()

    def get_value(self, pattern):
        res = self.enums[pattern]
        self.enums[pattern] += 1
        return res


class Value(pydantic.BaseModel):
    """value on the generating stack"""

    specification: dict = pydantic.Field(default_factory=dict)
    state: State = State.DELAYED
    value: Any = None
    sons: list["Value"] | None = None
    depth: int
    scope: Any = None


def done(value, parent: Value):
    """crate a Value already computed"""
    return Value(
        value=value,
        state=State.DONE,
        depth=parent.depth + 1,
    )


def new_value(specification: specification, parent: Value, scope=None):
    """create a Value not yet computed"""
    return Value(
        specification=specification,
        depth=parent.depth + 1,
        scope=scope,
    )


class Structure_Generator:
    """main generator"""

    def __init__(
        self,
        specif: specification,
        faker=None,
        max_depth: int = 20,
        max_size=None,
    ):
        self.max_depth = max_depth
        self.max_size = max_size
        self.specif = specif
        self.parse_specif(specif)
        self.CALLBACKS = collections.defaultdict(
            lambda: Structure_Generator._null_callback
        )
        self._type_alias = {"number": "integer"}
        register_base_functions(self.CALLBACKS)
        if faker is not None:
            try:
                from faker import Faker

                self.faker = Faker(faker)
                self._set_faker_callbacks()
            except ModuleNotFoundError:
                logger.warning("You need to install faker to use those features")

    def _null_callback(self, value):
        value.state = State.DONE
        value.value = None

    def _set_faker_callbacks(self):
        @register_simple_function
        def faker_callback(name, *parameters):
            function = getattr(self.faker, name, None)
            if function:
                try:
                    return function(*parameters)
                except BaseException as e:
                    logger.error("problem in faker callback", exc_info=e)
            else:
                logger.warning(f"{name} not found in faker")

        self.register_method("string", "fake", faker_callback)

    def register_method(self, type_name, method_name, function):
        self.CALLBACKS[(type_name, method_name)] = function

    @classmethod
    def from_json_file(cls, filename: str, faker=None):
        with open(filename, "r") as file_in:
            specif = json.load(file_in)
            return cls(specif, faker=faker)

    GLOBALS = {}

    def parse_specif(self, specif):
        if specif is None:
            return
        if specif.get("store_ref"):
            self.GLOBALS[specif["store_ref"]] = specif
        match specif.get("type"):
            case "array":
                self.parse_specif(specif.get("type_elements"))
            case "record":
                for key in specif.get("keys", []):
                    self.parse_specif(key.get("value"))
            case "choice":
                for option in specif.get("options", []):
                    self.parse_specif(option.get("value"))
            case _:
                pass

    def generate(self):
        main_value = Value(specification=self.specif, depth=0)
        stack = [main_value]
        overall_size = 1
        while stack:
            val = stack.pop()
            while (load := val.specification.get("load_ref")) is not None:
                if load not in self.GLOBALS:
                    logger.error(
                        f"unknown reference {load} {list(self.GLOBALS.keys())}"
                    )
                val.specification = self.GLOBALS.get(load, {})
            if val.depth >= val.specification.get("max_depth", self.max_depth):
                val.state = State.TRUNCATED
                val.value = None
                continue
            type_val = val.specification.get("type")
            method_val = val.specification.get("method")
            type_val = self._type_alias.get(type_val, type_val)
            key = type_val, method_val
            self.CALLBACKS[key](self, val)
            match val.state:
                case State.DONE:
                    continue
                case State.TO_BUILD:
                    stack.append(val)
                    if (
                        self.max_size is not None
                        and overall_size + len(val.sons) >= self.max_size
                    ):
                        stack.extend(val.sons[: self.max_size - overall_size])
                        overall_size = self.max_size
                    else:
                        stack.extend(val.sons)
                        overall_size += len(val.sons)
                case State.DELAYED:
                    stack.append(val)
        return main_value.value

    def generate_json(self, **args):
        return json.dumps(self.generate(), **args)


def register_simple_function(fun):
    fun = pydantic.validate_call(fun)

    def callback(sg: Structure_Generator, value: Value):
        arguments = value.specification.get("parameters")
        if isinstance(arguments, dict):
            res = fun(**arguments)
        elif arguments is None:
            res = fun()
        elif isinstance(arguments, list):
            res = fun(*arguments)
        else:
            res = fun(arguments)
        value.state = State.DONE
        value.value = res

    callback._inner_arguments = fun.__annotations__
    return callback


@register_simple_function
def generate_integer_uniform(min_val: int = 0, max_val: int = 9):
    return random.randint(min_val, max_val)


@register_simple_function
def generate_integer_choice(*choices):
    if not choices:
        return None
    return random.choice(choices)


@register_simple_function
def generate_string_choice(*choices):
    if not choices:
        return None
    return random.choice(choices)


@register_simple_function
def generate_number_numpy(distribution: str, *choices):
    try:
        import numpy.random

        f = getattr(numpy.random, distribution)
        if f:
            return f(*choices)
        else:
            logger.error(f"unknown numpy distribution: {distribution}")
    except BaseException as e:
        logger.error(exc_info=e)

    return random.choice(choices)


@register_simple_function
def generate_boolean(probability: float = 50.0) -> bool:
    return random.random() * 100.0 < probability


@register_simple_function
def generate_string(
    min_length: int = 1,
    max_length: int = 16,
    alphabet="ascii_letters_",
    fixed_alphabet=None,
    encoding=None,
) -> str:
    if isinstance(fixed_alphabet, str):
        alphabet = fixed_alphabet
    else:
        alphabet = _ALPHABETS.get(alphabet, _ALPHABETS["ascii_letters_"])
    res = "".join(random.choices(alphabet, k=random.randint(min_length, max_length)))
    match encoding:
        case "urlencoded":
            import urllib.parse

            res = urllib.parse.quote_plus(res)
        case "base64":
            import base64

            res = base64.b64encode(res.encode()).decode()
    return res


def asciify(s: str):
    import re
    import unicodedata

    return re.sub(
        r"\s", " ", unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()
    )


@register_simple_function
def generate_string_from_regex(regex: str, min_length: int = 0):
    try:
        return word_from_regex(regex, min_length)
    except Exception as e:
        logger.error(exc_info=e)
        return None


def generate_string_enum(sg: Structure_Generator, value: Value):
    pattern = value.specification.get("pattern", "%d")
    enum_id = value.scope.get_value(pattern) if value.scope else 0
    value.value = pattern % enum_id
    value.state = State.DONE


def generate_record(sg: Structure_Generator, value: Value):
    scope = Scope()
    match value.state:
        case State.DELAYED:
            keys_there = set()
            value.value = []
            to_be_done = []
            for key in value.specification.get("keys", ()):
                repeats = key.get("repeat", 1)
                for _ in range(repeats):
                    match key.get("chance", 100):
                        case None:
                            presence = True
                        case int() | float() as p:
                            presence = random.random() * 100 < p
                        case str() as key_name:
                            presence = (
                                key_name[1:] not in keys_there
                                if key_name.startswith("!")
                                else key_name in keys_there
                            )
                    if presence:
                        if not isinstance(key.get("name"), dict):
                            name = done(key["name"], value)
                        else:
                            name = new_value(key.get("name", {}), value, scope=scope)
                            to_be_done.append(name)
                        n_value = new_value(key.get("value", {}), value, scope=scope)
                        to_be_done.append(n_value)
                        value.value.append((name, n_value))
            if to_be_done:
                value.state = State.TO_BUILD
                value.sons = to_be_done
            else:
                value.value = {}
                value.state = State.DONE
        case State.TO_BUILD:
            value.value = {
                k.value: v.value
                for k, v in value.value
                if k.state == v.state == State.DONE
            }
            value.state = State.DONE


def generate_array(sg: Structure_Generator, value: Value):
    scope = Scope()
    match value.state:
        case State.DELAYED:
            min_length = value.specification.get("min_length", 0)
            max_length = value.specification.get("max_length", min_length + 4)
            length = random.randint(min_length, max_length)
            type_elements = value.specification.get("type_elements", {})
            value.value = [
                new_value(type_elements, value, scope=scope) for _ in range(length)
            ]
            value.sons = value.value
            value.state = State.TO_BUILD
        case State.TO_BUILD:
            value.value = [v.value for v in value.value]
            value.state = State.DONE


def generate_choice(sg: Structure_Generator, value: Value):
    r = random.random() * 100.0
    options = value.specification.get("options", [])
    for option in options:
        chance = option.get("chance", 100.0 / len(options))
        if r < chance:
            value.specification = option.get("value")
            return
        else:
            r -= chance
    value.value = None
    value.state = State.DONE


def generate_fixed(sg: Structure_Generator, value: Value):
    value.value = value.specification.get("value", None)
    value.state = State.DONE


def register_base_functions(callbacks):
    callbacks[("integer", "uniform")] = generate_integer_uniform
    callbacks[("integer", None)] = generate_integer_uniform
    callbacks[("integer", "choice")] = generate_integer_choice
    callbacks[("integer", "numpy")] = generate_number_numpy
    callbacks[("bool", None)] = generate_boolean
    callbacks[("fixed", None)] = generate_fixed
    callbacks[("choice", None)] = generate_choice
    callbacks[("string", None)] = generate_string
    callbacks[("string", "enum")] = generate_string_enum
    callbacks[("string", "choice")] = generate_string_choice
    callbacks[("string", "regex")] = generate_string_from_regex
    callbacks[("record", None)] = generate_record
    callbacks[("array", None)] = generate_array
    callbacks[("constant", None)] = generate_fixed
