#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""render_pir_interview.py: print a PIR owner interview as markdown.

The interview YAML is the contract; this is the view a person reads in the room. Sections
appear in writing order, each with the guidance a reader needs before the questions (what good
looks like, the common mistakes, a worked example, the prompt), then the questions with the
finding they close, the question, the answer shape and where the answer lands.

The input is validated first (schema and semantics via tools/pir_interview.py); an invalid
interview is refused, not rendered around. Remaining HUMAN_CONFIRM placeholders are counted
and reported on stderr; `--no-placeholders` makes them a failure, for the moment the interview
is about to be used with the owner.

`--check PATH` renders and compares with an existing markdown file instead of writing.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pir_interview

NO_ITEMS = "- none"


def render_list(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items] if items else [NO_ITEMS]


def render_order_table(interview: dict[str, Any]) -> list[str]:
    rows = [
        "| Order | Template section | Questions | Blocking |",
        "| --- | --- | --- | --- |",
    ]
    for section in interview.get("sections") or []:
        questions = section.get("questions") or []
        blocking = sum(1 for q in questions if q.get("blocking"))
        rows.append(
            f"| {section['writing_order']} | {section['template_section']}. {section['title']} "
            f"| {len(questions)} | {blocking} |"
        )
    return rows


def render_question(question: dict[str, Any]) -> list[str]:
    kind = "blocking" if question.get("blocking") else "advisory"
    where = f" at `{question['path']}`" if question.get("path") else ""
    return [
        f"#### {question['id']} ({kind}, `{question['rule']}`{where})",
        "",
        f"- **Finding:** {question['finding']}",
        f"- **Question:** {question['ask']}",
        f"- **A complete answer:** {question['answer_shape']}",
        f"- **Goes into:** `{question['applies_to']}`",
        "",
    ]


def render_section(section: dict[str, Any]) -> list[str]:
    lines = [
        f"### {section['template_section']}. {section['title']} (writing order {section['writing_order']})",
        "",
        f"**What good looks like.** {section['expectation']}",
        "",
        "**Common mistakes.**",
        "",
        *render_list([str(item) for item in section.get("common_mistakes") or []]),
        "",
        f"**Example.** {section['example']}",
        "",
        f"**Ask.** {section['interview_prompt']}",
        "",
    ]
    for question in section.get("questions") or []:
        lines.extend(render_question(question))
    return lines


def render_response_template(interview: dict[str, Any]) -> list[str]:
    template = interview["response_template"]
    lines = [f"## {template['title']}", "", "One block per question:", "", "```text"]
    for field in template["fields"]:
        lines.append(f"{field['label']}: <{field['guidance']}>")
    lines.extend(["```", ""])
    return lines


def render_markdown(interview: dict[str, Any]) -> str:
    counts = interview["counts"]
    title_id = interview.get("packet_id") or interview["packet"]
    lines = [
        f"# PIR owner interview: {title_id}, round {interview['round']}",
        "",
        "## Outcome",
        "",
        f"- Status: `{interview['status']}`",
        f"- Packet: `{interview['packet']}` (status `{interview['packet_status']}`)",
        f"- Questions: {counts['questions']} ({counts['blocking']} blocking, {counts['advisory']} advisory) "
        f"across {counts['sections']} section(s)",
        f"- PIR owner: {interview['owner']}",
        f"- Facilitator: {interview['facilitator']}",
        "",
        "## Source artifacts",
        "",
        *render_list([f"`{a['path']}` ({a['role']})" for a in interview["source_artifacts"]]),
        "",
        "## How to use this interview",
        "",
        *render_list(list(interview["instructions"])),
        "",
    ]
    if interview["status"] == pir_interview.STATUS_NOTHING_TO_ASK:
        lines.extend(
            [
                "## Nothing to ask",
                "",
                "The validator raised no findings against this packet. There is no gap to close by "
                "interview; the packet is ready for review.",
                "",
            ]
        )
    else:
        lines.extend(["## Order of work", "", *render_order_table(interview), "", "## Sections", ""])
        for section in interview["sections"]:
            lines.extend(render_section(section))
    lines.extend(render_response_template(interview))
    lines.extend(
        [
            "## After the answers arrive",
            "",
            *[f"{i}. {s}" for i, s in enumerate(interview["after_answers"], 1)],
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a PIR owner interview as markdown.")
    parser.add_argument("interview", help="The interview YAML or JSON.")
    parser.add_argument("--output", help="Write the markdown here. Defaults to stdout.")
    parser.add_argument(
        "--check", help="Render and compare with this existing markdown; exit 1 with a diff if they differ."
    )
    parser.add_argument(
        "--no-placeholders",
        action="store_true",
        help="Fail if any HUMAN_CONFIRM placeholder remains; use before the interview goes to the owner.",
    )
    args = parser.parse_args(argv)
    if args.output and args.check:
        parser.error("--output and --check are exclusive")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        interview = pir_interview.load_interview(Path(args.interview))
    except FileNotFoundError as exc:
        print(f"ERROR: file not found: {exc.filename}", file=sys.stderr)
        return 1
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    remaining = pir_interview.placeholders(interview)
    for item in remaining:
        print(f"placeholder: {item}", file=sys.stderr)
    if remaining and args.no_placeholders:
        print(
            f"ERROR: {len(remaining)} HUMAN_CONFIRM placeholder(s) remain; replace them before use",
            file=sys.stderr,
        )
        return 1

    text = render_markdown(interview)
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
                    tofile="re-rendered",
                )
            )
        )
        print(f"FAIL {expected_path} is stale; re-render it with --output", file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
