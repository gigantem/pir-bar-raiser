#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""generate_pir_interview.py: turn a gap report into the owner's question program.

Input is a PIR packet and the findings tools/validate_pir.py raised against it, either run
here (`--packet`) or read from a gap report it wrote earlier (`--gap-report`, with `--packet`
naming which entry when the report covers several). Both routes produce the same interview.

Output is an interview document (schemas/pir-interview.schema.json): the findings grouped by
template section in the deck's writing order (timeline first, summary last), each finding
paired with the question that closes it from catalogs/pir-rule-questions.yaml, and each
section carrying its expectation, common mistakes, example and prompt from
catalogs/pir-section-expectations.yaml. Nothing the tool cannot derive is guessed: the PIR
owner is read from the packet or left as HUMAN_CONFIRM_PIR_OWNER, and the facilitator is
always HUMAN_CONFIRM_FACILITATOR.

A packet with no findings yields an interview whose status is `nothing_to_ask`, written and
reported rather than silently omitted, so "no interview file" can never mean "nobody checked".

`--check PATH` regenerates and compares with an existing interview instead of writing, exiting
1 with a diff when they differ, so an interview on disk can be held to its packet.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pir_interview
import validate_pir

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATED_BY = "tools/generate_pir_interview.py"
OWNER_PLACEHOLDER = "HUMAN_CONFIRM_PIR_OWNER"
FACILITATOR_PLACEHOLDER = "HUMAN_CONFIRM_FACILITATOR"
PACKET_STATUSES = ("draft", "in_team_review", "in_go_review", "published")


def repo_relative(path: Path, repo_root: Path) -> str:
    """A path as the interview records it: relative to `repo_root` when inside it, else as given.

    `repo_root` is the root of the repository that holds the PIR (pirs/, interviews/, clarifications/),
    which is the current directory on the command line. It is not where the tools are installed:
    the two coincide when the tools sit at that root and differ when they run from an installed
    extension.
    """
    resolved = path.resolve()
    try:
        return resolved.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def default_instructions() -> list[str]:
    return [
        "Work through the sections in the order given: it is the deck's writing order, so the "
        "timeline and metrics are settled before the analysis that depends on them, and the "
        "summary is written last.",
        "Answer blocking questions first; the packet cannot pass the gate while any is open. "
        "Advisory questions are the deck's softer guidance and may be answered, deferred with an "
        "owner and date, or waived with a reason.",
        "Every answer comes with its evidence (a log query, a dashboard panel, a ticket, a record), "
        "and the person or team who gave it. Nothing is invented to make the packet validate.",
        "The PIR stays blameless: when an answer names a person, restate it as the process, design "
        "or tooling gap.",
        "Replace every HUMAN_CONFIRM placeholder before using this interview with the owner.",
    ]


def default_response_template() -> dict[str, Any]:
    return {
        "title": "Response format for the PIR owner",
        "fields": [
            {"label": "Question ID", "guidance": "The Q-nnn id exactly as shown."},
            {
                "label": "Answer",
                "guidance": "The fact, number, sentence or structure asked for, in the answer shape given.",
            },
            {
                "label": "Evidence",
                "guidance": "Where the answer can be checked: a query, panel, ticket, record or document.",
            },
            {
                "label": "Answered by",
                "guidance": "The person or team who gave the answer, never a role placeholder.",
            },
            {"label": "Date", "guidance": "When the answer was given, YYYY-MM-DD."},
            {
                "label": "Deferred or waived",
                "guidance": "If not answered: deferred to whom and by when, or waived for what reason.",
            },
        ],
    }


def default_after_answers() -> list[str]:
    return [
        "Open a clarification ledger from this interview (tools/open_pir_ledger.py) and record "
        "each answer in it: the answer, its evidence, who gave it and when.",
        "Transcribe each answer into the packet and record where it landed in the ledger's "
        "applied_to (JSON pointers into the packet).",
        "Re-run tools/validate_pir.py on the packet. If findings remain, generate the next round "
        "of this interview with --round incremented; otherwise the packet is ready for review.",
    ]


