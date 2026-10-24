# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""A clarification ledger is held against the interview it came from and the packet it fed.

The committed good ledgers pass; each `LEDGER-` rule is proven by its own fixture (the
parametrised test in test_validator_rules.py covers those by rule id). What is added here is
the cross-file half, exercised against trees built under tmp_path so both polarities are real:
a cited path either resolves, is declared external, or is reported; a ledger either matches
its interview or says where it differs; an applied_to pointer either names something in the
packet or does not.
"""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest
import validate_pir_ledger
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
GOOD_DIR = REPO_ROOT / "examples" / "ledgers" / "good"
GOOD_LEDGERS = sorted(p for p in GOOD_DIR.glob("*.yaml") if not p.name.endswith(".mutation.yaml"))
RESOLVED = GOOD_DIR / "order-capture-draft-L01-resolved.yaml"
INTERVIEW = REPO_ROOT / "examples" / "interviews" / "order-capture-draft-I01.yaml"
FINISHED_PACKET = REPO_ROOT / "examples" / "good" / "order-capture-pool-exhaustion.yaml"


@pytest.fixture(scope="module")
def schema() -> dict:
    return validate_pir_ledger.load_schema()


def _resolved() -> dict:
    return copy.deepcopy(yaml.safe_load(RESOLVED.read_text(encoding="utf-8")))


def _rules(findings: validate_pir_ledger.Findings) -> list[str]:
    return [f.rule for f in findings.items]


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A repository-shaped tree holding the finished packet, the interview and the resolved ledger."""
    (tmp_path / "examples" / "good").mkdir(parents=True)
    (tmp_path / "examples" / "interviews").mkdir(parents=True)
    (tmp_path / "examples" / "draft").mkdir(parents=True)
    shutil.copy(FINISHED_PACKET, tmp_path / "examples" / "good" / FINISHED_PACKET.name)
    shutil.copy(INTERVIEW, tmp_path / "examples" / "interviews" / INTERVIEW.name)
    shutil.copy(
        REPO_ROOT / "examples" / "draft" / "order-capture-draft.yaml",
        tmp_path / "examples" / "draft" / "order-capture-draft.yaml",
    )
    return tmp_path


# ------------------------------------------------------------------------- committed corpus


@pytest.mark.parametrize("path", GOOD_LEDGERS, ids=[p.name for p in GOOD_LEDGERS])
def test_every_committed_ledger_is_clean(path: Path, schema: dict) -> None:
    ledger = yaml.safe_load(path.read_text(encoding="utf-8"))
    findings = validate_pir_ledger.validate_ledger(ledger, schema)
    assert findings.errors == [], [f.render() for f in findings.errors]
    assert findings.warnings == [], [f.render() for f in findings.warnings]


def test_there_are_committed_ledgers() -> None:
    assert len(GOOD_LEDGERS) >= 3, "open, partial and resolved states are each exercised"


def test_the_resolved_ledger_reports_its_external_references(schema: dict) -> None:
    findings = validate_pir_ledger.validate_ledger(_resolved(), schema)
    assert len(findings.external) == 2
    assert all(not ref.startswith(validate_pir_ledger.EXTERNAL_PREFIX) for ref in findings.external)


# ------------------------------------------------------------------------- path resolution


def test_paths_resolve_against_the_given_root(tree: Path, schema: dict) -> None:
    findings = validate_pir_ledger.validate_ledger(_resolved(), schema, repo_root=tree)
    assert "LEDGER-PATH-UNRESOLVED" not in _rules(findings), [f.render() for f in findings.items]
    empty = tree / "empty"
    empty.mkdir()
    findings = validate_pir_ledger.validate_ledger(_resolved(), schema, repo_root=empty)
    unresolved = [f for f in findings.items if f.rule == "LEDGER-PATH-UNRESOLVED"]
    assert {f.path for f in unresolved} == {"$.scope.packet", "$.scope.interview"}


