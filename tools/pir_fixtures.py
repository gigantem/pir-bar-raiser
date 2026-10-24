#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""pir_fixtures.py: materialise mutation fixtures.

A mutation fixture is a small YAML document:

    description: what this fixture proves
    kind: packet                      # or ledger, or review; which validator judges it (default packet)
    as_path: reviews/<stem>/x.json    # review fixtures only: the path the artifact is judged as filed at
    base: examples/good/order-capture-pool-exhaustion.yaml
    expect: [PIR-AI-VAGUE]            # rule ids that must fire as errors
    expect_warnings: [PIR-WHY-SHALLOW] # rule ids that must fire as warnings (optional)
    expect_clean: true                 # instead of expect: the result must carry no errors
    mutations:
      - {op: replace, path: /action_items/0/statement, value: "Investigate the pool."}
      - {op: remove,  path: /review/stages/1}
      - {op: add,     path: /response_analysis/channels_of_inquiry/-, value: {...}}

Paths are JSON Pointers (RFC 6901). `add` on a list path ending in `-` appends; on an index it
inserts; on a mapping key it sets. A fixture whose mutations leave the base unchanged is
rejected, because it would be asserting on the base rather than on the change it claims.

This module is a library used by tools/check_fixtures.py and the test suite. It has no CLI.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import json_pointer
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MUTATION_SUFFIX = ".mutation.yaml"
VALID_OPS = ("replace", "remove", "add")
FIXTURE_KINDS = ("packet", "ledger", "review")
DEFAULT_KIND = "packet"


class FixtureError(ValueError):
    """A fixture that cannot be materialised, with the reason."""


def apply_mutation(document: Any, mutation: dict[str, Any]) -> None:
    op = mutation.get("op")
    pointer = mutation.get("path")
    if op not in VALID_OPS:
        raise FixtureError(f"unknown op {op!r}; expected one of {VALID_OPS}")
    if not isinstance(pointer, str):
        raise FixtureError("mutation has no string 'path'")
    try:
        _apply(document, op, pointer, mutation.get("value"))
    except json_pointer.PointerError as exc:
        raise FixtureError(str(exc)) from exc


def _apply(document: Any, op: str, pointer: str, value: Any) -> None:
    tokens = json_pointer.segments(pointer)
    if not tokens:
        raise FixtureError("mutating the document root is not supported")
    parent = json_pointer.descend(document, tokens[:-1], pointer)
    last = tokens[-1]

    if isinstance(parent, list):
        if op == "add" and last == "-":
            parent.append(copy.deepcopy(value))
            return
        index = json_pointer.list_index(last, pointer)
        if op == "add":
            if not 0 <= index <= len(parent):
                raise FixtureError(f"{pointer}: insert index out of range")
            parent.insert(index, copy.deepcopy(value))
            return
        if not 0 <= index < len(parent):
            raise FixtureError(f"{pointer}: index out of range")
        if op == "remove":
            del parent[index]
        else:
            parent[index] = copy.deepcopy(value)
        return

    if isinstance(parent, dict):
        if op == "add":
            parent[last] = copy.deepcopy(value)
            return
        if last not in parent:
            raise FixtureError(f"{pointer}: key {last!r} does not exist")
        if op == "remove":
            del parent[last]
        else:
            parent[last] = copy.deepcopy(value)
        return

    raise FixtureError(f"{pointer}: parent is a {type(parent).__name__}, not a container")


def load_fixture(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise FixtureError(f"{path}: fixture is not valid YAML ({exc})") from exc
    if not isinstance(data, dict):
        raise FixtureError(f"{path}: fixture root must be a mapping")
    for key in ("description", "base", "mutations"):
        if key not in data:
            raise FixtureError(f"{path}: fixture is missing '{key}'")
    kind = data.get("kind", DEFAULT_KIND)
    if kind not in FIXTURE_KINDS:
        raise FixtureError(f"{path}: unknown fixture kind {kind!r}; expected one of {FIXTURE_KINDS}")
    expects = [x for x in data.get("expect") or [] if isinstance(x, str)]
    warnings = [x for x in data.get("expect_warnings") or [] if isinstance(x, str)]
    clean = data.get("expect_clean") is True
    if clean and (expects or warnings):
        raise FixtureError(f"{path}: expect_clean cannot be combined with expected rules")
    if "expect_exactly" in data and not isinstance(data["expect_exactly"], bool):
        raise FixtureError(f"{path}: expect_exactly must be true or false")
    if data.get("expect_exactly") is True and clean:
        raise FixtureError(f"{path}: expect_exactly needs named rules; expect_clean already means none")
    if not clean and not expects and not warnings:
        raise FixtureError(f"{path}: fixture expects nothing; name the rule it proves, or set expect_clean")
    if not isinstance(data["mutations"], list) or not data["mutations"]:
        raise FixtureError(f"{path}: fixture has no mutations")
    return data


def materialise(fixture: dict[str, Any], repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """The base document with the fixture's mutations applied. Raises if nothing changed."""
    base_path = repo_root / str(fixture["base"])
    with base_path.open(encoding="utf-8") as handle:
        base = yaml.safe_load(handle)
    if not isinstance(base, dict):
        raise FixtureError(f"{base_path}: base must be a mapping")
    document = copy.deepcopy(base)
    for mutation in fixture["mutations"]:
        if not isinstance(mutation, dict):
            raise FixtureError("each mutation must be a mapping")
        apply_mutation(document, mutation)
    if document == base:
        raise FixtureError("mutations left the base unchanged; the fixture asserts nothing about its change")
    return document


def is_mutation_fixture(path: Path) -> bool:
    return path.name.endswith(MUTATION_SUFFIX)