# ---------------------------------------------------------------------------------- findings


def findings_from_validator(packet: dict[str, Any]) -> list[dict[str, Any]]:
    schema = validate_pir.load_schema()
    findings = validate_pir.validate_packet(
        packet, schema, validate_pir.blame_patterns(), validate_pir.vague_action_patterns()
    )
    return [
        {"rule": f.rule, "severity": f.severity, "section": f.section, "message": f.message, "path": f.path}
        for f in findings.items
    ]


#: What a rule id looks like. A gap report is data, so a "rule" that is not shaped like one is never
#: echoed back into an error message the agent will read.
RULE_ID = re.compile(r"^[A-Z]+(?:-[A-Z0-9]+)+$")


def _finding_key(finding: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (finding["rule"], finding["severity"], finding["section"], finding["message"], finding["path"])


def findings_from_gap_report(report_path: Path, packet_path: Path) -> list[dict[str, Any]]:
    """The findings of `packet_path`, once its gap report is shown to say what the validator says now.

    A gap report is an input someone else wrote, and the interview puts its text in front of the
    owner and the next agent. So the packet is validated afresh and the report must match that run
    finding for finding (rule, severity, section, message, path); a stale or altered report is refused,
    and what is returned is the validator's own findings, never the report's text."""
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise pir_interview.InterviewError(f"{report_path}: not valid JSON ({exc})") from exc
    entries = report.get("packets") if isinstance(report, dict) else None
    if not isinstance(entries, list):
        raise pir_interview.InterviewError(f"{report_path}: not a gap report (no 'packets' list)")
    wanted = packet_path.resolve()
    matches = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and isinstance(entry.get("packet"), str)
        and Path(entry["packet"]).resolve() == wanted
    ]
    if not matches:
        listed = ", ".join(str(e.get("packet")) for e in entries if isinstance(e, dict)) or "nothing"
        raise pir_interview.InterviewError(
            f"{report_path} has no entry for {packet_path} (it covers: {listed})"
        )
    if len(matches) > 1:
        raise pir_interview.InterviewError(f"{report_path} has {len(matches)} entries for {packet_path}")
    findings = matches[0].get("findings")
    if not isinstance(findings, list):
        raise pir_interview.InterviewError(f"{report_path}: entry for {packet_path} has no findings list")
    normalised: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            raise pir_interview.InterviewError(f"{report_path}: a finding is not a mapping")
        for field in ("rule", "severity", "section", "message"):
            if not isinstance(finding.get(field), str):
                raise pir_interview.InterviewError(f"{report_path}: a finding lacks '{field}'")
        normalised.append(
            {
                "rule": finding["rule"],
                "severity": finding["severity"],
                "section": finding["section"],
                "message": finding["message"],
                "path": str(finding.get("path") or ""),
            }
        )
    fresh = findings_from_validator(validate_pir.load_document(packet_path))
    reported_keys = Counter(_finding_key(f) for f in normalised)
    fresh_keys = Counter(_finding_key(f) for f in fresh)
    if reported_keys != fresh_keys:
        only_reported = sorted(
            {key[0] if RULE_ID.match(key[0]) else "<not a rule id>" for key in reported_keys - fresh_keys}
        )
        only_fresh = sorted({key[0] for key in fresh_keys - reported_keys})
        raise pir_interview.InterviewError(
            f"{report_path} does not match a fresh validation of {packet_path}: it reports "
            f"{sum(reported_keys.values())} finding(s) and the validator finds {sum(fresh_keys.values())}; "
            f"only in the report: {', '.join(only_reported) or 'none'}; only in the fresh run: "
            f"{', '.join(only_fresh) or 'none'}. Regenerate it with validate_pir.py --gap-report, or omit "
            "--gap-report and let the generator validate the packet."
        )
    return fresh


# ---------------------------------------------------------------------------------- building


def owner_of(packet: dict[str, Any]) -> str:
    control = packet.get("document_control")
    owner = control.get("pir_owner") if isinstance(control, dict) else None
    if isinstance(owner, str) and owner.strip() and not validate_pir.is_placeholder_owner(owner):
        return owner.strip()
    return OWNER_PLACEHOLDER


