# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""The scaffold prefills the mechanical half of a review and can never be mistaken for one.

Three mechanisms keep the two apart, and each is shown to work rather than described: the
sentinels are rejected by name, the _scaffold block fails the schema (and the tool aborts if its
output would ever pass), and the tool refuses to write where committed reviews live. The
committed scaffold example is regenerated and compared so the mechanical half cannot drift.
"""

from __future__ import annotations

import json
from pathlib import Path

import pir_interview
import pytest
import render_pir_review_scaffold as scaffold
import validate_pir
import validate_pir_review

REPO_ROOT = Path(__file__).resolve().parent.parent
DRAFT = REPO_ROOT / "examples" / "draft" / "order-capture-draft.yaml"
FINISHED = REPO_ROOT / "examples" / "good" / "order-capture-pool-exhaustion.yaml"
GOLDEN = REPO_ROOT / "examples" / "scaffolds" / "order-capture-draft.scaffold.json"


def _build(packet_path: Path, stage: str = "readiness") -> dict:
    packet = validate_pir.load_document(packet_path)
    return scaffold.build_scaffold(packet_path, packet, "pir-reviewer", stage, [])


def test_the_committed_scaffold_is_what_the_tool_produces_today() -> None:
    assert scaffold.serialise(_build(DRAFT)) == GOLDEN.read_text(encoding="utf-8")
    assert scaffold.main([str(DRAFT), "--check", str(GOLDEN)]) == 0


def test_every_judgement_field_is_a_sentinel_and_every_mechanical_field_is_a_fact() -> None:
    document = _build(FINISHED, "go")
    for field in scaffold.JUDGEMENT_FIELDS:
        if field == "coverage":
            # One sentinel per template section, in catalog order: the checklist the reviewer walks.
            assert list(document[field]) == list(pir_interview.load_section_catalog())
            assert set(document[field].values()) == {scaffold.JUDGEMENT}
        else:
            assert document[field] == scaffold.JUDGEMENT, field
    assert document["subject"]["revision"] == validate_pir_review.packet_digest(FINISHED)
    assert document["subject"]["id"] == "PIR-2026-0412"
    assert document["gate_evidence"] == validate_pir_review.gate_evidence_for(
        validate_pir.load_document(FINISHED)
    )
    assert document["gate_evidence"]["validator_status"] == "PASS"
    assert set(document["_scaffold"]["judgement_fields"]) == set(scaffold.JUDGEMENT_FIELDS)


def test_a_scaffold_cannot_pass_as_a_review() -> None:
    document = _build(FINISHED, "go")
    findings = validate_pir_review.validate_review(document, validate_pir_review.load_schema())
    rules = {f.rule for f in findings.errors}
    assert "REVIEW-SCHEMA" in rules and "REVIEW-SENTINEL" in rules
    scaffold.assert_not_a_review(document)  # does not raise: the boundary holds


def test_the_tool_aborts_if_its_output_would_pass() -> None:
    """The one thing the tool must never emit, shown to be refused rather than trusted."""
    document = _build(FINISHED, "go")
    del document["_scaffold"]
    document.update(
        {
            "status": "PASS",
            "summary": "A review typed over the scaffold without judgement.",
            "blocker_count": 0,
            "non_blocker_count": 0,
            "waiver_count": 0,
            "findings": [],
        }
    )
    with pytest.raises(SystemExit, match="REFUSING TO EMIT"):
        scaffold.assert_not_a_review(document)


def test_a_sentinel_typed_into_a_string_field_is_still_refused() -> None:
    document = _build(FINISHED, "go")
    del document["_scaffold"]
    document.update(
        {
            "status": "PASS",
            "summary": "ASSESSOR_JUDGEMENT_REQUIRED but it is long enough",
            "blocker_count": 0,
            "non_blocker_count": 0,
            "waiver_count": 0,
            "findings": [],
        }
    )
    findings = validate_pir_review.validate_review(document, validate_pir_review.load_schema())
    assert any(f.rule == "REVIEW-SENTINEL" for f in findings.errors)


@pytest.mark.parametrize(
    "output",
    [
        "reviews/order-capture/20260912T090000Z-pir-reviewer.json",
        "reviews/order-capture/x.scaffold.json",
        "elsewhere/20260912T090000Z-pir-reviewer.json",
    ],
)
def test_the_tool_refuses_review_slots(output: str) -> None:
    with pytest.raises(SystemExit, match="REFUSING TO WRITE"):
        scaffold.assert_output_path_is_not_a_review_slot(REPO_ROOT / output)


def test_a_scaffold_name_outside_reviews_is_allowed(tmp_path: Path) -> None:
    scaffold.assert_output_path_is_not_a_review_slot(tmp_path / "order-capture.scaffold.json")
    out = tmp_path / "order-capture.scaffold.json"
    assert scaffold.main([str(DRAFT), "--output", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["gate_evidence"]["validator_status"] == "FAIL"


def test_ledgers_are_discovered_for_the_packet(tmp_path: Path) -> None:
    (tmp_path / "pirs").mkdir()
    packet = tmp_path / "pirs" / "order-capture.yaml"
    packet.write_bytes(FINISHED.read_bytes())
    stem_dir = tmp_path / "clarifications" / "order-capture"
    stem_dir.mkdir(parents=True)
    (stem_dir / "20260905T000000Z-L01.yaml").write_text(
        "scope:\n  packet: pirs/order-capture.yaml\n", encoding="utf-8"
    )
    (stem_dir / "20260906T000000Z-L02.yaml").write_text(
        "scope:\n  packet: pirs/other.yaml\n", encoding="utf-8"
    )
    assert scaffold.discover_ledgers(packet, tmp_path) == [
        "clarifications/order-capture/20260905T000000Z-L01.yaml"
    ]
    assert scaffold.discover_ledgers(tmp_path / "pirs" / "other.yaml", tmp_path) == []


def test_a_missing_packet_is_an_error(tmp_path: Path, capsys) -> None:
    assert scaffold.main([str(tmp_path / "nope.yaml")]) == 1
    assert "not found" in capsys.readouterr().err


# ------------------------------------------------------ the guard does not depend on the cwd


def _scaffold_from(cwd: Path, output: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(cwd)
    scaffold.main([str(DRAFT), "--output", str(output)])


@pytest.mark.parametrize(
    "relative",
    [
        "reviews/order-capture/order-capture.scaffold.json",
        "Reviews/order-capture/order-capture.scaffold.json",
        "nested/REVIEWS/x.scaffold.json",
        "drafts/20260912T090000Z-PIR-REVIEWER.JSON",
    ],
    ids=["reviews", "capital-reviews", "upper-reviews-deeper", "upper-case-review-name"],
)
def test_a_review_slot_is_refused_from_any_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    """Run from somewhere else with an absolute --output into another tree, and still refused."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    target = tmp_path / "workspace" / relative
    with pytest.raises(SystemExit, match="REFUSING TO WRITE"):
        _scaffold_from(elsewhere, target, monkeypatch)
    assert not target.exists()


def test_a_symbolic_link_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reviews = tmp_path / "workspace" / "reviews" / "order-capture"
    reviews.mkdir(parents=True)
    link = tmp_path / "out.scaffold.json"
    link.symlink_to(reviews / "out.scaffold.json")
    with pytest.raises(SystemExit, match="symbolic link"):
        _scaffold_from(tmp_path, link, monkeypatch)
    assert not (reviews / "out.scaffold.json").exists()


def test_a_directory_linked_into_reviews_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reviews = tmp_path / "workspace" / "reviews"
    reviews.mkdir(parents=True)
    (tmp_path / "innocent").symlink_to(reviews, target_is_directory=True)
    target = tmp_path / "innocent" / "out.scaffold.json"
    with pytest.raises(SystemExit, match="REFUSING TO WRITE"):
        _scaffold_from(tmp_path, target, monkeypatch)
    assert not (reviews / "out.scaffold.json").exists()


def test_a_scaffold_outside_any_reviews_directory_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "drafts" / "order-capture.scaffold.json"
    target.parent.mkdir()
    _scaffold_from(tmp_path, target, monkeypatch)
    assert json.loads(target.read_text(encoding="utf-8"))["_scaffold"]
