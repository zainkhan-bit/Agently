"""What a file is, decided by its content. The name and the declared type must agree with it.

Errors carry fixed texts only: never the file's name or anything from inside it.
"""

import re
import unicodedata
import zipfile
import zlib
from pathlib import Path, PurePath

from app.core.errors import AppError
from app.modules.knowledge.models import DOCX, MD, PDF, TXT

EXTENSIONS = {".pdf": PDF, ".docx": DOCX, ".txt": TXT, ".md": MD, ".markdown": MD}
# Refused by name before anything else: they could run script in a browser.
UNSAFE_EXTENSIONS = {".svg", ".svgz", ".html", ".htm", ".xhtml", ".xht", ".shtml", ".mht"}
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DECLARED = {
    PDF: {"application/pdf"},
    DOCX: {DOCX_TYPE},
    TXT: {"text/plain"},
    MD: {"text/markdown", "text/x-markdown", "text/plain"},
}
# What browsers send when they do not know the type.
GENERIC = {"", "application/octet-stream"}
NAME_MAX = 255

MARKUP = (b"<!doctype", b"<html", b"<svg", b"<?xml", b"<script", b"<head", b"<body", b"<iframe")
PDF_UNSAFE = re.compile(rb"/JavaScript|/JS[\s(<\[/]|/Launch")
# Control characters except tab, line feed, form feed and carriage return.
TEXT_CONTROLS = re.compile("[\x00-\x08\x0b\x0e-\x1f\x7f-\x9f]")
ZIP_SIGNATURE = b"PK\x03\x04"
ZIP_MAX_ENTRIES = 2_000
ZIP_MAX_UNPACKED = 100_000_000
ZIP_MAX_RATIO = 100
ZIP_RATIO_FROM = 1_000_000  # small entries compress well and are harmless
CONTENT_TYPES = "[Content_Types].xml"
CONTENT_TYPES_MAX = 1_000_000
CHUNK = 1 << 20


class FileRefusedError(AppError):
    status_code = 415
    code = "file_refused"


class FileTypeUnsupportedError(FileRefusedError):
    code = "file_type_unsupported"
    message = "Only PDF, DOCX, TXT and Markdown files can be added."


class FileTypeMismatchError(FileRefusedError):
    code = "file_type_mismatch"
    message = "The file's content does not match its name or type."


class FileUnsafeError(FileRefusedError):
    code = "file_unsafe"
    message = "This file contains something that is not allowed, such as a script or macros."


class FileMalformedError(FileRefusedError):
    status_code = 422
    code = "file_malformed"
    message = "The file is damaged or not readable."


class FileEmptyError(FileRefusedError):
    status_code = 422
    code = "file_empty"
    message = "The file is empty."


class FileTooLargeError(FileRefusedError):
    status_code = 413
    code = "file_too_large"
    message = "The file is too large."


class FileNameInvalidError(FileRefusedError):
    status_code = 422
    code = "file_name_invalid"
    message = "The file name is missing, too long or contains invalid characters."


def check_name(name: str) -> tuple[str, str]:
    """The name to show, and the kind its extension names. Paths are refused, not cleaned."""
    name = unicodedata.normalize("NFC", name.strip())
    if not 1 <= len(name) <= NAME_MAX or "/" in name or "\\" in name or name in (".", ".."):
        raise FileNameInvalidError()
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in name):
        raise FileNameInvalidError()
    suffix = PurePath(name).suffix.lower()
    if suffix in UNSAFE_EXTENSIONS:
        raise FileUnsafeError()
    if suffix not in EXTENSIONS:
        raise FileTypeUnsupportedError()
    return name, EXTENSIONS[suffix]


def check_declared(kind: str, content_type: str | None) -> None:
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared in GENERIC or declared in DECLARED[kind]:
        return
    if declared in {"text/html", "application/xhtml+xml", "image/svg+xml"}:
        raise FileUnsafeError()
    raise FileTypeMismatchError()


def check_content(path: Path, kind: str) -> None:
    """Raises unless the bytes at ``path`` are a harmless file of this kind."""
    size = path.stat().st_size
    if size == 0:
        raise FileEmptyError()
    with path.open("rb") as file:
        head = file.read(1024)
    found = _sniff(head)
    if found == "markup":
        raise FileUnsafeError()
    if found != _family(kind):
        raise FileTypeMismatchError()
    if kind == PDF:
        _check_pdf(path, size)
    elif kind == DOCX:
        _check_docx(path)
    else:
        _check_text(path)


def _family(kind: str) -> str:
    return "text" if kind in (TXT, MD) else kind


def _sniff(head: bytes) -> str:
    if head.startswith(b"%PDF-"):
        return PDF
    if head.startswith(ZIP_SIGNATURE):
        return DOCX
    start = head.removeprefix(b"\xef\xbb\xbf").lstrip().lower()
    if start.startswith(MARKUP):
        return "markup"
    return "text"


def _check_pdf(path: Path, size: int) -> None:
    with path.open("rb") as file:
        file.seek(max(0, size - 1024))
        if b"%%EOF" not in file.read():
            raise FileMalformedError()
        file.seek(0)
        tail = b""
        while chunk := file.read(CHUNK):
            # Compressed objects can hide these: a heuristic, and the file is never served.
            if PDF_UNSAFE.search(tail + chunk):
                raise FileUnsafeError()
            tail = chunk[-16:]


def _check_docx(path: Path) -> None:
    """Sizes here are what the archive claims. Whoever unpacks it must count real bytes too."""
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > ZIP_MAX_ENTRIES:
                raise FileUnsafeError()
            names = {entry.filename for entry in entries}
            if CONTENT_TYPES not in names or "word/document.xml" not in names:
                raise FileTypeMismatchError()
            unpacked = 0
            for entry in entries:
                if entry.flag_bits & 0x1:  # encrypted
                    raise FileUnsafeError()
                if entry.filename.lower().endswith("vbaproject.bin"):
                    raise FileUnsafeError()
                unpacked += entry.file_size
                ratio = entry.file_size / max(entry.compress_size, 1)
                if entry.file_size > ZIP_RATIO_FROM and ratio > ZIP_MAX_RATIO:
                    raise FileUnsafeError()
            if unpacked > ZIP_MAX_UNPACKED:
                raise FileUnsafeError()
            if archive.getinfo(CONTENT_TYPES).file_size > CONTENT_TYPES_MAX:
                raise FileUnsafeError()
            if b"macroenabled" in archive.read(CONTENT_TYPES).lower():
                raise FileUnsafeError()
    except (
        zipfile.BadZipFile, zipfile.LargeZipFile, zlib.error, OSError, EOFError,
        NotImplementedError,
    ):  # fmt: skip
        raise FileMalformedError() from None


def _check_text(path: Path) -> None:
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise FileMalformedError() from None
    if not text.strip():
        raise FileEmptyError()
    if TEXT_CONTROLS.search(text):
        raise FileMalformedError()
