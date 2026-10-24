# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""A reviewer-findings artifact says what it counted, about the packet it names.

Each `REVIEW-` rule is proven by its fixture (the parametrised test in test_validator_rules.py
covers those by rule id). What is added here is the cross-file half against trees built under
tmp_path, and the two couplings new to this repo: gate evidence is recomputed when the packet
is unchanged, and a review cannot pass a packet the gate rejects.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
import validate_pir
import validate_pir_review

REPO_ROOT = Path(__file__).resolve().parent.parent
GOOD_DIR = REPO_ROOT / "examples" / "reviews" / "good"
GOOD_REVIEWS = sorted(GOOD_DIR.glob("*.json"))
GO_REVIEW = GOOD_DIR / "order-capture-go-review.json"
READINESS = GOOD_DIR / "order-capture-draft-readiness.json"
FINISHED = REPO_ROOT / "examples" / "good" / "order-capture-pool-exhaustion.yaml"
DRAFT = REPO_ROOT / "examples" / "draft" / "order-capture-draft.yaml"


@pytest.fixture(scope="module")
def schema() -> dict:
    return validate_pir_review.load_schema()


def _go() -> dict:
    return copy.deepcopy(json.loads(GO_REVIEW.read_text(encoding="utf-8")))


def _rules(findings: validate_pir_review.Findings) -> list[str]:
    return [f.rule for f in findings.items]


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A repository shaped like this one: the packet under pirs/, the ledger where the review cites it."""
    (tmp_path / "pirs").mkdir()
    (tmp_path / "examples" / "ledgers" / "good").mkdir(parents=True)
    (tmp_path / "examples" / "good").mkdir(parents=True)
    shutil.copy(FINISHED, tmp_path / "pirs" / "order-capture.yaml")
    shutil.copy(FINISHED, tmp_path / "examples" / "good" / FINISHED.name)
    shutil.copy(
        REPO_ROOT / "examples" / "ledgers" / "good" / "order-capture-draft-L01-resolved.yaml",
        tmp_path / "examples" / "ledgers" / "good" / "order-capture-draft-L01-resolved.yaml",
    )
    return tmp_path


# ------------------------------------------------------------------------- committed corpus


@pytest.mark.parametrize("path", GOOD_REVIEWS, ids=[p.name for p in GOOD_REVIEWS])
def test_every_committed_review_is_clean(path: Path, schema: dict) -> None:
    review = json.loads(path.read_text(encoding="utf-8"))
    findings = validate_pir_review.validate_review(review, schema, REPO_ROOT, path)
    assert findings.errors == [], [f.render() for f in findings.errors]
    assert findings.warnings == [], [f.render() for f in findings.warnings]


def test_committed_reviews_are_current_not_stale() -> None:
    """A stale revision is only a warning, so the examples must be shown to be current on purpose."""
    for path, packet in ((GO_REVIEW, FINISHED), (READINESS, DRAFT)):
        review = json.loads(path.read_text(encoding="utf-8"))
        assert review["subject"]["revision"] == validate_pir_review.packet_digest(packet), (
            f"{path.name} reviews bytes the packet no longer has; regenerate its subject and gate_evidence "
            f"from tools/render_pir_review_scaffold.py"
        )


def test_the_readiness_review_fails_because_the_gate_fails() -> None:
    review = json.loads(READINESS.read_text(encoding="utf-8"))
    assert review["gate_evidence"]["validator_status"] == "FAIL"
    assert review["status"] == "FAIL"
    # Measured, not typed: the recorded count is what the validator says about the draft today.
    draft = validate_pir.load_document(REPO_ROOT / review["subject"]["path"])
    fresh = validate_pir_review.gate_evidence_for(draft)
    assert review["gate_evidence"]["error_count"] == fresh["error_count"] > 0


# ------------------------------------------------------------------------- derived fields


def test_status_is_derived_from_the_findings() -> None:
    assert validate_pir_review.expected_status([]) == "PASS"
    blocker = {"severity": "blocker"}
    waived = {"severity": "blocker", "waiver": {"by": "x", "reason": "accepted residual risk"}}
    info = {"severity": "info"}
    assert validate_pir_review.expected_status([blocker, info]) == "FAIL"
    assert validate_pir_review.expected_status([waived, info]) == "PASS_WITH_WAIVERS"
    assert validate_pir_review.expected_status([waived, blocker]) == "FAIL"
    assert validate_pir_review.expected_counts([waived, blocker, info]) == {
        "blocker_count": 2,
        "non_blocker_count": 1,
        "waiver_count": 1,
    }


def test_a_waived_blocker_passes_with_waivers(schema: dict) -> None:
    review = _go()
    review["findings"][0]["severity"] = "blocker"
    review["findings"][0]["waiver"] = {
        "by": "GO, Digital Channels",
        "reason": "Accepted as residual risk for this review.",
    }
    review["status"] = "PASS_WITH_WAIVERS"
    review["blocker_count"], review["non_blocker_count"], review["waiver_count"] = 1, 1, 1
    findings = validate_pir_review.validate_review(review, schema)
    assert findings.errors == [], [f.render() for f in findings.errors]


# ------------------------------------------------------------------------ subject and gate


def _readiness() -> dict:
    return copy.deepcopy(json.loads(READINESS.read_text(encoding="utf-8")))


def test_gate_evidence_is_recomputed_only_while_the_revision_is_current(schema: dict) -> None:
    review = _readiness()
    review["gate_evidence"]["error_count"] = 3
    findings = validate_pir_review.validate_review(review, schema)
    assert "REVIEW-GATE-EVIDENCE" in _rules(findings)
    review["subject"]["revision"] = "packet-sha256:" + "f" * 64
    findings = validate_pir_review.validate_review(review, schema)
    assert "REVIEW-GATE-EVIDENCE" not in _rules(findings)
    assert [f.rule for f in findings.warnings] == ["REVIEW-SUBJECT-STALE"]
    assert findings.errors == [], "a stale FAIL review is history, not an error"


@pytest.mark.parametrize("status", ["PASS", "PASS_WITH_WAIVERS"])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("revision", None),
        ("revision", "packet-sha256:" + "f" * 64),
        ("path", "external:SRE/pirs/order-capture.yaml"),
    ],
    ids=["null-revision", "stale-revision", "external-subject"],
)
def test_a_passing_review_must_be_verifiable(
    schema: dict, status: str, field: str, value: str | None
) -> None:
    """A pass nothing here can verify is an error, reported once."""
    review = _go()
    review["status"] = status
    if status == "PASS_WITH_WAIVERS":
        review["findings"][0]["waiver"] = {
            "by": "GO, Digital Channels",
            "reason": "Accepted as residual risk.",
        }
        review["waiver_count"] = 1
    review["subject"][field] = value
    findings = validate_pir_review.validate_review(review, schema)
    assert [f.rule for f in findings.errors] == ["REVIEW-PASS-UNVERIFIED"], [
        f.render() for f in findings.items
    ]
    assert "REVIEW-SUBJECT-STALE" not in _rules(findings)


@pytest.mark.parametrize(
    ("field", "value"),
    [("revision", None), ("path", "external:SRE/pirs/order-capture-draft.yaml")],
    ids=["null-revision", "external-subject"],
)
def test_a_failing_review_without_a_verifiable_subject_is_honest_history(
    schema: dict, field: str, value: str | None
) -> None:
    review = _readiness()
    review["subject"][field] = value
    review["gate_evidence"]["warning_count"] = 7
    findings = validate_pir_review.validate_review(review, schema)
    assert findings.items == [], [f.render() for f in findings.items]


def test_a_review_cannot_pass_a_packet_the_gate_rejects(schema: dict) -> None:
    review = json.loads(READINESS.read_text(encoding="utf-8"))
    for finding in review["findings"]:
        finding["severity"] = "info"
    review["status"], review["blocker_count"], review["non_blocker_count"] = "PASS", 0, 3
    findings = validate_pir_review.validate_review(review, schema)
    assert "REVIEW-GATE-FAIL-PASSED" in _rules(findings)


def test_external_subject_is_reported_not_resolved(tree: Path, schema: dict) -> None:
    review = _readiness()
    review["subject"]["path"] = "external:SRE/pirs/order-capture.yaml"
    findings = validate_pir_review.validate_review(review, schema, repo_root=tree)
    assert "REVIEW-SUBJECT-UNRESOLVED" not in _rules(findings)
    assert any("SRE/pirs/order-capture.yaml" in ref for ref in findings.external)


# ---------------------------------------------------------------------------------- filing


def test_filing_under_reviews_binds_the_subject_to_the_stem(tree: Path, schema: dict) -> None:
    review = _go()
    artifact = tree / "reviews" / "order-capture" / "20260912T090000Z-pir-reviewer.json"
    findings = validate_pir_review.validate_review(review, schema, tree, artifact)
    misfiled = [f for f in findings.items if f.rule == "REVIEW-FILING"]
    assert misfiled and "pirs/order-capture.yaml" in misfiled[0].message
    review["subject"]["path"] = "pirs/order-capture.yaml"
    findings = validate_pir_review.validate_review(review, schema, tree, artifact)
    assert "REVIEW-FILING" not in _rules(findings), [f.render() for f in findings.items]
    badly_named = tree / "reviews" / "order-capture" / "notes.json"
    findings = validate_pir_review.validate_review(review, schema, tree, badly_named)
    assert any(f.rule == "REVIEW-FILING" and "not named" in f.message for f in findings.items)


def test_artifacts_outside_reviews_are_not_filing_checked(tree: Path, schema: dict) -> None:
    findings = validate_pir_review.validate_review(_go(), schema, tree, tree / "scratch" / "x.json")
    assert "REVIEW-FILING" not in _rules(findings)


# ----------------------------------------------------------------------------------- the CLI


def test_cli_passes_good_and_fails_bad(tmp_path: Path, capsys) -> None:
    assert validate_pir_review.main([str(GO_REVIEW)]) == 0
    bad = _go()
    bad["blocker_count"] = 4
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    assert validate_pir_review.main([str(bad_path)]) == 1
    assert "REVIEW-COUNTS" in capsys.readouterr().err


def test_cli_reports_an_unreadable_review(tmp_path: Path, capsys) -> None:
    unreadable = tmp_path / "x.json"
    unreadable.write_text("[1, 2]", encoding="utf-8")
    assert validate_pir_review.main([str(unreadable)]) == 1
    assert "could not be read" in capsys.readouterr().err


def test_the_readiness_summary_states_the_gaps_the_gate_measures() -> None:
    """Its prose counts went stale once (15 across nine, after the gate measured 16 across eight); measure them."""
    words = dict(
        enumerate(
            [
                "zero",
                "one",
                "two",
                "three",
                "four",
                "five",
                "six",
                "seven",
                "eight",
                "nine",
                "ten",
                "eleven",
                "twelve",
            ]
        )
    )
    findings = validate_pir.validate_packet(
        validate_pir.load_document(DRAFT),
        validate_pir.load_schema(),
        validate_pir.blame_patterns(),
        validate_pir.vague_action_patterns(),
    )
    sections = len({f.section for f in findings.errors})
    summary = _readiness()["summary"]
    assert f"{len(findings.errors)} blocking gaps across {words[sections]} sections" in summary, summary


# ------------------------------------------------ a review may not be ahead of its packet

STAGES = ("readiness", "team", "go", "exec_go")
STATUSES = ("draft", "in_team_review", "in_go_review", "published")
#: Owner, 2026-10-22: the least advanced status each stage can be held at; later is allowed.
AHEAD = {
    ("team", "draft"),
    ("go", "draft"),
    ("go", "in_team_review"),
    ("exec_go", "draft"),
    ("exec_go", "in_team_review"),
}


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("stage", STAGES)
def test_the_stage_status_table(tmp_path: Path, stage: str, status: str) -> None:
    packet = validate_pir.load_document(REPO_ROOT / "examples" / "draft" / "order-capture-draft.yaml")
    packet["status"] = status
    (tmp_path / "pirs").mkdir()
    (tmp_path / "pirs" / "order-capture-draft.yaml").write_text(json.dumps(packet), encoding="utf-8")
    review = json.loads(
        (REPO_ROOT / "examples" / "reviews" / "good" / "order-capture-draft-readiness.json").read_text(
            encoding="utf-8"
        )
    )
    review["review_stage"] = stage
    review["subject"]["path"] = "pirs/order-capture-draft.yaml"
    review["clarification_ledgers"] = []
    findings = validate_pir_review.validate_review(review, validate_pir_review.load_schema(), tmp_path)
    assert ("REVIEW-STAGE-AHEAD" in _rules(findings)) == ((stage, status) in AHEAD), (stage, status)


def test_the_table_covers_every_stage_and_status() -> None:
    schema = json.loads((REPO_ROOT / "schemas" / "pir-review.schema.json").read_text(encoding="utf-8"))
    assert tuple(schema["properties"]["review_stage"]["enum"]) == STAGES
    packet_schema = json.loads((REPO_ROOT / "schemas" / "pir-packet.schema.json").read_text(encoding="utf-8"))
    assert (
        tuple(packet_schema["properties"]["status"]["enum"])
        == validate_pir_review.PACKET_STATUS_ORDER
        == STATUSES
    )
    assert set(validate_pir_review.STAGE_NEEDS_STATUS) == set(STAGES)
