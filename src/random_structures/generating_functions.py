import collections
import enum
import json
import random
import string
from logging import getLogger
from typing import Any

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
                logger.warning(
                    "You need to install faker to use those features"
                )

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
                for key in specif["keys"]:
                    self.parse_specif(key.get("type"))
            case "choice":
                for option in specif["options"]:
                    self.parse_specif(option.get("type"))
            case _:
                pass

    def generate(self):
        main_value = Value(specification=self.specif, depth=0)
        stack = [main_value]
        overall_size = 1
        while stack:
            val = stack.pop()
            while (load := val.specification.get("load_ref")) is not None:
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
    fun = pydantic.validate_arguments(fun)

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

    return callback


@register_simple_function
def generate_integer_uniform(min_val: int = 0, max_val: int = 9):
    return random.randint(min_val, max_val)


@register_simple_function
def generate_integer_choice(*choices):
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
    alphabet="letters_",
    fixed_alphabet=None,
) -> str:
    if isinstance(fixed_alphabet, str):
        alphabet = fixed_alphabet
    else:
        alphabet = _ALPHABETS.get(alphabet, _ALPHABETS["ascii_letters_"])
    return "".join(
        random.choices(alphabet, k=random.randint(min_length, max_length))
    )


@register_simple_function
def generate_fixed(value):
    return value


def generate_string_enum(sg: Structure_Generator, value: Value):
    pattern = value.specification.get("pattern", "%d")
    enum_id = value.scope.get_value(pattern) if value.scope else 1
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
                        if isinstance(key.get("name"), str):
                            name = done(key["name"], value)
                        else:
                            name = new_value(
                                key.get("name", {}), value, scope=scope
                            )
                            to_be_done.append(name)
                        n_value = new_value(
                            key.get("type", {}), value, scope=scope
                        )
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
    match value.state:
        case State.DELAYED:
            min_length = value.specification.get("min_length", 0)
            max_length = value.specification.get("max_length", min_length + 4)
            length = random.randint(min_length, max_length)
            type_elements = value.specification.get("type_elements", {})
            value.value = [
                new_value(type_elements, value) for _ in range(length)
            ]
            value.sons = value.value
            value.state = State.TO_BUILD
        case State.TO_BUILD:
            value.value = [v.value for v in value.value]
            value.state = State.DONE


def generate_choice(sg: Structure_Generator, value: Value):
    r = random.random() * 100.0
    for option in value.specification["options"]:
        if r < option["chance"]:
            value.specification = option.get("type")
            return
        else:
            r -= option["chance"]
    value.value = None
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
    callbacks[("record", None)] = generate_record
    callbacks[("array", None)] = generate_array