def packet_status_of(packet: dict[str, Any]) -> str:
    status = packet.get("status")
    return status if isinstance(status, str) and status in PACKET_STATUSES else "unknown"


def packet_id_pattern() -> re.Pattern[str]:
    """The packet schema's own id pattern, so there is one definition of a valid packet id."""
    pattern = validate_pir.load_schema()["properties"]["id"]["pattern"]
    return re.compile(str(pattern))


def interview_stem(packet: dict[str, Any], packet_path: Path) -> tuple[str | None, str]:
    """(packet id or None, the stem the interview id is built from)."""
    packet_id = packet.get("id")
    if isinstance(packet_id, str) and packet_id_pattern().fullmatch(packet_id):
        return packet_id, packet_id
    return None, packet_path.stem


def specific_path(path: str) -> str:
    """The finding's path when it points somewhere; the document root ('$') names nothing useful."""
    return path if path and path != "$" else ""


def build_interview(
    packet: dict[str, Any],
    packet_path: Path,
    findings: list[dict[str, Any]],
    round_number: int,
    gap_report_path: Path | None = None,
    sections: dict[str, dict[str, Any]] | None = None,
    rule_questions: dict[str, dict[str, str]] | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """The interview document for `findings`, grouped by section in writing order.

    Raises InterviewError for a finding whose rule has no question or whose section has no
    catalog entry: a gap the owner cannot be asked about is a defect in the catalogs, not
    something to skip.
    """
    sections = sections or pir_interview.load_section_catalog()
    rule_questions = rule_questions or pir_interview.load_rule_questions()

    grouped: dict[str, list[dict[str, Any]]] = {}
    for finding in findings:
        rule = finding["rule"]
        if rule not in validate_pir.RULES:
            raise pir_interview.InterviewError(f"finding cites {rule}, which the validator does not define")
        if rule not in rule_questions:
            raise pir_interview.InterviewError(
                f"{rule} has no entry in {pir_interview.RULE_QUESTIONS_PATH.name}"
            )
        home = validate_pir.RULES[rule][0]
        if home not in sections:
            raise pir_interview.InterviewError(
                f"section {home} has no entry in {pir_interview.SECTIONS_PATH.name}"
            )
        grouped.setdefault(home, []).append(finding)

    ordered_keys = sorted(grouped, key=lambda key: int(sections[key]["writing_order"]))
    built_sections: list[dict[str, Any]] = []
    next_id = 1
    for key in ordered_keys:
        entry = sections[key]
        questions: list[dict[str, Any]] = []
        for finding in grouped[key]:
            question_text = rule_questions[finding["rule"]]
            questions.append(
                {
                    "id": f"Q-{next_id:03d}",
                    "rule": finding["rule"],
                    "severity": finding["severity"],
                    "blocking": finding["severity"] == validate_pir.ERROR,
                    "path": finding["path"],
                    "finding": finding["message"],
                    "ask": question_text["ask"],
                    "answer_shape": question_text["answer_shape"],
                    "applies_to": specific_path(finding["path"]) or question_text["applies_to"],
                }
            )
            next_id += 1
        built_sections.append(
            {
                "key": key,
                "title": str(entry["title"]),
                "template_section": str(entry["template_section"]),
                "writing_order": int(entry["writing_order"]),
                "expectation": str(entry["expectation"]).strip(),
                "common_mistakes": [str(item) for item in entry.get("common_mistakes") or []],
                "example": str(entry["example"]).strip(),
                "interview_prompt": str(entry["interview_prompt"]).strip(),
                "questions": questions,
            }
        )

    packet_id, stem = interview_stem(packet, packet_path)
    source_artifacts = [{"path": repo_relative(packet_path, repo_root), "role": "pir-packet"}]
    if gap_report_path is not None:
        source_artifacts.append({"path": repo_relative(gap_report_path, repo_root), "role": "gap-report"})
    source_artifacts.append(
        {"path": repo_relative(pir_interview.SECTIONS_PATH, repo_root), "role": "section-expectations"}
    )
    source_artifacts.append(
        {"path": repo_relative(pir_interview.RULE_QUESTIONS_PATH, repo_root), "role": "rule-questions"}
    )

    interview: dict[str, Any] = {
        "id": f"{stem}-I{round_number:02d}",
        "packet": repo_relative(packet_path, repo_root),
        "packet_id": packet_id,
        "packet_status": packet_status_of(packet),
        "round": round_number,
        "status": pir_interview.STATUS_ANSWERS_REQUIRED
        if built_sections
        else pir_interview.STATUS_NOTHING_TO_ASK,
        "generated_by": GENERATED_BY,
        "owner": owner_of(packet),
        "facilitator": FACILITATOR_PLACEHOLDER,
        "source_artifacts": source_artifacts,
        "instructions": default_instructions(),
        "counts": {},
        "sections": built_sections,
        "response_template": default_response_template(),
        "after_answers": default_after_answers(),
    }
    interview["counts"] = pir_interview.expected_counts(interview)
    return interview


def serialise(interview: dict[str, Any]) -> str:
    return yaml.safe_dump(interview, sort_keys=False, allow_unicode=True, width=100)


# --------------------------------------------------------------------------------------- CLI


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the PIR owner interview from a packet's gap report."
    )
    parser.add_argument("--packet", required=True, help="The PIR packet (.yaml/.yml/.json).")
    parser.add_argument(
        "--gap-report",
        help="Read findings from this gap report (written by validate_pir.py --gap-report) instead of validating here.",
    )
    parser.add_argument("--round", type=int, default=1, help="Interview round; the first is 1.")
    parser.add_argument("--output", help="Write the interview here. Defaults to stdout.")
    parser.add_argument(
        "--check",
        help="Regenerate and compare with this existing interview; exit 1 with a diff if they differ.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path.cwd()),
        help="Directory the interview records its paths relative to. Defaults to the current directory: "
        "run from the root of the repository that holds pirs/.",
    )
    args = parser.parse_args(argv)
    if args.round < 1:
        parser.error("--round must be 1 or more")
    if args.output and args.check:
        parser.error("--output and --check are exclusive")
    return args


