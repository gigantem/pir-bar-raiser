#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""validate_pir_ledger.py: a clarification ledger says what happened, and it matches the packet.

Schema (schemas/pir-clarification-ledger.schema.json) plus the rules below, each with a stable
`LEDGER-` id, so a finding can be named and asserted on by its id, exactly as the packet
validator's findings are. Three lessons shape it: every cited path resolves or declares that it cannot (`external:`);
`answered_by` is a person or a team, never a role word; a ledger that is RESOLVED has no open
question. Two rules are new here because the ledger now has an interview and a packet to be
held against: the ledger's questions are the interview's questions (same ids, rules, sections
and blocking flags, none missing), and every `applied_to` pointer names something that exists
in the packet, which is what "the answer reached the packet" means mechanically.

Exit 0 when every ledger passes; 1 otherwise, listing each finding; 2 when it could not run (a wrong
argument, an unreadable schema, or a ledger that cannot be opened).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
import json_pointer
import pir_interview
import validate_pir

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA_PATH = REPO_ROOT / "schemas" / "pir-clarification-ledger.schema.json"
ERROR = validate_pir.ERROR
WARNING = validate_pir.WARNING
EXTERNAL_PREFIX = "external:"
#: Suffixes that make an `answer_source` path-shaped; anything else is prose about provenance.
PATH_SUFFIXES = (".yaml", ".yml", ".json", ".md", ".txt", ".csv", ".png", ".pdf", ".docx")
SETTLED = frozenset({"answered", "deferred", "waived"})

RULES: dict[str, str] = {
    "LEDGER-SCHEMA": ERROR,
    "LEDGER-ID-DUPLICATE": ERROR,
    "LEDGER-OPEN-HAS-ANSWER": ERROR,
    "LEDGER-SETTLED-INCOMPLETE": ERROR,
    "LEDGER-DEFERRAL-INCOMPLETE": ERROR,
    "LEDGER-WAIVER-INCOMPLETE": ERROR,
    "LEDGER-ANSWERER-GENERIC": ERROR,
    "LEDGER-COUNTS": ERROR,
    "LEDGER-STATUS": ERROR,
    "LEDGER-RESOLVED-UNAPPLIED": ERROR,
    "LEDGER-PATH-UNRESOLVED": ERROR,
    "LEDGER-PATH-OUTSIDE": ERROR,
    "LEDGER-INTERVIEW-MISMATCH": ERROR,
    "LEDGER-INTERVIEW-UNCOVERED": ERROR,
    "LEDGER-APPLIED-UNRESOLVED": ERROR,
    "LEDGER-BLOCKING-WAIVED": WARNING,
    "LEDGER-BLOCKING-DEFERRED": WARNING,
    "LEDGER-SCOPE-EXTERNAL": ERROR,
    "LEDGER-DATE-INVALID": ERROR,
}

#: Values that name a channel or a tool rather than someone who can be asked. With the packet's
#: placeholders and role words (validate_pir.owner_placeholder) they are the generic answerers. A
#: denylist, matched against the whole normalised value: it proves a value IS generic and never that
#: a value IS a person. "Order Capture product owner (A. Example)" passes because it carries a name;
#: "product owner", "the on-call engineer", "ChatGPT" and "HUMAN_CONFIRM_OWNER" do not.
CHANNELS_AND_TOOLS: tuple[str, ...] = (
    "interview",
    "chat",
    "agent",
    "assistant",
    "ai",
    "llm",
    "bot",
    "model",
    "chatgpt",
    "claude",
    "copilot",
    "gemini",
    "me",
    "myself",
    "i",
)
GENERIC_ANSWERERS: tuple[str, ...] = (
    validate_pir.PLACEHOLDER_OWNERS + validate_pir.ROLE_WORDS + CHANNELS_AND_TOOLS
)

#: Whole answers (or answer sources) that say nothing yet. Narrower than the packet's evidence list:
#: "No" and "None" are real answers to some questions.
NON_ANSWERS: frozenset[str] = frozenset({"tbd", "tba", "tbc", "todo", "pending", "unknown", "n/a", "na"})


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
            raise KeyError(f"unregistered ledger rule id {rule_id}")
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