def test_an_external_reference_is_reported_not_resolved(tree: Path, schema: dict) -> None:
    ledger = _resolved()
    ledger["scope"]["packet"] = "external:SRE/pirs/order-capture.yaml"
    findings = validate_pir_ledger.validate_ledger(ledger, schema, repo_root=tree)
    assert "LEDGER-PATH-UNRESOLVED" not in _rules(findings)
    assert any("SRE/pirs/order-capture.yaml" in ref for ref in findings.external)
    # With no packet to open, applied_to cannot be checked, and nothing pretends it was.
    assert "LEDGER-APPLIED-UNRESOLVED" not in _rules(findings)


def test_a_prose_answer_source_is_not_resolved(tree: Path, schema: dict) -> None:
    ledger = _resolved()
    ledger["questions"][0]["answer_source"] = "phone call with the on-call engineer, 2026-09-05"
    findings = validate_pir_ledger.validate_ledger(ledger, schema, repo_root=tree)
    assert "LEDGER-PATH-UNRESOLVED" not in _rules(findings)


def test_a_path_shaped_answer_source_must_resolve(tree: Path, schema: dict) -> None:
    ledger = _resolved()
    ledger["questions"][0]["answer_source"] = "docs/evidence/nope.md"
    findings = validate_pir_ledger.validate_ledger(ledger, schema, repo_root=tree)
    assert any(f.rule == "LEDGER-PATH-UNRESOLVED" and "answer_source" in f.path for f in findings.items)


# ------------------------------------------------------------------- held against the interview


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda led: led["scope"].__setitem__("packet_id", "PIR-2026-9999"), "scope.packet_id"),
        (lambda led: led["scope"].__setitem__("round", 2), "scope.round"),
        (lambda led: led.__setitem__("id", "PIR-2026-0412-L02"), "does not pair"),
        (lambda led: led["questions"][0].__setitem__("blocking", False), "Q-001.blocking"),
        (lambda led: led["questions"][0].__setitem__("section", "summary"), "Q-001.section"),
        (
            # An id no interview reaches: the interview's own numbering grows when a rule is added.
            lambda led: led["questions"].append({**led["questions"][0], "id": "Q-999"}),
            "Q-999 is not a question",
        ),
    ],
    ids=["packet_id", "round", "id", "blocking", "section", "extra"],
)
def test_disagreement_with_the_interview_is_named(tree: Path, schema: dict, mutate, fragment: str) -> None:
    ledger = _resolved()
    mutate(ledger)
    ledger["finding_counts"] = validate_pir_ledger.expected_counts(ledger["questions"])
    findings = validate_pir_ledger.validate_ledger(ledger, schema, repo_root=tree)
    mismatches = [f.render() for f in findings.items if f.rule == "LEDGER-INTERVIEW-MISMATCH"]
    assert any(fragment in m for m in mismatches), [f.render() for f in findings.items]


def test_an_unloadable_interview_is_a_mismatch_not_a_pass(tree: Path, schema: dict) -> None:
    (tree / "examples" / "interviews" / INTERVIEW.name).write_text("id: nope\n", encoding="utf-8")
    findings = validate_pir_ledger.validate_ledger(_resolved(), schema, repo_root=tree)
    assert any(
        f.rule == "LEDGER-INTERVIEW-MISMATCH" and "could not be loaded" in f.message for f in findings.items
    )


# ------------------------------------------------------------------------ applied_to pointers


def test_applied_to_pointers_are_resolved_in_the_packet(tree: Path, schema: dict) -> None:
    ledger = _resolved()
    ledger["questions"][8]["applied_to"] = ["/five_whys/9", "/five_whys/1/whys/0/because"]
    findings = validate_pir_ledger.validate_ledger(ledger, schema, repo_root=tree)
    bad = [f for f in findings.items if f.rule == "LEDGER-APPLIED-UNRESOLVED"]
    assert len(bad) == 1 and "/five_whys/9" in bad[0].message and bad[0].path.endswith("applied_to[0]")


