"""Validation of text people type, shared by every module."""

import unicodedata
from typing import Annotated

from pydantic import AfterValidator
from pydantic_core import PydanticCustomError

# Text-direction controls could make a name disguise the text shown next to it.
_BIDI_CONTROLS = frozenset(
    "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
)
_INVISIBLE = frozenset({"Cc", "Cf", "Cn", "Mn", "Me", "Zl", "Zp", "Zs"})
NAME_MAX = 100


def _check_name(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= NAME_MAX:
        raise PydanticCustomError("name_length", "Name must be 1 to 100 characters.")
    categories = {unicodedata.category(char) for char in value}
    if categories & {"Cc", "Cs", "Zl", "Zp"} or _BIDI_CONTROLS & set(value):
        raise PydanticCustomError("name_invalid", "Name contains invalid characters.")
    if categories <= _INVISIBLE:
        raise PydanticCustomError("name_invalid", "Name needs at least one visible character.")
    return value


Name = Annotated[str, AfterValidator(_check_name)]


def check_text(value: str, maximum: int) -> str:
    """Free text. PostgreSQL cannot store null characters or lone surrogates."""
    if len(value) > maximum:
        raise PydanticCustomError(
            "text_too_long", "Must be at most {maximum} characters.", {"maximum": maximum}
        )
    if any(unicodedata.category(c) in {"Cc", "Cs"} and c not in "\n\r\t" for c in value):
        raise PydanticCustomError("text_invalid", "Contains invalid characters.")
    return value


def is_blank(value: str) -> bool:
    return all(unicodedata.category(char) in _INVISIBLE for char in value)