def is_external(reference: str) -> bool:
    return reference.startswith(EXTERNAL_PREFIX)


def looks_like_path(value: str) -> bool:
    return "/" in value and value.lower().endswith(PATH_SUFFIXES)


def generic_answerer(value: str) -> str | None:
    """Why `value` names nobody who can be asked (a placeholder, a role, a channel, a tool), or None."""
    reason = validate_pir.owner_placeholder(value)
    if reason:
        return reason
    core = validate_pir.core_text(value)
    return core if core in CHANNELS_AND_TOOLS else None


def non_answer(value: Any) -> str | None:
    """Why `value` is not yet an answer (blank, a placeholder mark, a stock non-answer), or None."""
    if not isinstance(value, str) or not value.strip():
        return "blank"
    mark = validate_pir.placeholder_mark(value)
    if mark:
        return mark
    core = validate_pir.core_text(value)
    if not core:
        return "nothing but punctuation"
    return core if core in NON_ANSWERS else None


def parse_ledger_date(value: str) -> date | datetime | None:
    """A ledger date (a date, or a timestamp with an offset) as a value, or None if it is not a real one."""
    try:
        return date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value)
    except ValueError:
        return None


# ------------------------------------------------------------------------------------- rules


def validate_schema(ledger: dict[str, Any], schema: dict[str, Any], out: Findings) -> None:
    validator = Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(ledger), key=lambda item: list(item.path)):
        out.rule(
            "LEDGER-SCHEMA",
            f"schema violation: {error.message}",
            validate_pir.format_error_path(list(error.path)),
        )


def validate_question(question: dict[str, Any], index: int, out: Findings) -> None:
    qid = str(question.get("id", f"questions[{index}]"))
    where = f"$.questions[{index}]"
    status = question.get("status")
    answer = question.get("answer")
    answered_by = question.get("answered_by")
    answered_at = question.get("answered_at")
    answer_source = question.get("answer_source")
    deferral = question.get("deferral")
    waiver = question.get("waiver")

    if status == "open":
        if any(value not in (None, "") for value in (answer, answered_by, answered_at, answer_source)):
            out.rule("LEDGER-OPEN-HAS-ANSWER", f"{qid} is open but carries answer metadata", where)
        if question.get("applied_to"):
            out.rule("LEDGER-OPEN-HAS-ANSWER", f"{qid} is open but records applied_to", f"{where}.applied_to")
        if deferral is not None or waiver is not None:
            out.rule("LEDGER-OPEN-HAS-ANSWER", f"{qid} is open but carries a deferral or waiver", where)
        return

    if status not in SETTLED:
        return  # the schema has already reported the status

    for field, value in (("answered_by", answered_by), ("answered_at", answered_at)):
        if not (isinstance(value, str) and value.strip()):  # "   " is as missing as ""
            out.rule(
                "LEDGER-SETTLED-INCOMPLETE", f"{qid} is {status} but is missing {field}", f"{where}.{field}"
            )
    if status == "answered":
        for field, value in (("answer", answer), ("answer_source", answer_source)):
            reason = non_answer(value)
            if reason == "blank":
                out.rule(
                    "LEDGER-SETTLED-INCOMPLETE",
                    f"{qid} is answered but is missing {field}",
                    f"{where}.{field}",
                )
            elif reason:
                out.rule(
                    "LEDGER-SETTLED-INCOMPLETE",
                    f"{qid} is answered but its {field} {value!r} says nothing yet ({reason!r})",
                    f"{where}.{field}",
                )
    if status == "deferred":
        if not isinstance(deferral, dict):
            out.rule(
                "LEDGER-DEFERRAL-INCOMPLETE",
                f"{qid} is deferred without a deferral (owner, revisit_by, reason)",
                where,
            )
        elif isinstance(deferral.get("owner"), str) and generic_answerer(deferral["owner"]):
            out.rule(
                "LEDGER-ANSWERER-GENERIC",
                f"{qid} is deferred to {deferral['owner']!r}, which names a role rather than a person or team",
                f"{where}.deferral.owner",
            )
        if question.get("blocking") is True:
            out.rule(
                "LEDGER-BLOCKING-DEFERRED",
                f"{qid} is blocking and deferred; the packet will still fail the gate on {question.get('rule')} until it is answered",
                where,
            )
    elif deferral is not None:
        out.rule(
            "LEDGER-DEFERRAL-INCOMPLETE", f"{qid} is {status} but carries a deferral", f"{where}.deferral"
        )
    if status == "waived":
        if not isinstance(waiver, dict):
            out.rule("LEDGER-WAIVER-INCOMPLETE", f"{qid} is waived without a waiver reason", where)
        if question.get("blocking") is True:
            out.rule(
                "LEDGER-BLOCKING-WAIVED",
                f"{qid} is blocking and waived; the packet will still fail the gate on {question.get('rule')}",
                where,
            )
    elif waiver is not None:
        out.rule("LEDGER-WAIVER-INCOMPLETE", f"{qid} is {status} but carries a waiver", f"{where}.waiver")

    if isinstance(answered_by, str) and answered_by.strip():
        phrase = generic_answerer(answered_by)
        if phrase:
            out.rule(
                "LEDGER-ANSWERER-GENERIC",
                f"{qid} is {status} by {answered_by!r}, which names a role rather than a person or team (matched {phrase!r})",
                f"{where}.answered_by",
            )


