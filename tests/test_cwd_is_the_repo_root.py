# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""On the command line, cited paths resolve against the current directory, not the tools' home.

The tools' home and the repository holding the PIR coincide here and differ once the tools run
from a package (the VS Code extension bundles them inside a skill folder). So every tool that
records or resolves `pirs/`, `interviews/`, `clarifications/` or `reviews/` paths takes
`--repo-root`, defaulting to the current directory, and the suite proves both halves against a
workspace built under tmp_path: run from the workspace, the artifacts record and resolve
workspace-relative paths; run from elsewhere, the same commands do not.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import check_artifact_conventions as conventions
import generate_pir_interview
import open_pir_ledger
import pytest
import render_pir_interview
import render_pir_review_scaffold as scaffold
import validate_pir
import validate_pir_ledger
import validate_pir_review
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
FINISHED = REPO_ROOT / "examples" / "good" / "order-capture-pool-exhaustion.yaml"
DRAFT = REPO_ROOT / "examples" / "draft" / "order-capture-draft.yaml"
GO_REVIEW = REPO_ROOT / "examples" / "reviews" / "good" / "order-capture-go-review.json"
STAMP = "20260916T090000Z"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A repository that holds a PIR and nothing of this repository's tooling."""
    ws = tmp_path / "incident-repo"
    (ws / "pirs").mkdir(parents=True)
    shutil.copy(FINISHED, ws / "pirs" / "order-capture.yaml")
    shutil.copy(DRAFT, ws / "pirs" / "order-capture-draft.yaml")
    for directory in ("interviews", "clarifications", "reviews"):
        (ws / directory).mkdir()
    return ws


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_interview_loop_records_workspace_relative_paths(workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    assert validate_pir.main(["pirs/order-capture.yaml"]) == 0
    assert validate_pir.main(["pirs/order-capture-draft.yaml", "--gap-report", "gap.json"]) == 1

    interview_path = Path("interviews/order-capture-draft") / f"{STAMP}-I01.yaml"
    interview_path.parent.mkdir(parents=True)
    argv = ["--packet", "pirs/order-capture-draft.yaml", "--gap-report", "gap.json", "--round", "1"]
    assert generate_pir_interview.main([*argv, "--output", str(interview_path)]) == 0
    interview = _load(interview_path)
    assert interview["packet"] == "pirs/order-capture-draft.yaml"
    roles = {entry["role"]: entry["path"] for entry in interview["source_artifacts"]}
    assert roles["pir-packet"] == "pirs/order-capture-draft.yaml"
    assert roles["gap-report"] == "gap.json"
    # The catalogs live with the tools, outside this workspace, so they are recorded as given.
    assert Path(roles["section-expectations"]).is_absolute()

    assert (
        render_pir_interview.main([str(interview_path), "--output", str(interview_path.with_suffix(".md"))])
        == 0
    )
    ledger_path = Path("clarifications/order-capture-draft") / f"{STAMP}-L01.yaml"
    ledger_path.parent.mkdir(parents=True)
    assert open_pir_ledger.main([str(interview_path), "--output", str(ledger_path)]) == 0
    ledger = _load(ledger_path)
    assert ledger["scope"]["interview"] == interview_path.as_posix()
    assert ledger["scope"]["packet"] == "pirs/order-capture-draft.yaml"
    assert validate_pir_ledger.main([str(ledger_path)]) == 0
    assert conventions.main([]) == 0


def test_the_scaffold_cites_and_guards_the_workspace(workspace: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(workspace)
    stem_dir = Path("clarifications/order-capture")
    stem_dir.mkdir(parents=True)
    (stem_dir / f"{STAMP}-L01.yaml").write_text(
        "scope:\n  packet: pirs/order-capture.yaml\n", encoding="utf-8"
    )
    assert (
        scaffold.main(["pirs/order-capture.yaml", "--review-stage", "go", "--output", "oc.scaffold.json"])
        == 0
    )
    document = json.loads(Path("oc.scaffold.json").read_text(encoding="utf-8"))
    assert document["subject"]["path"] == "pirs/order-capture.yaml"
    assert document["clarification_ledgers"] == [f"clarifications/order-capture/{STAMP}-L01.yaml"]
    with pytest.raises(SystemExit, match="REFUSING TO WRITE"):
        scaffold.main(["pirs/order-capture.yaml", "--output", "reviews/order-capture/x.scaffold.json"])


def test_a_review_resolves_its_subject_from_the_workspace(workspace: Path, monkeypatch, capsys) -> None:
    review = json.loads(GO_REVIEW.read_text(encoding="utf-8"))
    review["subject"]["path"] = "pirs/order-capture.yaml"
    review["clarification_ledgers"] = []
    artifact = workspace / "reviews" / "order-capture" / f"{STAMP}-pir-reviewer.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(json.dumps(review), encoding="utf-8")
    monkeypatch.chdir(workspace)
    assert validate_pir_review.main([str(artifact)]) == 0
    monkeypatch.chdir(workspace.parent)
    assert validate_pir_review.main([str(artifact)]) == 1
    assert "REVIEW-SUBJECT-UNRESOLVED" in capsys.readouterr().err


def test_from_elsewhere_the_same_packet_is_recorded_as_given(
    workspace: Path, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    packet = workspace / "pirs" / "order-capture-draft.yaml"
    out = tmp_path / "i.yaml"
    assert generate_pir_interview.main(["--packet", str(packet), "--output", str(out)]) == 0
    recorded = _load(out)["packet"]
    assert recorded == "incident-repo/pirs/order-capture-draft.yaml", "relative to where it ran, not to pirs/"
    assert (
        generate_pir_interview.main(
            ["--packet", str(packet), "--repo-root", str(workspace), "--output", str(out)]
        )
        == 0
    )
    assert _load(out)["packet"] == "pirs/order-capture-draft.yaml"


def test_repo_relative_is_explicit_about_its_root(tmp_path: Path) -> None:
    inside = tmp_path / "pirs" / "x.yaml"
    assert generate_pir_interview.repo_relative(inside, tmp_path) == "pirs/x.yaml"
    assert generate_pir_interview.repo_relative(inside, tmp_path / "elsewhere") == inside.as_posix()
