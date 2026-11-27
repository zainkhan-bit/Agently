"""Split extracted text into overlapping chunks for retrieval. Chunks never cross pages."""

from dataclasses import dataclass, field

CHUNK_CHARACTERS = 1_200
OVERLAP_CHARACTERS = 200
# Where a chunk prefers to end, best first; searched in its last half.
BREAKS = ("\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ")


@dataclass(frozen=True)
class Chunk:
    sequence: int
    page: int | None
    content: str = field(repr=False)


def chunk(pages: list[tuple[int | None, str]]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page, text in pages:
        for piece in _split(text):
            chunks.append(Chunk(len(chunks), page, piece))
    return chunks


def _split(text: str) -> list[str]:
    text = text.strip()
    pieces = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_CHARACTERS, len(text))
        if end < len(text):
            end = _break_before(text, start, end)
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        next_start = max(end - OVERLAP_CHARACTERS, start + 1)
        # Start the overlap at a word, not inside one.
        space = text.find(" ", next_start, end)
        start = space + 1 if space != -1 else next_start
    return pieces


def _break_before(text: str, start: int, end: int) -> int:
    floor = start + CHUNK_CHARACTERS // 2
    for mark in BREAKS:
        found = text.rfind(mark, floor, end)
        if found != -1:
            return found + len(mark)
    return end