def validate_dates(ledger: dict[str, Any], schema: dict[str, Any], out: Findings) -> None:
    """A date the schema's shape accepts but the calendar does not ("2026-13-45"), as for packets."""
    shape = re.compile(str(schema.get("$defs", {}).get("date", {}).get("pattern", "^$")))
    for index, question in enumerate(ledger.get("questions") or []):
        if not isinstance(question, dict):
            continue
        deferral = validate_pir.mapping(question.get("deferral"))
        for path, value in (
            (f"$.questions[{index}].answered_at", question.get("answered_at")),
            (f"$.questions[{index}].deferral.revisit_by", deferral.get("revisit_by")),
        ):
            if isinstance(value, str) and shape.search(value) and parse_ledger_date(value) is None:
                out.rule(
                    "LEDGER-DATE-INVALID",
                    f"{value!r} is shaped like a date but is not a real one; when was it, really?",
                    path,
                )


def validate_questions(ledger: dict[str, Any], out: Findings) -> None:
    seen: set[str] = set()
    for index, question in enumerate(ledger.get("questions") or []):
        if not isinstance(question, dict):
            continue
        qid = str(question.get("id"))
        if qid in seen:
            out.rule("LEDGER-ID-DUPLICATE", f"{qid} appears more than once", f"$.questions[{index}].id")
        seen.add(qid)
        validate_question(question, index, out)


def expected_counts(questions: list[Any]) -> dict[str, int]:
    dicts = [q for q in questions if isinstance(q, dict)]
    return {
        "total": len(dicts),
        "open": sum(1 for q in dicts if q.get("status") == "open"),
        "blocking_open": sum(1 for q in dicts if q.get("status") == "open" and q.get("blocking") is True),
    }


def validate_counts_and_status(ledger: dict[str, Any], out: Findings) -> None:
    questions = ledger.get("questions")
    if not isinstance(questions, list):
        return
    actual = expected_counts(questions)
    declared = ledger.get("finding_counts")
    if isinstance(declared, dict) and declared != actual:
        out.rule(
            "LEDGER-COUNTS",
            f"finding_counts {declared} do not match the questions {actual}",
            "$.finding_counts",
        )

    status = ledger.get("status")
    settled = actual["total"] - actual["open"]
    if status == "OPEN" and settled:
        out.rule(
            "LEDGER-STATUS",
            f"status OPEN but {settled} question(s) are settled; use PARTIALLY_RESOLVED",
            "$.status",
        )
    if status == "PARTIALLY_RESOLVED":
        if not settled:
            out.rule(
                "LEDGER-STATUS", "status PARTIALLY_RESOLVED but no question is settled; use OPEN", "$.status"
            )
        if not actual["open"]:
            out.rule(
                "LEDGER-STATUS", "status PARTIALLY_RESOLVED but no question is open; use RESOLVED", "$.status"
            )
    if status == "RESOLVED":
        if actual["open"]:
            out.rule(
                "LEDGER-STATUS", f"status RESOLVED but {actual['open']} question(s) are open", "$.status"
            )
        for index, question in enumerate(questions):
            if (
                isinstance(question, dict)
                and question.get("status") == "answered"
                and not question.get("applied_to")
            ):
                out.rule(
                    "LEDGER-RESOLVED-UNAPPLIED",
                    f"{question.get('id')} is answered but applied_to is empty; RESOLVED means every answer reached the packet",
                    f"$.questions[{index}].applied_to",
                )