def generate(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    packet_path = Path(args.packet)
    packet = validate_pir.load_document(packet_path)
    if args.gap_report:
        gap_report_path = Path(args.gap_report)
        findings = findings_from_gap_report(gap_report_path, packet_path)
    else:
        gap_report_path = None
        findings = findings_from_validator(packet)
    interview = build_interview(
        packet, packet_path, findings, args.round, gap_report_path, repo_root=Path(args.repo_root)
    )
    errors = pir_interview.validate_interview(interview)
    if errors:
        joined = "\n  - ".join(errors)
        raise pir_interview.InterviewError(
            f"generated interview is not valid, refusing to write it:\n  - {joined}"
        )
    return interview, serialise(interview)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        interview, text = generate(args)
    except FileNotFoundError as exc:
        print(f"ERROR: file not found: {exc.filename}", file=sys.stderr)
        return 1
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.check:
        expected_path = Path(args.check)
        if not expected_path.is_file():
            print(f"ERROR: --check target {expected_path} does not exist", file=sys.stderr)
            return 1
        current = expected_path.read_text(encoding="utf-8")
        if current == text:
            print(
                f"PASS {expected_path} is current ({interview['counts']['questions']} question(s))",
                file=sys.stderr,
            )
            return 0
        diff = difflib.unified_diff(
            current.splitlines(keepends=True),
            text.splitlines(keepends=True),
            fromfile=str(expected_path),
            tofile="regenerated",
        )
        sys.stderr.write("".join(diff))
        print(f"FAIL {expected_path} is stale; regenerate it with --output", file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    counts = interview["counts"]
    print(
        f"{interview['status']}: {counts['questions']} question(s), {counts['blocking']} blocking, "
        f"across {counts['sections']} section(s)" + (f" -> {args.output}" if args.output else ""),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
