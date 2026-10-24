#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""open_pir_ledger.py: open a clarification ledger from an interview.

The ledger starts with every interview question open, in the interview's order, carrying the
question's id, rule, section, blocking flag and text, so the answers are recorded against
exactly what was asked and tools/validate_pir_ledger.py can hold the two together. Counts are
computed, never typed. The ledger's packet defaults to the interview's packet; `--packet`
overrides it when the answers are being applied to a different file (the examples do this, so
the interview can be generated from a draft while the ledger points at the finished packet).

An interview with nothing to ask has no ledger: there are no questions to record answers to,
and a ledger with zero questions is refused by its own schema. That case exits 1 and says so.

`--check PATH` regenerates and compares with an existing ledger instead of writing.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_pir_interview
import pir_interview

LEDGER_SUFFIX_RE = "-I"


def ledger_id_for(interview_id: str) -> str:
    stem, sep, round_part = interview_id.rpartition(LEDGER_SUFFIX_RE)
    if not sep:
        raise pir_interview.InterviewError(f"interview id {interview_id!r} does not end in -Inn")
    return f"{stem}-L{round_part}"


def open_ledger(
    interview: dict[str, Any], interview_path: str, packet_path: str | None = None
) -> dict[str, Any]:
    if interview.get("status") == pir_interview.STATUS_NOTHING_TO_ASK:
        raise pir_interview.InterviewError(
            f"{interview_path} has nothing to ask; there is no ledger to open for a clean packet"
        )
    questions: list[dict[str, Any]] = []
    for section, question in pir_interview.iter_questions(interview):
        questions.append(
            {
                "id": question["id"],
                "rule": question["rule"],
                "section": section["key"],
                "blocking": bool(question["blocking"]),
                "question": question["ask"],
                "status": "open",
                "answer": None,
                "answered_by": None,
                "answered_at": None,
                "answer_source": None,
                "applied_to": [],
            }
        )
    return {
        "id": ledger_id_for(str(interview["id"])),
        "scope": {
            "packet": packet_path or interview["packet"],
            "packet_id": interview.get("packet_id"),
            "interview": interview_path,
            "round": interview["round"],
            "source_artifacts": [],
        },
        "status": "OPEN",
        "finding_counts": {
            "total": len(questions),
            "open": len(questions),
            "blocking_open": sum(1 for q in questions if q["blocking"]),
        },
        "questions": questions,
    }


def serialise(ledger: dict[str, Any]) -> str:
    return yaml.safe_dump(ledger, sort_keys=False, allow_unicode=True, width=100)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open a clarification ledger from a PIR owner interview.")
    parser.add_argument(
        "interview", help="The interview YAML; recorded repo-relative when inside the repository."
    )
    parser.add_argument(
        "--packet", help="The packet the answers will be applied to; defaults to the interview's."
    )
    parser.add_argument("--output", help="Write the ledger here. Defaults to stdout.")
    parser.add_argument(
        "--check", help="Regenerate and compare with this existing ledger; exit 1 with a diff if they differ."
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path.cwd()),
        help="Directory the ledger records its paths relative to. Defaults to the current directory: "
        "run from the root of the repository that holds pirs/ and interviews/.",
    )
    args = parser.parse_args(argv)
    if args.output and args.check:
        parser.error("--output and --check are exclusive")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root)
    try:
        interview = pir_interview.load_interview(Path(args.interview))
        ledger = open_ledger(
            interview,
            generate_pir_interview.repo_relative(Path(args.interview), repo_root),
            generate_pir_interview.repo_relative(Path(args.packet), repo_root) if args.packet else None,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: file not found: {exc.filename}", file=sys.stderr)
        return 1
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    text = serialise(ledger)

    if args.check:
        expected_path = Path(args.check)
        if not expected_path.is_file():
            print(f"ERROR: --check target {expected_path} does not exist", file=sys.stderr)
            return 1
        current = expected_path.read_text(encoding="utf-8")
        if current == text:
            print(f"PASS {expected_path} is current", file=sys.stderr)
            return 0
        sys.stderr.write(
            "".join(
                difflib.unified_diff(
                    current.splitlines(keepends=True),
                    text.splitlines(keepends=True),
                    fromfile=str(expected_path),
                    tofile="regenerated",
                )
            )
        )
        print(f"FAIL {expected_path} is stale; regenerate it with --output", file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    counts = ledger["finding_counts"]
    print(
        f"opened {ledger['id']}: {counts['total']} question(s), {counts['blocking_open']} blocking",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
