# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""Make tools/ importable as plain modules, the same way the tools import each other."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))


@pytest.fixture(autouse=True)
def _run_from_the_repository_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tools' command lines resolve cited paths against the current directory (the root of the
    repository holding the PIR), so the suite runs from this root whatever directory pytest was
    started in. A test that needs another working directory calls monkeypatch.chdir itself."""
    monkeypatch.chdir(REPO_ROOT)
