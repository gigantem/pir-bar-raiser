#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""validate_catalogs.py: the catalogs, the schema and the validator describe one rule set.

Three contracts, each enforced here rather than asserted in prose:

1. **Lexicons** (catalogs/blame-lexicon.yaml, catalogs/vague-action-lexicon.yaml) are
   non-empty, every term carries the fields the validator and the interview read, every
   blame pattern compiles, and a vague term's optional `forms` are words and its optional
   `satisfied_by` compiles.
2. **Section expectations** (catalogs/pir-section-expectations.yaml): section ids are unique,
   writing orders are unique, every entry carries the guidance fields the interview renders,
   and every section is a top-level key of the packet schema (plus `cross_cutting`).
3. **Rule homes**: the set of rule ids listed across all sections equals the validator's
   RULES table, each listed once, under the section the validator assigns it. A rule without
   a home has no guidance to attach to its finding; a home listing a rule that does not fire
   is documentation of nothing.
4. **Rule questions** (catalogs/pir-rule-questions.yaml): exactly the validator's rules, once
   each, every entry carrying `ask`, `answer_shape` and `applies_to`. A rule with no question
   is a gap the owner cannot be asked about; a question for a rule that does not fire is never
   asked.
5. **Principles** (catalogs/pir-principles.yaml, the rendered template's Appendix B): a preamble
   and titled, non-empty sections with unique ids.

Exit 0 when all five hold; 1 otherwise, naming each defect.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_pir

REPO_ROOT = Path(__file__).resolve().parent.parent
SECTIONS_PATH = REPO_ROOT / "catalogs" / "pir-section-expectations.yaml"
RULE_QUESTIONS_PATH = REPO_ROOT / "catalogs" / "pir-rule-questions.yaml"
SCHEMA_PATH = REPO_ROOT / "schemas" / "pir-packet.schema.json"
QUESTION_FIELDS = ("ask", "answer_shape", "applies_to")

SECTION_FIELDS = (
    "id",
    "title",
    "template_section",
    "writing_order",
    "expectation",
    "common_mistakes",
    "example",
    "interview_prompt",
    "template_guidance",
    "rules",
)
PRINCIPLES_PATH = REPO_ROOT / "catalogs" / "pir-principles.yaml"
BLAME_FIELDS = ("term", "pattern", "severity", "why_it_matters", "remediation")
VAGUE_FIELDS = ("term", "why_it_matters", "remediation")
#: Schema keys that are not template sections and so need no catalog entry.
NOT_SECTIONS = frozenset({"id", "status", "key_timings"})


def check_lexicon(path: Path, fields: tuple[str, ...], compile_patterns: bool) -> list[str]:
    problems: list[str] = []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    terms = data.get("terms") if isinstance(data, dict) else None
    if not isinstance(terms, list) or not terms:
        return [f"{path.name}: no terms"]
    seen: set[str] = set()
    for index, term in enumerate(terms):
        if not isinstance(term, dict):
            problems.append(f"{path.name}: terms[{index}] is not a mapping")
            continue
        for field in fields:
            if not isinstance(term.get(field), str) or not term[field].strip():
                problems.append(f"{path.name}: terms[{index}] is missing '{field}'")
        name = str(term.get("term", "")).lower()
        if name in seen:
            problems.append(f"{path.name}: term '{name}' is listed twice")
        seen.add(name)
        if compile_patterns and isinstance(term.get("pattern"), str):
            try:
                re.compile(term["pattern"])
            except re.error as exc:
                problems.append(f"{path.name}: pattern for '{name}' does not compile: {exc}")
        forms = term.get("forms")
        if forms is not None and (
            not isinstance(forms, list)
            or not forms
            or not all(isinstance(f, str) and f.strip() for f in forms)
        ):
            problems.append(f"{path.name}: forms for '{name}' must be a non-empty list of words")
        satisfied = term.get("satisfied_by")
        if satisfied is not None:
            if not isinstance(satisfied, str) or not satisfied.strip():
                problems.append(f"{path.name}: satisfied_by for '{name}' must be a regular expression")
            else:
                try:
                    re.compile(satisfied)
                except re.error as exc:
                    problems.append(f"{path.name}: satisfied_by for '{name}' does not compile: {exc}")
    return problems


def check_sections() -> list[str]:
    problems: list[str] = []
    data = yaml.safe_load(SECTIONS_PATH.read_text(encoding="utf-8"))
    sections = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(sections, list) or not sections:
        return [f"{SECTIONS_PATH.name}: no sections"]
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    schema_sections = set(schema["properties"]) - NOT_SECTIONS

    ids: set[str] = set()
    orders: set[int] = set()
    homes: dict[str, str] = {}
    for section in sections:
        if not isinstance(section, dict):
            problems.append("a section entry is not a mapping")
            continue
        for field in SECTION_FIELDS:
            if field not in section:
                problems.append(f"section {section.get('id', '<no id>')} is missing '{field}'")
        section_id = str(section.get("id"))
        if section_id in ids:
            problems.append(f"section id {section_id} is listed twice")
        ids.add(section_id)
        order = section.get("writing_order")
        if isinstance(order, int):
            if order in orders:
                problems.append(f"writing_order {order} is used twice")
            orders.add(order)
        if section_id != "cross_cutting" and section_id not in schema_sections:
            problems.append(f"section {section_id} is not a top-level key of the packet schema")
        for rule_id in section.get("rules") or []:
            if rule_id in homes:
                problems.append(f"{rule_id} is listed under both {homes[rule_id]} and {section_id}")
            homes[rule_id] = section_id

    for schema_section in sorted(schema_sections - ids):
        problems.append(f"schema section '{schema_section}' has no catalog entry")
    for rule_id, section_id in sorted(homes.items()):
        if rule_id not in validate_pir.RULES:
            problems.append(
                f"catalog lists {rule_id} under {section_id} but the validator does not define it"
            )
        elif validate_pir.RULES[rule_id][0] != section_id:
            problems.append(
                f"catalog lists {rule_id} under {section_id} but the validator assigns it to {validate_pir.RULES[rule_id][0]}"
            )
    for rule_id in sorted(set(validate_pir.RULES) - set(homes)):
        problems.append(f"validator rule {rule_id} has no home in the section catalog")
    return problems


def check_rule_questions() -> list[str]:
    problems: list[str] = []
    data = yaml.safe_load(RULE_QUESTIONS_PATH.read_text(encoding="utf-8"))
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list) or not rules:
        return [f"{RULE_QUESTIONS_PATH.name}: no rules"]
    seen: set[str] = set()
    for index, entry in enumerate(rules):
        if not isinstance(entry, dict):
            problems.append(f"{RULE_QUESTIONS_PATH.name}: rules[{index}] is not a mapping")
            continue
        rule_id = str(entry.get("id"))
        if rule_id in seen:
            problems.append(f"{RULE_QUESTIONS_PATH.name}: {rule_id} has two questions")
        seen.add(rule_id)
        if rule_id not in validate_pir.RULES:
            problems.append(f"{RULE_QUESTIONS_PATH.name}: {rule_id} is not a validator rule")
        for field in QUESTION_FIELDS:
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                problems.append(f"{RULE_QUESTIONS_PATH.name}: {rule_id} is missing '{field}'")
    for rule_id in sorted(set(validate_pir.RULES) - seen):
        problems.append(f"validator rule {rule_id} has no question in {RULE_QUESTIONS_PATH.name}")
    return problems


