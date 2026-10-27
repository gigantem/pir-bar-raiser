#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""validate_pir_review.py: a reviewer-findings artifact says what it counted, about the packet it names.

Schema (schemas/pir-review.schema.json) plus the rules below, each with a stable `REVIEW-` id
so a finding can be named and asserted on by its id, as the packet and ledger findings
are. It exists for one defect: headline numbers typed rather than counted, a `blocker_count: 0` printed above
a blocker finding. So the counts are recomputed from the findings, and the status is derived
from them rather than read.

Two couplings are new here. The artifact carries the gate's own verdict (`gate_evidence`, copied
from the scaffold), and when `subject.revision` matches the packet on disk that evidence is
recomputed and must agree. And a review may not PASS a packet the gate rejects: the validator's
blockers are blockers. A FAIL review whose revision no longer matches the packet is reported as
stale (a warning), because a verdict on bytes that have since changed is history, not a verdict.
A passing review must be verifiable: with no revision, a
stale one, or an external subject, nothing here can show the gate passed the packet it names, so
PASS and PASS_WITH_WAIVERS are errors there.

A scaffold (tools/render_pir_review_scaffold.py) cannot pass here: its `_scaffold` block fails
the schema and its ASSESSOR_JUDGEMENT_REQUIRED sentinels fail REVIEW-SENTINEL, which exists so
that a sentinel typed into a string field that happens to satisfy minLength is still caught.

Exit 0 when every artifact passes; 1 otherwise, listing each finding; 2 when it could not run (a
wrong argument, an unreadable schema, or an artifact that cannot be opened).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pir_interview
import validate_pir

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA_PATH = REPO_ROOT / "schemas" / "pir-review.schema.json"
ERROR = validate_pir.ERROR
WARNING = validate_pir.WARNING
EXTERNAL_PREFIX = "external:"
DIGEST_PREFIX = "packet-sha256:"
JUDGEMENT = "ASSESSOR_JUDGEMENT_REQUIRED"
#: The sentinel however it is cased or separated ("assessor judgement required", "Assessor-Judgement_Required"):
#: retyping it is not forming the judgement it marks.
JUDGEMENT_MARK = re.compile(r"assessor[\s_-]*judge?ment[\s_-]*required", re.IGNORECASE)
#: reviews/<stem>/<YYYYMMDDTHHMMSSZ>-<reviewer>.json, the filing convention in reviews/README.md.
FILING_NAME = re.compile(r"^\d{8}T\d{6}Z-[a-z0-9-]+\.json$")

RULES: dict[str, str] = {
    "REVIEW-SCHEMA": ERROR,
    "REVIEW-SENTINEL": ERROR,
    "REVIEW-ID-SEQUENCE": ERROR,
    "REVIEW-COUNTS": ERROR,
    "REVIEW-STATUS": ERROR,
    "REVIEW-GATE-FAIL-PASSED": ERROR,
    "REVIEW-SUBJECT-UNRESOLVED": ERROR,
    "REVIEW-SUBJECT-ID": ERROR,
    "REVIEW-STAGE-AHEAD": ERROR,
    "REVIEW-SUBJECT-STALE": WARNING,
    "REVIEW-PASS-UNVERIFIED": ERROR,
    "REVIEW-GATE-EVIDENCE": ERROR,
    "REVIEW-LEDGER-UNRESOLVED": ERROR,
    "REVIEW-PATH-OUTSIDE": ERROR,
    "REVIEW-FINDING-SECTION": ERROR,
    "REVIEW-FINDING-RULE": ERROR,
    "REVIEW-BLAME-LANGUAGE": ERROR,
    "REVIEW-PARTY-PLACEHOLDER": ERROR,
    "REVIEW-FILING": ERROR,
    "REVIEW-COVERAGE": ERROR,
}


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    message: str
    path: str = ""

    def render(self) -> str:
        where = f" (at {self.path})" if self.path else ""
        return f"{self.rule}: {self.message}{where}"


