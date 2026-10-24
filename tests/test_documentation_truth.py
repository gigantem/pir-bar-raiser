# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""What the documents and the agent-facing surfaces state is held to the tree.

The version both extensions state, the one example the skill hands the reviewer, the timestamp
format, the link texts an agent reads, what each exit code means, and the data/instruction
boundary each surface declares: every claim is asserted here against the code it describes.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import check_artifact_conventions as conventions
import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = Path("assistant/skills/pir-assessment")
SURFACES = (
    sorted(Path("assistant/agents").glob("*.md"))
    + sorted(Path("assistant/prompts").glob("*.md"))
    + [SKILL / "SKILL.md"]
)
LINK = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<target>[^)\s#]+)(?:#[^)]*)?\)")
SKILL_OWN = ("references/", "assets/", "pirs/", "interviews/", "clarifications/", "reviews/")


# ---------------------------------------------------------------------------- the version


def test_the_extensions_version_is_stated_once() -> None:
    """Antigravity's plugin manifest has no version field, so the VS Code manifest's version is the one
    both extensions state."""
    import build_antigravity

    vsix = json.loads(Path("vsix/package.json").read_text(encoding="utf-8"))
    antigravity = json.loads(Path("antigravity/plugin.json").read_text(encoding="utf-8"))
    assert "version" not in antigravity
    assert build_antigravity.release()["version"] == vsix["version"]


# ----------------------------------------------------------------- the skill's one asset


def test_the_skill_ships_one_example_finding_and_no_envelope() -> None:
    assets = sorted(p.name for p in (SKILL / "assets").iterdir())
    assert assets == ["finding.example.json"]
    example = json.loads((SKILL / "assets" / "finding.example.json").read_text(encoding="utf-8"))
    schema = json.loads(Path("schemas/pir-review.schema.json").read_text(encoding="utf-8"))
    finding = {**schema["$defs"]["finding"], "$defs": schema["$defs"]}
    assert not list(Draft202012Validator(finding).iter_errors(example))
    envelope = set(schema["properties"]) - {"findings"}
    assert not envelope & set(example), "the envelope comes from the scaffold, never from a template"


# ----------------------------------------------------------------- the checklist's categories


def test_the_checklist_names_every_finding_category_and_only_those() -> None:
    schema = json.loads(Path("schemas/pir-review.schema.json").read_text(encoding="utf-8"))
    enum = set(schema["$defs"]["finding"]["properties"]["category"]["enum"])
    text = (SKILL / "references" / "review-checklist.md").read_text(encoding="utf-8")
    named = {
        name
        for clause in re.findall(r"category: ([^)]*)\)", text)
        for name in re.findall(r"`([a-z_]+)`", clause)
    }
    assert named == enum


# ---------------------------------------------------------------------- names and paths


def test_the_documented_timestamp_is_the_one_the_gate_enforces() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "YYYYMMDDTHHMMSSZ" in text and "date -u +%Y%m%dT%H%M%SZ" in text
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    assert re.fullmatch(conventions.TIMESTAMP, stamp)


@pytest.mark.parametrize("surface", SURFACES, ids=str)
def test_every_link_names_its_file_by_its_path_in_the_text(surface: Path) -> None:
    """An agent running from the repository root reads the text, not the file-relative target."""
    links = [m for m in LINK.finditer(surface.read_text(encoding="utf-8")) if "://" not in m.group("target")]
    for match in links:
        text = re.fullmatch(r"`([^`]+)`", match.group("text"))
        assert text, f"{surface}: link text {match.group('text')!r} is not a path in backticks"
        resolved = (surface.parent / match.group("target")).resolve()
        if text.group(1).startswith(SKILL_OWN):
            skill_dir = next(p for p in resolved.parents if p.name == "pir-assessment")
            assert resolved.relative_to(skill_dir).as_posix() == text.group(1), match.group(0)
        else:
            assert resolved.relative_to(REPO_ROOT).as_posix() == text.group(1), match.group(0)


# ---------------------------------------------------------------- what each exit code means