def check_principles() -> list[str]:
    """Appendix B has a preamble and non-empty titled sections with unique ids."""
    problems: list[str] = []
    data = yaml.safe_load(PRINCIPLES_PATH.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("preamble"), str)
        or not data["preamble"].strip()
    ):
        problems.append(f"{PRINCIPLES_PATH.name}: no preamble")
    sections = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(sections, list) or not sections:
        return [*problems, f"{PRINCIPLES_PATH.name}: no sections"]
    seen: set[str] = set()
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            problems.append(f"{PRINCIPLES_PATH.name}: sections[{index}] is not a mapping")
            continue
        sid = str(section.get("id"))
        if sid in seen:
            problems.append(f"{PRINCIPLES_PATH.name}: section {sid} is listed twice")
        seen.add(sid)
        if not isinstance(section.get("title"), str) or not section["title"].strip():
            problems.append(f"{PRINCIPLES_PATH.name}: section {sid} has no title")
        points = section.get("points")
        if (
            not isinstance(points, list)
            or not points
            or not all(isinstance(x, str) and x.strip() for x in points)
        ):
            problems.append(f"{PRINCIPLES_PATH.name}: section {sid} has no points, or an empty one")
    return problems


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check that the lexicons, the section catalog, the rule questions and the principles agree with the schema and the validators. Takes no arguments."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parse_args(argv if argv is not None else [])
    problems = []
    problems += check_lexicon(validate_pir.BLAME_LEXICON_PATH, BLAME_FIELDS, compile_patterns=True)
    problems += check_lexicon(validate_pir.VAGUE_ACTION_LEXICON_PATH, VAGUE_FIELDS, compile_patterns=False)
    problems += check_sections()
    problems += check_rule_questions()
    problems += check_principles()
    if problems:
        print(f"FAIL: {len(problems)} catalog defect(s):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(
        f"PASS: lexicons, section catalog, rule questions and principles agree with the schema and all "
        f"{len(validate_pir.RULES)} validator rules"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