def test_answers_applied_to_the_draft_rather_than_the_finished_packet_are_caught(
    tree: Path, schema: dict
) -> None:
    """The resolved ledger's pointers name content the draft does not have yet."""
    ledger = _resolved()
    ledger["scope"]["packet"] = "examples/draft/order-capture-draft.yaml"
    findings = validate_pir_ledger.validate_ledger(ledger, schema, repo_root=tree)
    assert any(f.rule == "LEDGER-APPLIED-UNRESOLVED" and "/five_whys/1" in f.message for f in findings.items)


# -------------------------------------------------------------------------- named ownership


@pytest.mark.parametrize("value", validate_pir_ledger.GENERIC_ANSWERERS)
def test_every_generic_answerer_is_rejected(value: str, schema: dict) -> None:
    ledger = _resolved()
    ledger["questions"][0]["answered_by"] = value.title()
    findings = validate_pir_ledger.validate_ledger(ledger, schema)
    assert any(
        f.rule == "LEDGER-ANSWERER-GENERIC" and f.path == "$.questions[0].answered_by" for f in findings.items
    ), value


@pytest.mark.parametrize(
    "value", ["A. Example (Order Capture product owner)", "Observability COE", "Order Capture team"]
)
def test_a_named_person_or_team_is_accepted(value: str, schema: dict) -> None:
    ledger = _resolved()
    ledger["questions"][0]["answered_by"] = value
    findings = validate_pir_ledger.validate_ledger(ledger, schema)
    assert "LEDGER-ANSWERER-GENERIC" not in _rules(findings)


def test_a_deferral_to_a_role_is_rejected(schema: dict) -> None:
    ledger = yaml.safe_load((GOOD_DIR / "order-capture-draft-L01-partial.yaml").read_text(encoding="utf-8"))
    ledger["questions"][12]["deferral"]["owner"] = "the team"
    findings = validate_pir_ledger.validate_ledger(ledger, schema)
    assert any(f.rule == "LEDGER-ANSWERER-GENERIC" and "deferral.owner" in f.path for f in findings.items)


# ------------------------------------------------------------------------- status alignment


def test_partially_resolved_needs_both_settled_and_open(schema: dict) -> None:
    all_open = yaml.safe_load((GOOD_DIR / "order-capture-draft-L01-open.yaml").read_text(encoding="utf-8"))
    all_open["status"] = "PARTIALLY_RESOLVED"
    findings = validate_pir_ledger.validate_ledger(all_open, schema)
    assert any("no question is settled" in f.message for f in findings.items)
    none_open = _resolved()
    none_open["status"] = "PARTIALLY_RESOLVED"
    findings = validate_pir_ledger.validate_ledger(none_open, schema)
    assert any("no question is open" in f.message for f in findings.items)


# ----------------------------------------------------------------------------------- the CLI


def test_cli_passes_good_and_fails_bad(tmp_path: Path, capsys) -> None:
    assert validate_pir_ledger.main([str(RESOLVED)]) == 0
    assert "2 external reference(s)" in capsys.readouterr().err
    bad = _resolved()
    bad["finding_counts"]["open"] = 5
    bad_path = tmp_path / "bad.yaml"
    bad_path.write_text(yaml.safe_dump(bad, sort_keys=False), encoding="utf-8")
    assert validate_pir_ledger.main([str(bad_path)]) == 1
    assert "LEDGER-COUNTS" in capsys.readouterr().err


def test_cli_reports_an_unreadable_ledger(tmp_path: Path, capsys) -> None:
    unreadable = tmp_path / "x.yaml"
    unreadable.write_text("- not\n- a\n- ledger\n", encoding="utf-8")
    assert validate_pir_ledger.main([str(unreadable)]) == 1
    assert "could not be read" in capsys.readouterr().err


def test_cli_honours_repo_root(tree: Path, capsys) -> None:
    empty = tree / "empty"
    empty.mkdir()
    assert validate_pir_ledger.main([str(RESOLVED), "--repo-root", str(empty)]) == 1
    assert "LEDGER-PATH-UNRESOLVED" in capsys.readouterr().err
    assert validate_pir_ledger.main([str(RESOLVED), "--repo-root", str(tree)]) == 0
