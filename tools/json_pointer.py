#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""json_pointer.py: resolve an RFC 6901 JSON Pointer in a parsed document, strictly.

The ledger validator uses it to prove that every `applied_to` pointer names something that exists
in the packet. Strict means an array index is "0" or digits without a leading zero: Python's int()
would also accept "-1", "+1" and " 1", and a list indexed with -1 silently yields its last row, so a
pointer to a row that does not exist would resolve.

This module is a library. It has no CLI.
"""

from __future__ import annotations

import re
from typing import Any


class PointerError(ValueError):
    """A pointer that is malformed or names nothing in the document, with the reason."""


#: RFC 6901 array index: "0", or digits without a leading zero.
ARRAY_INDEX = re.compile(r"0|[1-9][0-9]*")


def segments(pointer: str) -> list[str]:
    """The unescaped reference tokens of `pointer`; the empty pointer names the whole document."""
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise PointerError(f"JSON pointer must start with '/': {pointer!r}")
    return [segment.replace("~1", "/").replace("~0", "~") for segment in pointer.split("/")[1:]]


def list_index(segment: str, pointer: str) -> int:
    if not ARRAY_INDEX.fullmatch(segment):
        raise PointerError(
            f"{pointer}: {segment!r} is not a list index (RFC 6901: 0, or digits without a leading zero)"
        )
    return int(segment)


def descend(node: Any, tokens: list[str], pointer: str) -> Any:
    """The node `tokens` lead to from `node`; `pointer` is named in any error."""
    for token in tokens:
        if isinstance(node, list):
            index = list_index(token, pointer)
            if index >= len(node):
                raise PointerError(f"{pointer}: list index {token!r} does not resolve")
            node = node[index]
        elif isinstance(node, dict):
            if token not in node:
                raise PointerError(f"{pointer}: key {token!r} does not exist")
            node = node[token]
        else:
            raise PointerError(f"{pointer}: cannot descend into a {type(node).__name__} at {token!r}")
    return node


def resolve(document: Any, pointer: str) -> Any:
    """The value `pointer` names in `document`; PointerError when it does not resolve."""
    return descend(document, segments(pointer), pointer)
