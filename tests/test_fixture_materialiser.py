# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""The mutation materialiser must apply exactly what a fixture says, and refuse the rest."""

from __future__ import annotations

from pathlib import Path

import json_pointer
import pir_fixtures
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE = "examples/good/order-capture-pool-exhaustion.yaml"


def _fixture(mutations: list[dict], **extra) -> dict:
    return {"description": "t", "base": BASE, "expect": ["PIR-SCHEMA"], "mutations": mutations, **extra}


def test_replace_remove_add_and_append() -> None:
    doc = {"a": [1, 2, 3], "b": {"c": "x"}}
    pir_fixtures.apply_mutation(doc, {"op": "replace", "path": "/a/1", "value": 9})
    pir_fixtures.apply_mutation(doc, {"op": "remove", "path": "/a/0"})
    pir_fixtures.apply_mutation(doc, {"op": "add", "path": "/a/-", "value": 4})
    pir_fixtures.apply_mutation(doc, {"op": "add", "path": "/a/0", "value": 0})
    pir_fixtures.apply_mutation(doc, {"op": "add", "path": "/b/d", "value": "y"})
    pir_fixtures.apply_mutation(doc, {"op": "remove", "path": "/b/c"})
    assert doc == {"a": [0, 9, 3, 4], "b": {"d": "y"}}


def test_escaped_pointer_segments() -> None:
    doc = {"a/b": {"c~d": 1}}
    pir_fixtures.apply_mutation(doc, {"op": "replace", "path": "/a~1b/c~0d", "value": 2})
    assert doc == {"a/b": {"c~d": 2}}


@pytest.mark.parametrize(
    "mutation",
    [
        {"op": "replace", "path": "/nope", "value": 1},
        {"op": "remove", "path": "/a/9"},
        {"op": "replace", "path": "a", "value": 1},
        {"op": "frobnicate", "path": "/a", "value": 1},
        {"op": "replace", "path": "", "value": {}},
    ],
)
def test_bad_mutations_are_refused(mutation: dict) -> None:
    with pytest.raises(pir_fixtures.FixtureError):
        pir_fixtures.apply_mutation({"a": [1]}, mutation)


def test_a_fixture_that_changes_nothing_is_refused() -> None:
    fixture = _fixture([{"op": "replace", "path": "/id", "value": "PIR-2026-0412"}])
    with pytest.raises(pir_fixtures.FixtureError, match="unchanged"):
        pir_fixtures.materialise(fixture)


def test_a_fixture_that_expects_nothing_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "f.yaml"
    path.write_text(
        f"description: t\nbase: {BASE}\nmutations:\n  - {{op: remove, path: /summary}}\n", encoding="utf-8"
    )
    with pytest.raises(pir_fixtures.FixtureError, match="expects nothing"):
        pir_fixtures.load_fixture(path)


def test_expect_clean_cannot_also_expect_rules(tmp_path: Path) -> None:
    path = tmp_path / "f.yaml"
    path.write_text(
        f"description: t\nbase: {BASE}\nexpect_clean: true\nexpect: [PIR-SCHEMA]\nmutations:\n  - {{op: remove, path: /summary}}\n",
        encoding="utf-8",
    )
    with pytest.raises(pir_fixtures.FixtureError, match="expect_clean"):
        pir_fixtures.load_fixture(path)


def test_malformed_yaml_is_a_fixture_error(tmp_path: Path) -> None:
    path = tmp_path / "f.yaml"
    path.write_text("description: a: b\n", encoding="utf-8")
    with pytest.raises(pir_fixtures.FixtureError, match="not valid YAML"):
        pir_fixtures.load_fixture(path)


def test_an_unknown_fixture_kind_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "f.yaml"
    path.write_text(
        "description: t\nkind: packetz\nbase: x.yaml\nexpect: [PIR-SCHEMA]\nmutations: [{op: remove, path: /a}]\n",
        encoding="utf-8",
    )
    with pytest.raises(pir_fixtures.FixtureError, match="unknown fixture kind"):
        pir_fixtures.load_fixture(path)


def test_resolve_pointer_names_what_exists_and_refuses_what_does_not() -> None:
    doc = {"a": [{"b": 1}], "c~d": 2}
    assert json_pointer.resolve(doc, "/a/0/b") == 1
    assert json_pointer.resolve(doc, "/c~0d") == 2
    assert json_pointer.resolve(doc, "") is doc
    for pointer in ("/a/1", "/a/0/z", "/a/x", "a/0"):
        with pytest.raises(json_pointer.PointerError):
            json_pointer.resolve(doc, pointer)
