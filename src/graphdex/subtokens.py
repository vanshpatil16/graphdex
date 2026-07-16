"""Identifier subtokenization so `getUserById` matches "user by id"."""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^0-9A-Za-z]+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def subtokenize(identifier: str) -> str:
    """Split an identifier into lowercase space-separated subtokens."""
    words: list[str] = []
    for part in _NON_ALNUM.split(identifier):
        if not part:
            continue
        words.extend(w for w in _CAMEL_BOUNDARY.split(part) if w)
    return " ".join(w.lower() for w in words)