def check_reference(label: str, reference: Any, repo_root: Path, out: Findings) -> Path | None:
    """Resolve a cited path; None when it is external, unresolvable or not a string."""
    if not isinstance(reference, str) or not reference:
        return None
    if is_external(reference):
        out.external.append(f"{label}: {reference[len(EXTERNAL_PREFIX) :]}")
        return None
    target = validate_pir.contained_path(reference, repo_root)
    if target is None:
        out.rule(
            "LEDGER-PATH-OUTSIDE",
            f"{reference} leaves the repository root, so it is not opened; a cited path is relative to the root "
            f"and stays inside it (prefix it '{EXTERNAL_PREFIX}' if it deliberately lives elsewhere)",
            label,
        )
        return None
    if not target.exists():
        out.rule(
            "LEDGER-PATH-UNRESOLVED",
            f"{reference} does not resolve (prefix it '{EXTERNAL_PREFIX}' if it deliberately lives elsewhere)",
            label,
        )
        return None
    return target


def validate_references(
    ledger: dict[str, Any], repo_root: Path, out: Findings
) -> tuple[Path | None, Path | None]:
    """Every cited path resolves or declares itself external. Returns (packet, interview) paths."""
    scope = validate_pir.mapping(ledger.get("scope"))
    for field in ("packet", "interview"):
        # The ledger is held against both files it names; an external one switches that off, so it is
        # refused rather than reported. The schema already calls them repo-relative.
        reference = scope.get(field)
        if isinstance(reference, str) and is_external(reference):
            out.rule(
                "LEDGER-SCOPE-EXTERNAL",
                f"scope.{field} is {reference!r}; a ledger is checked against the {field} it names, so it must "
                f"resolve here (record the ledger in the repository that holds the {field})",
                f"$.scope.{field}",
            )
    packet_path = check_reference("$.scope.packet", scope.get("packet"), repo_root, out)
    interview_path = check_reference("$.scope.interview", scope.get("interview"), repo_root, out)
    for index, artifact in enumerate(scope.get("source_artifacts") or []):
        if isinstance(artifact, dict):
            check_reference(f"$.scope.source_artifacts[{index}].path", artifact.get("path"), repo_root, out)
    for index, question in enumerate(ledger.get("questions") or []):
        if not isinstance(question, dict):
            continue
        source = question.get("answer_source")
        if isinstance(source, str) and (is_external(source) or looks_like_path(source)):
            check_reference(f"$.questions[{index}].answer_source", source, repo_root, out)
    return packet_path, interview_path


