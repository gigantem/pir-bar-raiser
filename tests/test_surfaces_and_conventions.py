# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""The artifact directories hold only what they claim.

The check is run against this repository and against trees built under tmp_path, so it is shown to
go red on the defect it exists for: a stray file under reviews/, a rendered interview that no
longer matches its YAML, an artifact its own validator rejects.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import check_artifact_conventions as conventions
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INTERVIEW = REPO_ROOT / "examples" / "interviews" / "order-capture-draft-I01.yaml"
INTERVIEW_MD = REPO_ROOT / "examples" / "interviews" / "order-capture-draft-I01.md"
LEDGER = REPO_ROOT / "examples" / "ledgers" / "good" / "order-capture-draft-L01-resolved.yaml"
REVIEW = REPO_ROOT / "examples" / "reviews" / "good" / "order-capture-go-review.json"


# ------------------------------------------------------------------------- artifact conventions


@pytest.mark.parametrize(
    ("relative", "kind"),
    [
        ("interviews/order-capture/20260905T090000Z-I01.yaml", "interview"),
        ("interviews/order-capture/20260905T090000Z-I01.md", "interview-markdown"),
        ("clarifications/order-capture/20260905T090000Z-L01.yaml", "ledger"),
        ("reviews/order-capture/20260912T090000Z-pir-reviewer.json", "review"),
        ("reviews/README.md", "root-doc"),
        ("reviews/order-capture/notes.json", "unknown"),
        ("reviews/order-capture/20260912T090000Z-pir-reviewer.md", "unknown"),
        ("interviews/order-capture/deep/20260905T090000Z-I01.yaml", "unknown"),
        ("clarifications/stray.yaml", "unknown"),
        ("pirs/order-capture.yaml", "unknown"),
    ],
)
def test_classification(relative: str, kind: str) -> None:
    assert conventions.classify(Path(relative)) == kind


def test_this_repository_has_no_artifacts_yet_and_says_so(capsys) -> None:
    assert conventions.main([]) == conventions.EMPTY
    assert "SKIP" in capsys.readouterr().err


def test_a_fresh_workspace_without_the_folders_is_a_skip_not_a_failure(tmp_path: Path, capsys) -> None:
    """A workspace has none of the folders until its first interview: that is
    nothing filed, reported as a skip, never as a pass."""
    assert conventions.main(["--repo-root", str(tmp_path)]) == conventions.EMPTY
    assert "SKIP" in capsys.readouterr().err


def test_a_folder_name_taken_by_a_file_is_a_violation(tmp_path: Path) -> None:
    (tmp_path / "reviews").write_text("not a directory\n", encoding="utf-8")
    violations, _ = conventions.problems(tmp_path)
    assert violations == ["reviews is not a directory"]


@pytest.fixture
def assessed(tmp_path: Path) -> Path:
    """A tree holding one complete assessment, filed by the convention."""
    for d in ("interviews", "clarifications", "reviews"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "README.md").write_text("# x\n", encoding="utf-8")
    for d in (
        "examples/draft",
        "examples/good",
        "examples/interviews",
        "examples/ledgers/good",
        "catalogs",
        "schemas",
    ):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    for rel in (
        "examples/draft/order-capture-draft.yaml",
        "examples/good/order-capture-pool-exhaustion.yaml",
        "examples/interviews/order-capture-draft-I01.yaml",
        "examples/ledgers/good/order-capture-draft-L01-resolved.yaml",
    ):
        shutil.copy(REPO_ROOT / rel, tmp_path / rel)
    (tmp_path / "interviews" / "order-capture").mkdir()
    shutil.copy(INTERVIEW, tmp_path / "interviews" / "order-capture" / "20260905T090000Z-I01.yaml")
    shutil.copy(INTERVIEW_MD, tmp_path / "interviews" / "order-capture" / "20260905T090000Z-I01.md")
    (tmp_path / "clarifications" / "order-capture").mkdir()
    shutil.copy(LEDGER, tmp_path / "clarifications" / "order-capture" / "20260907T090000Z-L01.yaml")
    (tmp_path / "reviews" / "order-capture").mkdir()
    shutil.copy(REVIEW, tmp_path / "reviews" / "order-capture" / "20260912T090000Z-pir-reviewer.json")
    return tmp_path


def test_a_conforming_tree_passes(assessed: Path) -> None:
    violations, count = conventions.problems(assessed)
    assert violations == [], violations
    assert count == 4


def test_a_stray_file_is_named(assessed: Path) -> None:
    (assessed / "reviews" / "order-capture" / "notes.md").write_text("x\n", encoding="utf-8")
    violations, _ = conventions.problems(assessed)
    assert any("notes.md" in v and "does not match" in v for v in violations)


def test_a_stale_rendering_is_named(assessed: Path) -> None:
    md = assessed / "interviews" / "order-capture" / "20260905T090000Z-I01.md"
    md.write_text(md.read_text(encoding="utf-8") + "\nedited by hand\n", encoding="utf-8")
    violations, _ = conventions.problems(assessed)
    assert any("not the rendering" in v for v in violations)


def test_an_invalid_artifact_is_routed_to_its_own_validator(assessed: Path) -> None:
    review = assessed / "reviews" / "order-capture" / "20260912T090000Z-pir-reviewer.json"
    review.write_text(
        review.read_text(encoding="utf-8").replace('"blocker_count": 0', '"blocker_count": 5'),
        encoding="utf-8",
    )
    violations, _ = conventions.problems(assessed)
    assert any("REVIEW-COUNTS" in v for v in violations)


def test_the_conventions_cli_passes_a_conforming_tree(assessed: Path, capsys) -> None:
    assert conventions.main(["--repo-root", str(assessed)]) == 0
    assert "4 artifact(s)" in capsys.readouterr().out