class Findings:
    def __init__(self) -> None:
        self.items: list[Finding] = []
        self.external: list[str] = []

    def rule(self, rule_id: str, message: str, path: str = "") -> None:
        if rule_id not in RULES:
            raise KeyError(f"unregistered review rule id {rule_id}")
        self.items.append(Finding(rule_id, RULES[rule_id], message, path))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.items if f.severity == ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.items if f.severity == WARNING]


# ------------------------------------------------------------------------------------- loading


def load_schema(path: Path = DEFAULT_SCHEMA_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        schema = json.load(handle)
    if not isinstance(schema, dict):
        raise ValueError(f"{path}: schema root must be a JSON object")
    return schema


def load_review(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("review root must be a JSON object")
    return data


def packet_digest(packet_path: Path) -> str:
    """sha256 over the packet's raw bytes, the repo-wide revision formula (shared with the scaffold)."""
    return DIGEST_PREFIX + hashlib.sha256(packet_path.read_bytes()).hexdigest()


def gate_evidence_for(packet: dict[str, Any]) -> dict[str, Any]:
    """What the gate says about a packet, in the shape the review records. Shared with the scaffold."""
    findings = validate_pir.validate_packet(
        packet,
        validate_pir.load_schema(),
        validate_pir.blame_patterns(),
        validate_pir.vague_action_patterns(),
    )
    return {
        "derived_by": "tools/render_pir_review_scaffold.py",
        "validator_status": "FAIL" if findings.errors else "PASS",
        "error_count": len(findings.errors),
        "warning_count": len(findings.warnings),
        "rule_ids": sorted({f.rule for f in findings.items}),
    }


# ------------------------------------------------------------------------------------- rules


def validate_schema(review: dict[str, Any], schema: dict[str, Any], out: Findings) -> None:
    for error in sorted(Draft202012Validator(schema).iter_errors(review), key=lambda e: list(e.path)):
        out.rule(
            "REVIEW-SCHEMA",
            f"schema violation: {error.message}",
            validate_pir.format_error_path(list(error.path)),
        )


def validate_sentinels(review: dict[str, Any], out: Findings) -> None:
    for path, text in validate_pir.iter_strings(review):
        if JUDGEMENT_MARK.search(text):
            out.rule(
                "REVIEW-SENTINEL",
                "a judgement field still carries the scaffold sentinel; this is not a review",
                path,
            )


def finding_list(review: dict[str, Any]) -> list[dict[str, Any]]:
    findings = review.get("findings")
    return [f for f in findings if isinstance(f, dict)] if isinstance(findings, list) else []


def expected_counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    blockers = [f for f in findings if f.get("severity") == "blocker"]
    waived = [f for f in findings if isinstance(f.get("waiver"), dict)]
    return {
        "blocker_count": len(blockers),
        "non_blocker_count": len(findings) - len(blockers),
        "waiver_count": len(waived),
    }


def expected_status(findings: list[dict[str, Any]]) -> str:
    unwaived_blockers = [
        f for f in findings if f.get("severity") == "blocker" and not isinstance(f.get("waiver"), dict)
    ]
    if unwaived_blockers:
        return "FAIL"
    if any(isinstance(f.get("waiver"), dict) for f in findings):
        return "PASS_WITH_WAIVERS"
    return "PASS"


def validate_findings(review: dict[str, Any], sections: set[str], out: Findings) -> None:
    findings = finding_list(review)
    for index, finding in enumerate(findings):
        fid = str(finding.get("id"))
        expected = f"FIND-{index + 1:03d}"
        if fid != expected:
            out.rule(
                "REVIEW-ID-SEQUENCE",
                f"{fid} is out of sequence; expected {expected}",
                f"$.findings[{index}].id",
            )
        section = finding.get("section")
        if isinstance(section, str) and section not in sections:
            out.rule(
                "REVIEW-FINDING-SECTION",
                f"{fid} names section {section!r}, which is not a template section in the catalog",
                f"$.findings[{index}].section",
            )
        rule = finding.get("rule")
        if isinstance(rule, str) and rule not in validate_pir.RULES:
            out.rule(
                "REVIEW-FINDING-RULE",
                f"{fid} cites {rule}, which the validator does not define",
                f"$.findings[{index}].rule",
            )

    actual = expected_counts(findings)
    declared = {key: review.get(key) for key in actual}
    if all(isinstance(value, int) for value in declared.values()) and declared != actual:
        out.rule("REVIEW-COUNTS", f"counts {declared} do not match the findings {actual}", "$")

    status = review.get("status")
    should_be = expected_status(findings)
    if status in {"PASS", "FAIL", "PASS_WITH_WAIVERS"} and status != should_be:
        out.rule(
            "REVIEW-STATUS",
            f"status is {status} but the findings make it {should_be} (FAIL exactly when an unwaived blocker exists; "
            f"PASS_WITH_WAIVERS when every blocker is waived or any finding is)",
            "$.status",
        )


#: Every field of a finding the reviewer writes in their own words.
FINDING_PROSE = ("evidence", "rationale", "required_fix", "clarification_question", "target")


def review_prose(review: dict[str, Any]):
    """Every field of the review written in the reviewer's own words: (path, text). Rule ids, categories
    and other closed vocabulary are left out on purpose: "PIR-BLAME-LANGUAGE" itself contains "blame"."""
    if isinstance(review.get("summary"), str):
        yield "$.summary", review["summary"]
    coverage = review.get("coverage")
    if isinstance(coverage, dict):
        for section, judgement in coverage.items():
            if isinstance(judgement, str):
                yield f"$.coverage.{section}", judgement
    notes = review.get("notes")
    if isinstance(notes, str):
        yield "$.notes", notes
    elif isinstance(notes, list):
        for index, note in enumerate(notes):
            if isinstance(note, str):
                yield f"$.notes[{index}]", note
    for index, finding in enumerate(finding_list(review)):
        for field in FINDING_PROSE:
            if isinstance(finding.get(field), str):
                yield f"$.findings[{index}].{field}", finding[field]
        waiver = finding.get("waiver")
        if isinstance(waiver, dict) and isinstance(waiver.get("reason"), str):
            yield f"$.findings[{index}].waiver.reason", waiver["reason"]


def validate_blame(review: dict[str, Any], blame: list[tuple[str, re.Pattern[str]]], out: Findings) -> None:
    """The reviewer's own prose is held to the same standard as the PIR (deck: avoid blame in review),
    all of it: the summary, the notes, every finding's prose and every waiver's reason."""
    for path, text in review_prose(review):
        terms = validate_pir.blame_terms_in(text, blame)
        if terms:
            out.rule(
                "REVIEW-BLAME-LANGUAGE",
                f"'{terms[0]}' makes the review about a person; name the process gap instead",
                path,
            )


#: Whole-value coverage entries that record no judgement: they would be true of any packet. A
#: judgement may open with "No issues:" and go on to say what was checked; it may not stop there.
STOCK_JUDGEMENTS = frozenset(
    {
        "ok",
        "okay",
        "fine",
        "good",
        "all good",
        "looks good",
        "looks fine",
        "looks ok",
        "lgtm",
        "checked",
        "reviewed",
        "done",
        "no issues",
        "no issues found",
        "no problems",
        "no comments",
        "no findings",
        "nothing to add",
        "nothing found",
        "nothing to report",
        "as expected",
        "acceptable",
        "satisfactory",
        "not reviewed",
        "not checked",
        "skipped",
    }
)


def stock_judgement(value: str) -> str | None:
    """Why a coverage entry records no judgement, or None."""
    reason = validate_pir.evidence_placeholder(value)
    if reason:
        return reason
    core = validate_pir.core_text(value)
    return core if core in STOCK_JUDGEMENTS else None


def validate_coverage(review: dict[str, Any], sections: list[str], out: Findings) -> None:
    """Every template section was looked at, and the review says what was found there:
    a PASS with no findings and no coverage would otherwise record nothing at all."""
    coverage = review.get("coverage")
    if not isinstance(coverage, dict):
        return  # REVIEW-SCHEMA reports a missing or malformed coverage block
    for section in sections:
        if section not in coverage:
            out.rule(
                "REVIEW-COVERAGE",
                f"coverage has no judgement for section {section!r}; say what was checked there and what was found",
                "$.coverage",
            )
    for section, judgement in coverage.items():
        if section not in sections:
            out.rule(
                "REVIEW-COVERAGE",
                f"coverage names {section!r}, which is not a template section in the catalog",
                f"$.coverage.{section}",
            )
        elif isinstance(judgement, str) and not JUDGEMENT_MARK.search(judgement):
            reason = stock_judgement(judgement)
            if reason:
                out.rule(
                    "REVIEW-COVERAGE",
                    f"coverage for {section!r} records no judgement ({reason!r}); say what was checked and what was found",
                    f"$.coverage.{section}",
                )


#: First-person words that name whoever happens to be typing rather than someone accountable.
SELF_REFERENCES = frozenset({"me", "myself", "i"})


def party_placeholder(value: Any) -> str | None:
    """Why `value` names nobody accountable, or None. "pir-reviewer" (the persona) is a party."""
    reason = validate_pir.owner_placeholder(value)
    if reason:
        return reason
    core = validate_pir.core_text(value) if isinstance(value, str) else ""
    return core if core in SELF_REFERENCES else None


def validate_parties(review: dict[str, Any], out: Findings) -> None:
    """Who formed the judgements, and who accepted each waived risk, are named (accountability is named)."""
    reason = party_placeholder(review.get("reviewer"))
    if reason:
        out.rule(
            "REVIEW-PARTY-PLACEHOLDER",
            f"reviewer names nobody ({reason!r}); name the persona or person",
            "$.reviewer",
        )
    for index, finding in enumerate(finding_list(review)):
        waiver = finding.get("waiver")
        reason = party_placeholder(waiver.get("by")) if isinstance(waiver, dict) else None
        if reason:
            out.rule(
                "REVIEW-PARTY-PLACEHOLDER",
                f"{finding.get('id')} is waived by nobody accountable ({reason!r}); name who accepted the residual risk",
                f"$.findings[{index}].waiver.by",
            )


def check_reference(label: str, reference: Any, repo_root: Path, rule_id: str, out: Findings) -> Path | None:
    if not isinstance(reference, str) or not reference:
        return None
    if reference.startswith(EXTERNAL_PREFIX):
        out.external.append(f"{label}: {reference[len(EXTERNAL_PREFIX) :]}")
        return None
    target = validate_pir.contained_path(reference, repo_root)
    if target is None:
        out.rule(
            "REVIEW-PATH-OUTSIDE",
            f"{reference} leaves the repository root, so it is not opened; a cited path is relative to the root "
            f"and stays inside it (prefix it '{EXTERNAL_PREFIX}' if it deliberately lives elsewhere)",
            label,
        )
        return None
    if not target.is_file():
        out.rule(
            rule_id,
            f"{reference} does not resolve (prefix it '{EXTERNAL_PREFIX}' if it deliberately lives elsewhere)",
            label,
        )
        return None
    return target


#: The packet's statuses in the order a PIR moves through them (schemas/pir-packet.schema.json).
PACKET_STATUS_ORDER = ("draft", "in_team_review", "in_go_review", "published")
#: The least advanced packet status each review stage can be held at. A review may not claim a stage the packet has not reached; reviewing a packet that has
#: moved further (a readiness audit of a published PIR) is allowed.
STAGE_NEEDS_STATUS = {
    "readiness": "draft",
    "team": "in_team_review",
    "go": "in_go_review",
    "exec_go": "in_go_review",
}

#: Statuses that assert the packet is fit for its stage; a FAIL asserts nothing about the gate.
PASSING = frozenset({"PASS", "PASS_WITH_WAIVERS"})


def unverified_pass(review: dict[str, Any], why: str, out: Findings) -> None:
    out.rule(
        "REVIEW-PASS-UNVERIFIED",
        f"status is {review.get('status')} but {why}, so nothing shows the gate passes the packet reviewed; "
        f"re-render the scaffold against the packet as it is now and review that, or record FAIL",
        "$.subject",
    )


def validate_subject(review: dict[str, Any], repo_root: Path, out: Findings) -> None:
    subject = validate_pir.mapping(review.get("subject"))
    passing = review.get("status") in PASSING
    path = subject.get("path")
    if passing and isinstance(path, str) and path.startswith(EXTERNAL_PREFIX):
        unverified_pass(review, "the packet is external and cannot be read here", out)
    packet_path = check_reference(
        "$.subject.path", subject.get("path"), repo_root, "REVIEW-SUBJECT-UNRESOLVED", out
    )
    for index, ledger in enumerate(review.get("clarification_ledgers") or []):
        check_reference(
            f"$.clarification_ledgers[{index}]", ledger, repo_root, "REVIEW-LEDGER-UNRESOLVED", out
        )
    if packet_path is None:
        return
    try:
        packet = validate_pir.load_document(packet_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        out.rule("REVIEW-SUBJECT-UNRESOLVED", f"packet could not be read: {exc}", "$.subject.path")
        return
    if subject.get("id") != packet.get("id"):
        out.rule(
            "REVIEW-SUBJECT-ID",
            f"subject.id is {subject.get('id')!r} but the packet declares {packet.get('id')!r}",
            "$.subject.id",
        )
    stage, status = review.get("review_stage"), packet.get("status")
    needed = STAGE_NEEDS_STATUS.get(stage) if isinstance(stage, str) else None
    # An unknown stage is REVIEW-SCHEMA's to report, an unknown status the packet validator's.
    if (
        needed is not None
        and status in PACKET_STATUS_ORDER
        and PACKET_STATUS_ORDER.index(status) < PACKET_STATUS_ORDER.index(needed)
    ):
        out.rule(
            "REVIEW-STAGE-AHEAD",
            f"review_stage is {stage!r} but the packet's status is {status!r}; a {stage} review needs a "
            f"packet at {needed!r} or later, so this review claims a stage the PIR has not reached",
            "$.review_stage",
        )

    revision = subject.get("revision")
    current = packet_digest(packet_path)
    if revision is None:
        if passing:
            unverified_pass(review, "subject.revision is null (no digest was observed)", out)
        return
    if revision != current:
        if passing:
            unverified_pass(
                review,
                f"the packet has changed since it was reviewed (reviewed {revision[:23]}..., now {current[:23]}...)",
                out,
            )
            return
        out.rule(
            "REVIEW-SUBJECT-STALE",
            f"the packet has changed since this review (reviewed {revision[:23]}..., now {current[:23]}...); "
            f"the verdict is history, not a verdict on the current packet",
            "$.subject.revision",
        )
        return
    declared = review.get("gate_evidence")
    if isinstance(declared, dict):
        fresh = gate_evidence_for(packet)
        if declared != fresh:
            out.rule(
                "REVIEW-GATE-EVIDENCE",
                f"gate_evidence {declared} disagrees with a fresh run of the validator {fresh}; it is copied from the scaffold, never typed",
                "$.gate_evidence",
            )


def validate_gate_coupling(review: dict[str, Any], out: Findings) -> None:
    evidence = review.get("gate_evidence")
    if not isinstance(evidence, dict):
        return
    if evidence.get("validator_status") == "FAIL" and review.get("status") in {"PASS", "PASS_WITH_WAIVERS"}:
        out.rule(
            "REVIEW-GATE-FAIL-PASSED",
            f"status is {review.get('status')} but the validator FAILs this packet ({evidence.get('error_count')} error(s)); "
            f"a review cannot pass a packet the gate rejects",
            "$.status",
        )


def validate_filing(
    review: dict[str, Any], artifact_path: Path | None, repo_root: Path, out: Findings
) -> None:
    """An artifact under reviews/<stem>/ reviews pirs/<stem>.yaml when that packet exists."""
    if artifact_path is None:
        return
    try:
        relative = artifact_path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return
    if not relative.parts or relative.parts[0] != "reviews":
        return
    if len(relative.parts) != 3:
        # Only reviews/<stem>/<file>.json is a review; any other depth escapes the stem binding.
        out.rule(
            "REVIEW-FILING",
            f"{relative} is not filed as reviews/<stem>/<YYYYMMDDTHHMMSSZ>-<reviewer>.json",
            "$",
        )
        return
    stem = relative.parts[1]
    if not FILING_NAME.match(relative.name):
        out.rule("REVIEW-FILING", f"{relative} is not named <YYYYMMDDTHHMMSSZ>-<reviewer>.json", "$")
    subject = validate_pir.mapping(review.get("subject"))
    expected = f"pirs/{stem}.yaml"
    if (repo_root / expected).is_file() and subject.get("path") != expected:
        out.rule(
            "REVIEW-FILING",
            f"filed under reviews/{stem}/ but subject.path is {subject.get('path')!r}, not {expected}",
            "$.subject.path",
        )


def validate_review(
    review: dict[str, Any],
    schema: dict[str, Any],
    repo_root: Path = REPO_ROOT,
    artifact_path: Path | None = None,
) -> Findings:
    out = Findings()
    validate_schema(review, schema, out)
    validate_sentinels(review, out)
    sections = list(pir_interview.load_section_catalog())
    validate_findings(review, set(sections), out)
    validate_coverage(review, sections, out)
    validate_blame(review, validate_pir.blame_patterns(), out)
    validate_parties(review, out)
    validate_gate_coupling(review, out)
    validate_subject(review, repo_root, out)
    validate_filing(review, artifact_path, repo_root, out)
    return out


# --------------------------------------------------------------------------------------- CLI


def validate_path(path: Path, schema: dict[str, Any], repo_root: Path) -> int:
    print(f"VALIDATING {path}", file=sys.stderr)
    try:
        review = load_review(path)
    except OSError as exc:
        # Missing, unreadable or a directory: nothing was validated, so this is exit 2, not a gap.
        print(f"ERROR {path} cannot be opened, so nothing was validated: {exc}", file=sys.stderr)
        return 2
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL {path}\n  - REVIEW-SCHEMA: review could not be read: {exc}", file=sys.stderr)
        return 1
    findings = validate_review(review, schema, repo_root, path)
    verdict = "FAIL" if findings.errors else "PASS"
    suffix = (
        f" ({len(findings.external)} external reference(s) not resolved here)" if findings.external else ""
    )
    print(f"{verdict} {path}{suffix}", file=sys.stderr)
    for finding in findings.errors:
        print(f"  - {finding.render()}", file=sys.stderr)
    for finding in findings.warnings:
        print(f"  - warning {finding.render()}", file=sys.stderr)
    for reference in findings.external:
        print(f"  external: {reference}", file=sys.stderr)
    return 1 if findings.errors else 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate PIR reviewer-findings artifacts against schema and semantic rules."
    )
    parser.add_argument("paths", nargs="+", help="Review artifacts (.json).")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA_PATH), help="Schema to enforce.")
    parser.add_argument(
        "--repo-root",
        default=str(Path.cwd()),
        help="Directory cited paths are relative to. Defaults to the current directory: run from the "
        "root of the repository that holds pirs/ and reviews/.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        schema = load_schema(Path(args.schema))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    repo_root = Path(args.repo_root)
    exit_code = 0
    for raw in args.paths:
        exit_code = max(exit_code, validate_path(Path(raw), schema, repo_root))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