def validate_against_interview(ledger: dict[str, Any], interview_path: Path, out: Findings) -> None:
    try:
        interview = pir_interview.load_interview(interview_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        out.rule("LEDGER-INTERVIEW-MISMATCH", f"interview could not be loaded: {exc}", "$.scope.interview")
        return
    scope = validate_pir.mapping(ledger.get("scope"))
    for field in ("packet_id", "round"):
        if scope.get(field) != interview.get(field):
            out.rule(
                "LEDGER-INTERVIEW-MISMATCH",
                f"scope.{field} {scope.get(field)!r} differs from the interview's {interview.get(field)!r}",
                f"$.scope.{field}",
            )
    expected_id = str(interview.get("id", "")).rpartition("-I")
    if expected_id[1] and ledger.get("id") != f"{expected_id[0]}-L{expected_id[2]}":
        out.rule(
            "LEDGER-INTERVIEW-MISMATCH",
            f"ledger id {ledger.get('id')!r} does not pair with interview {interview.get('id')!r}",
            "$.id",
        )

    asked = pir_interview.question_index(interview)
    recorded: set[str] = set()
    for index, question in enumerate(ledger.get("questions") or []):
        if not isinstance(question, dict):
            continue
        qid = str(question.get("id"))
        recorded.add(qid)
        if qid not in asked:
            out.rule(
                "LEDGER-INTERVIEW-MISMATCH",
                f"{qid} is not a question the interview asked",
                f"$.questions[{index}]",
            )
            continue
        for field in ("rule", "section", "blocking"):
            if question.get(field) != asked[qid].get(field):
                out.rule(
                    "LEDGER-INTERVIEW-MISMATCH",
                    f"{qid}.{field} {question.get(field)!r} differs from the interview's {asked[qid].get(field)!r}",
                    f"$.questions[{index}].{field}",
                )
        if question.get("question") != asked[qid].get("ask"):  # the answer is to the question asked
            out.rule(
                "LEDGER-INTERVIEW-MISMATCH",
                f"{qid}.question is not the question the interview asked; record the answer against the asked text",
                f"$.questions[{index}].question",
            )
    for qid in sorted(set(asked) - recorded):
        out.rule(
            "LEDGER-INTERVIEW-UNCOVERED",
            f"interview question {qid} ({asked[qid]['rule']}) has no ledger entry",
            "$.questions",
        )


def validate_applied_to(ledger: dict[str, Any], packet_path: Path, out: Findings) -> None:
    try:
        packet = validate_pir.load_document(packet_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        out.rule("LEDGER-APPLIED-UNRESOLVED", f"packet could not be loaded: {exc}", "$.scope.packet")
        return
    for index, question in enumerate(ledger.get("questions") or []):
        if not isinstance(question, dict):
            continue
        for pointer_index, pointer in enumerate(question.get("applied_to") or []):
            if not isinstance(pointer, str):
                continue
            try:
                json_pointer.resolve(packet, pointer)
            except json_pointer.PointerError as exc:
                out.rule(
                    "LEDGER-APPLIED-UNRESOLVED",
                    f"{question.get('id')} claims its answer landed at {pointer}, which does not exist in the packet ({exc})",
                    f"$.questions[{index}].applied_to[{pointer_index}]",
                )


def validate_ledger(ledger: dict[str, Any], schema: dict[str, Any], repo_root: Path = REPO_ROOT) -> Findings:
    out = Findings()
    validate_schema(ledger, schema, out)
    validate_questions(ledger, out)
    validate_dates(ledger, schema, out)
    validate_counts_and_status(ledger, out)
    packet_path, interview_path = validate_references(ledger, repo_root, out)
    if interview_path is not None:
        validate_against_interview(ledger, interview_path, out)
    if packet_path is not None:
        validate_applied_to(ledger, packet_path, out)
    return out


# --------------------------------------------------------------------------------------- CLI


def validate_path(path: Path, schema: dict[str, Any], repo_root: Path) -> int:
    print(f"VALIDATING {path}", file=sys.stderr)
    try:
        ledger = validate_pir.load_document(path)
    except OSError as exc:
        # Missing, unreadable or a directory: nothing was validated, so this is exit 2, not a gap.
        print(f"ERROR {path} cannot be opened, so nothing was validated: {exc}", file=sys.stderr)
        return 2
    except (ValueError, yaml.YAMLError) as exc:
        print(f"FAIL {path}\n  - LEDGER-SCHEMA: ledger could not be read: {exc}", file=sys.stderr)
        return 1
    findings = validate_ledger(ledger, schema, repo_root)
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
        description="Validate PIR clarification ledgers against schema and semantic rules."
    )
    parser.add_argument("paths", nargs="+", help="Ledger files (.yaml, .yml or .json).")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA_PATH), help="Schema to enforce.")
    parser.add_argument(
        "--repo-root",
        default=str(Path.cwd()),
        help="Directory the ledger's cited paths are relative to. Defaults to the current directory: run "
        "from the root of the repository that holds pirs/, interviews/ and clarifications/.",
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