def _run(*args: str) -> int:
    return subprocess.run([sys.executable, *args], capture_output=True, check=False).returncode


@pytest.mark.parametrize(
    "tool", ["tools/validate_pir.py", "tools/validate_pir_ledger.py", "tools/validate_pir_review.py"]
)
def test_a_validator_exits_one_on_a_failing_file_and_two_when_it_cannot_run(
    tool: str, tmp_path: Path
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{}\n", encoding="utf-8")
    assert _run(tool, str(broken)) == 1
    assert _run(tool, str(broken), "--bogus-flag") == 2
    assert _run(tool, "--schema", str(tmp_path / "missing.json"), str(broken)) == 2


@pytest.mark.parametrize(
    ("tool", "path"),
    [
        ("tools/validate_pir.py", "examples/good/order-capture-pool-exhaustion.yaml"),
        ("tools/validate_pir_ledger.py", "examples/ledgers/good/order-capture-draft-L01-resolved.yaml"),
        ("tools/validate_pir_review.py", "examples/reviews/good/order-capture-go-review.json"),
    ],
)
def test_a_validator_exits_zero_on_a_passing_file(tool: str, path: str) -> None:
    assert _run(tool, path) == 0


def test_a_new_packets_gaps_are_exit_one_not_a_crash() -> None:
    assert _run("tools/validate_pir.py", "examples/draft/order-capture-draft.yaml") == 1


@pytest.mark.parametrize(
    "args",
    [
        ("tools/generate_pir_interview.py", "--packet", "missing.yaml"),
        ("tools/open_pir_ledger.py", "missing.yaml"),
        ("tools/render_pir_interview.py", "missing.yaml"),
        ("tools/render_pir_review_scaffold.py", "missing.yaml", "--review-stage", "go"),
        ("tools/render_pir_docx.py", "--packet", "missing.yaml", "--format", "md"),
    ],
    ids=lambda a: a[0],
)
def test_a_generator_that_cannot_write_its_output_exits_one(args: tuple[str, ...], tmp_path: Path) -> None:
    assert _run(*(str(tmp_path / a) if a == "missing.yaml" else a for a in args)) == 1


def test_a_scaffold_aimed_under_reviews_is_refused_with_exit_one(tmp_path: Path) -> None:
    target = tmp_path / "reviews" / "order-capture" / "order-capture.scaffold.json"
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "render_pir_review_scaffold.py"),
            str(REPO_ROOT / "examples" / "good" / "order-capture-pool-exhaustion.yaml"),
            "--review-stage",
            "go",
            "--output",
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 1 and "REFUSING TO WRITE" in result.stderr, result.stderr
    assert not target.exists()


# ----------------------------------------------------------- the data/instruction boundary

DATA_CLAUSE_SURFACES = [
    *sorted(Path("assistant/agents").glob("*.md")),
    *sorted(Path("assistant/prompts").glob("*.md")),
    SKILL / "SKILL.md",
    Path("antigravity/rules/pir-invariants.md"),
    Path("vsix/installed-preamble.md"),
    Path("antigravity/installed-preamble.md"),
]


@pytest.mark.parametrize("surface", DATA_CLAUSE_SURFACES, ids=str)
def test_every_surface_says_what_it_reads_is_data(surface: Path) -> None:
    """An instruction planted in a source or a gap report is never followed, and every surface says so."""
    text = " ".join(surface.read_text(encoding="utf-8").replace(">", " ").split())
    assert re.search(r"is data[,:]? (?:not instructions)?", text), surface
    assert re.search(r"never followed|is not followed", text), surface


@pytest.mark.parametrize(
    "surface",
    [
        Path("assistant/agents/pir-interviewer.agent.md"),
        Path("assistant/prompts/interview-pir.prompt.md"),
        SKILL / "SKILL.md",
    ],
    ids=str,
)
def test_the_interviewer_takes_answers_only_from_people(surface: Path) -> None:
    text = " ".join(surface.read_text(encoding="utf-8").split())
    assert "a file can be its evidence, never its author" in text
