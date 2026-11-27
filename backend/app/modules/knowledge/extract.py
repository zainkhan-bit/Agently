"""Text from a stored file. Runs in a child process, so that a stuck parser can be stopped.

    python -m app.modules.knowledge.extract <kind> <path>

prints one JSON object: {"pages": [[page or null, text], ...]} or {"error": "<code>"}. Nothing
else is printed, and nothing is logged: the text is private, and so is a parser's error message.
"""

import json
import logging
import os
import sys
import time
import zipfile
from pathlib import Path
from xml.parsers import expat

MAX_PAGES = 500
MEMORY_MB = 512
MAX_CHARACTERS = 2_000_000
MAX_DOCX_XML_BYTES = 20_000_000
DOCX_BODY = "word/document.xml"
WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

Pages = list[tuple[int | None, str]]


class ExtractionError(Exception):
    """``code`` is one of the fixed failure codes shown to people."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def extract(path: Path, kind: str) -> Pages:
    if kind == "pdf":
        pages = _pdf(path)
    elif kind == "docx":
        pages = [(None, _docx(path))]
    elif kind in ("txt", "md"):
        pages = [(None, _text(path))]
    else:
        raise ExtractionError("processing_failed")
    pages = [(page, text) for page, text in pages if text.strip()]
    if not pages:
        raise ExtractionError("text_empty")
    if sum(len(text) for _, text in pages) > MAX_CHARACTERS:
        raise ExtractionError("text_too_long")
    return pages


def _pdf(path: Path) -> Pages:
    from pypdf import PdfReader

    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ExtractionError("text_unreadable")
        if len(reader.pages) > MAX_PAGES:
            raise ExtractionError("pages_too_many")
        pages: Pages = []
        total = 0
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            total += len(text)
            if total > MAX_CHARACTERS:
                raise ExtractionError("text_too_long")
            pages.append((number, text))
        return pages
    except (ExtractionError, MemoryError):
        raise
    except Exception:  # noqa: BLE001 - pypdf raises many kinds on bad input
        raise ExtractionError("text_unreadable") from None


def _docx(path: Path) -> str:
    """Paragraphs of the body, read as a stream: the unpacked bytes are counted as they arrive
    (the sizes an archive declares can lie), and no tree of the whole document is built.
    """
    reader = _Paragraphs()
    received = 0
    try:
        with zipfile.ZipFile(path) as archive, archive.open(DOCX_BODY) as body:
            while chunk := body.read(1 << 20):
                received += len(chunk)
                if received > MAX_DOCX_XML_BYTES:
                    raise ExtractionError("text_too_long")
                reader.feed(chunk)
        reader.feed(b"", final=True)
    except (ExtractionError, MemoryError):
        raise
    except Exception:  # noqa: BLE001 - zipfile, zlib and expat raise many kinds on bad input
        raise ExtractionError("text_unreadable") from None
    return "\n\n".join(paragraph for paragraph in reader.paragraphs if paragraph.strip())


class _Paragraphs:
    """Expat without a DTD: no entity can be declared, so none can be expanded, in any encoding."""

    def __init__(self) -> None:
        self.paragraphs: list[str] = []
        self._parts: list[str] = []
        self._in_text = False
        self._parser = expat.ParserCreate(namespace_separator=" ")
        self._parser.StartDoctypeDeclHandler = self._refuse
        self._parser.EntityDeclHandler = self._refuse
        self._parser.StartElementHandler = self._start
        self._parser.EndElementHandler = self._end
        self._parser.CharacterDataHandler = self._text

    def feed(self, data: bytes, *, final: bool = False) -> None:
        self._parser.Parse(data, final)

    @staticmethod
    def _refuse(*_) -> None:
        raise ExtractionError("text_unreadable")

    def _start(self, name: str, _attributes) -> None:
        if name == f"{WORD} p":
            self._parts = []
        elif name == f"{WORD} t":
            self._in_text = True
        elif name == f"{WORD} tab":
            self._parts.append("\t")
        elif name in (f"{WORD} br", f"{WORD} cr"):
            self._parts.append("\n")

    def _end(self, name: str) -> None:
        if name == f"{WORD} t":
            self._in_text = False
        elif name == f"{WORD} p":
            self.paragraphs.append("".join(self._parts))

    def _text(self, data: str) -> None:
        if self._in_text:
            self._parts.append(data)


def _text(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8-sig")
    except (UnicodeDecodeError, OSError):
        raise ExtractionError("text_unreadable") from None


def limit_memory(megabytes: int) -> None:
    """Stop this process once it uses more memory than this. A crafted file must not take the
    machine's memory: on POSIX the system enforces it, on Windows a watchdog thread does.
    """
    limit = megabytes * 1024 * 1024
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        return
    import ctypes
    import threading
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [  # noqa: RUF012 - the C layout of PROCESS_MEMORY_COUNTERS
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    process = kernel32.GetCurrentProcess()
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(Counters),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

    def check() -> None:
        psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
        if counters.PagefileUsage > limit:  # private bytes
            _finish({"error": "text_too_long"})

    def watch() -> None:
        while True:
            time.sleep(0.05)
            check()

    check()
    threading.Thread(target=watch, daemon=True).start()


def _finish(result: dict) -> None:
    sys.stdout.write(json.dumps(result, ensure_ascii=True))
    sys.stdout.flush()
    os._exit(0)


def main(arguments: list[str]) -> int:
    logging.disable(logging.CRITICAL)  # a parser's warnings may quote the document
    limit_memory(int(os.environ.get("AGENTLY_EXTRACT_MEMORY_MB", MEMORY_MB)))
    try:
        kind, path = arguments
        result: dict = {"pages": extract(Path(path), kind)}
    except ExtractionError as error:
        result = {"error": error.code}
    except MemoryError:
        result = {"error": "text_too_long"}
    except Exception:  # noqa: BLE001 - its message may hold document text
        result = {"error": "processing_failed"}
    sys.stdout.write(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
