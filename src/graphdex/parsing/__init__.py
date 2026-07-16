"""Language dispatch for file parsing."""

from __future__ import annotations

from ..models import ParsedFile
from .python import PythonParser

SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".py": "python",
}

_PARSERS = {
    "python": PythonParser(),
}


def parse_file(path: str, source: bytes, language: str) -> ParsedFile:
    parser = _PARSERS.get(language)
    if parser is None:
        raise ValueError(f"unsupported language: {language}")
    return parser.parse(path, source)


__all__ = ["SUPPORTED_EXTENSIONS", "parse_file"]
