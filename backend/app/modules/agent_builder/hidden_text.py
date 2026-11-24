"""Finds text a reviewer could not see.

A draft is only safe because a person reads it. Invisible characters could hide instructions from
that person while a model still reads them.
"""

import unicodedata

_JOINERS = frozenset("\u200c\u200d")  # Urdu, Persian and Indic spelling; emoji families
_EMOJI_STYLE = frozenset("\ufe0e\ufe0f")
# Format characters that are visible marks in front of Arabic numbers.
_VISIBLE_FORMAT = frozenset("\u0600\u0601\u0602\u0603\u0604\u0605\u06dd\u0890\u0891\u08e2")
_HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cn", "Co", "Cs", "Zl", "Zp"})


# Fillers, blanks and silent marks.
_LISTED = frozenset(
    {0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x200A, 0x205F, 0x2800, 0x2D7F, 0x3164, 0xFFA0}
    | {0x1107F, 0x16FE4, 0x1D159}
)


def has_hidden_text(text: str) -> bool:
    for index, char in enumerate(text):
        before, after = text[index - 1 : index], text[index + 1 : index + 2]
        if char in _JOINERS:
            # Anywhere else they could encode a message between visible characters.
            # Inside Arabic or Indic words that stays possible: it is how they are spelled.
            in_word = _uses_joiners(before) and _uses_joiners(after)
            in_emoji = char == "\u200d" and _ends_emoji(before) and _is_symbol(after)
            if not in_word and not in_emoji:
                return True
        elif char in _EMOJI_STYLE:
            keycap = before and before in "0123456789#*" and after == "\u20e3"
            if not keycap and not _is_symbol(before):
                return True
        elif char not in "\n\r\t" and char not in _VISIBLE_FORMAT:
            if unicodedata.category(char) in _HIDDEN_CATEGORIES or _is_listed_as_hidden(char):
                return True
    return False


def _uses_joiners(char: str) -> bool:
    """A letter or mark from Arabic to Sinhala."""
    return "\u0600" <= char <= "\u0dff" and unicodedata.category(char)[0] in "LM"


def _is_symbol(char: str) -> bool:
    return bool(char) and unicodedata.category(char) in {"So", "Sk", "Sm"} and char > "\u007f"


def _ends_emoji(char: str) -> bool:
    return _is_symbol(char) or char == "\ufe0f"


def _is_listed_as_hidden(char: str) -> bool:
    """Invisible characters that Unicode classes as a letter, mark or symbol."""
    point = ord(char)
    return (
        point in _LISTED
        or 0x2000 <= point <= 0x2008  # spaces of unusual widths
        or 0x180B <= point <= 0x180F
        or 0xFE00 <= point <= 0xFE0F
        or 0xE0000 <= point <= 0xE0FFF
    )
