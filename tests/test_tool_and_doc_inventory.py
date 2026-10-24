# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""Two ratchets on the inventory.

1. Every file under tools/ is reached by a test, the CI workflow or the local runner, so a
   tool cannot arrive with nothing pointing at it. Prose (comments, docstrings) is stripped
   before searching so that mentioning a tool does not count as exercising it.
2. README.md names every shipped tool, schema and catalog, and names nothing that does not
   exist, so the inventory cannot drift from the tree.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS = REPO_ROOT / "tools"
README = REPO_ROOT / "README.md"

EXEMPT: dict[str, str] = {}


def _strip_python_prose(source: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add((body[0].lineno, body[0].col_offset))
    kept = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and tok.start in docstrings:
            continue
        kept.append(tok.string)
    return " ".join(kept)


def _reference_corpus() -> str:
    parts = []
    for path in sorted((REPO_ROOT / "tests").rglob("*.py")):
        parts.append(_strip_python_prose(path.read_text(encoding="utf-8")))
    for path in sorted(TOOLS.glob("*.py")):
        parts.append(_strip_python_prose(path.read_text(encoding="utf-8")))
    for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")) + sorted(TOOLS.glob("*.sh")):
        parts.append(
            "\n".join(
                line
                for line in path.read_text(encoding="utf-8").splitlines()
                if not line.lstrip().startswith("#")
            )
        )
    return "\n".join(parts)


def test_every_tool_is_reached_by_something_that_would_fail() -> None:
    corpus = _reference_corpus()
    tools = sorted(p for p in TOOLS.iterdir() if p.suffix in (".py", ".sh") and p.is_file())
    assert tools
    # Whole names only: `validate_pir` must not count as reached because `validate_pir_ledger` is.
    # `\b` treats `_` as part of a word, so a longer name never contains a match.
    orphans = [
        t.name for t in tools if t.name not in EXEMPT and not re.search(rf"\b{re.escape(t.stem)}\b", corpus)
    ]
    assert not orphans, f"tools with nothing pointing at them: {orphans}"


def test_readme_inventory_matches_the_tree() -> None:
    readme = README.read_text(encoding="utf-8")
    shipped = (
        [f"tools/{p.name}" for p in TOOLS.iterdir() if p.suffix in (".py", ".sh")]
        + [f"schemas/{p.name}" for p in (REPO_ROOT / "schemas").glob("*.json")]
        + [f"catalogs/{p.name}" for p in (REPO_ROOT / "catalogs").glob("*.yaml")]
    )
    missing = sorted(item for item in shipped if f"`{item}`" not in readme)
    assert not missing, f"README.md does not name: {missing}"
    named = set(re.findall(r"`((?:tools|schemas|catalogs)/[A-Za-z0-9_.-]+)`", readme))
    dangling = sorted(item for item in named if not (REPO_ROOT / item).exists())
    assert not dangling, f"README.md names files that do not exist: {dangling}"
