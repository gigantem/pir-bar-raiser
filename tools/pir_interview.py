#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""pir_interview.py: load, validate and walk PIR owner interviews.

The library behind tools/generate_pir_interview.py (which builds one), tools/render_pir_interview.py
(which prints one), tools/open_pir_ledger.py (which opens a ledger from one) and
tools/validate_pir_ledger.py (which checks a ledger against one). It owns the interview's
semantics, the things the schema cannot say:

* question ids are Q-001, Q-002, ... in document order, with no gaps;
* sections are unique and in strictly ascending writing order;
* every question's rule is one the validator defines, filed under the section the validator
  assigns it, and `blocking` is exactly "the finding is an error";
* `counts` equals what the document contains;
* `nothing_to_ask` means zero questions, and `answers_required` means at least one.

It also finds the HUMAN_CONFIRM placeholders the generator leaves for facts only a person
knows, so a renderer can report them and a caller can refuse to proceed with them in place.

This module is a library. It has no CLI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_pir

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA_PATH = REPO_ROOT / "schemas" / "pir-interview.schema.json"
SECTIONS_PATH = REPO_ROOT / "catalogs" / "pir-section-expectations.yaml"
RULE_QUESTIONS_PATH = REPO_ROOT / "catalogs" / "pir-rule-questions.yaml"
HUMAN_CONFIRM = "HUMAN_CONFIRM"
STATUS_ANSWERS_REQUIRED = "answers_required"
STATUS_NOTHING_TO_ASK = "nothing_to_ask"


class InterviewError(ValueError):
    """An interview or catalog that cannot be used, with the reason."""


# ------------------------------------------------------------------------------------- loading


def load_document(path: Path) -> dict[str, Any]:
    """A YAML or JSON mapping; anything else is an error naming the file."""
    try:
        data = validate_pir.parse_document(path, yaml_for_any_suffix=True)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise InterviewError(f"{path}: not valid YAML/JSON ({exc})") from exc
    except ValueError as exc:
        raise InterviewError(str(exc)) from exc
    if not isinstance(data, dict):
        raise InterviewError(f"{path}: root must be a mapping")
    return data


def load_schema(path: Path = DEFAULT_SCHEMA_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        schema = json.load(handle)
    if not isinstance(schema, dict):
        raise InterviewError(f"{path}: schema root must be a JSON object")
    return schema


def load_section_catalog(path: Path = SECTIONS_PATH) -> dict[str, dict[str, Any]]:
    """Section entries keyed by id, in catalog order. Fails on a catalog with no sections."""
    data = load_document(path)
    sections = data.get("sections")
    if not isinstance(sections, list) or not sections:
        raise InterviewError(f"{path}: no sections")
    by_id: dict[str, dict[str, Any]] = {}
    for entry in sections:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise InterviewError(f"{path}: a section entry has no string id")
        by_id[entry["id"]] = entry
    return by_id


def load_rule_questions(path: Path = RULE_QUESTIONS_PATH) -> dict[str, dict[str, str]]:
    """Rule-question entries keyed by rule id. Fails on a missing field or a duplicate id."""
    data = load_document(path)
    rules = data.get("rules")
    if not isinstance(rules, list) or not rules:
        raise InterviewError(f"{path}: no rules")
    by_id: dict[str, dict[str, str]] = {}
    for entry in rules:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise InterviewError(f"{path}: a rule entry has no string id")
        rule_id = entry["id"]
        if rule_id in by_id:
            raise InterviewError(f"{path}: {rule_id} is listed twice")
        for field in ("ask", "answer_shape", "applies_to"):
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                raise InterviewError(f"{path}: {rule_id} is missing '{field}'")
        by_id[rule_id] = {field: str(entry[field]).strip() for field in ("ask", "answer_shape", "applies_to")}
    return by_id


# ---------------------------------------------------------------------------------- validation


def validate_schema(interview: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(schema)
    errors: list[str] = []
    for error in sorted(validator.iter_errors(interview), key=lambda item: list(item.path)):
        errors.append(
            f"schema violation at {validate_pir.format_error_path(list(error.path))}: {error.message}"
        )
    return errors


def iter_questions(interview: dict[str, Any]):
    """Every (section, question) pair in document order."""
    for section in interview.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for question in section.get("questions") or []:
            if isinstance(question, dict):
                yield section, question


def question_index(interview: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Questions keyed by id, each with its section key added under 'section'."""
    index: dict[str, dict[str, Any]] = {}
    for section, question in iter_questions(interview):
        qid = str(question.get("id"))
        index[qid] = {**question, "section": section.get("key")}
    return index


def expected_counts(interview: dict[str, Any]) -> dict[str, int]:
    questions = [q for _, q in iter_questions(interview)]
    return {
        "questions": len(questions),
        "blocking": sum(1 for q in questions if q.get("severity") == validate_pir.ERROR),
        "advisory": sum(1 for q in questions if q.get("severity") == validate_pir.WARNING),
        "sections": len(interview.get("sections") or []),
    }


def validate_semantics(interview: dict[str, Any]) -> list[str]:
    """The rules the schema cannot express. Returns one message per defect."""
    errors: list[str] = []
    sections = interview.get("sections") or []

    seen_keys: set[str] = set()
    last_order: int | None = None
    for section in sections:
        if not isinstance(section, dict):
            continue
        key = str(section.get("key"))
        if key in seen_keys:
            errors.append(f"section {key} appears twice")
        seen_keys.add(key)
        order = section.get("writing_order")
        if isinstance(order, int):
            if last_order is not None and order <= last_order:
                errors.append(f"section {key} (writing_order {order}) is out of writing order")
            last_order = order

    expected_id = 1
    for section, question in iter_questions(interview):
        qid = str(question.get("id"))
        if qid != f"Q-{expected_id:03d}":
            errors.append(f"{qid} is out of sequence; expected Q-{expected_id:03d}")
        expected_id += 1
        rule = str(question.get("rule"))
        if rule not in validate_pir.RULES:
            errors.append(f"{qid} cites {rule}, which the validator does not define")
        else:
            home = validate_pir.RULES[rule][0]
            if section.get("key") != home:
                errors.append(f"{qid} ({rule}) is filed under {section.get('key')} but belongs to {home}")
        severity = question.get("severity")
        if question.get("blocking") is not (severity == validate_pir.ERROR):
            errors.append(f"{qid} has blocking={question.get('blocking')!r} but severity {severity!r}")

    declared = interview.get("counts")
    actual = expected_counts(interview)
    if isinstance(declared, dict) and declared != actual:
        errors.append(f"counts {declared} do not match the document {actual}")

    status = interview.get("status")
    if status == STATUS_NOTHING_TO_ASK and actual["questions"]:
        errors.append(f"status is {STATUS_NOTHING_TO_ASK} but {actual['questions']} question(s) are present")
    if status == STATUS_ANSWERS_REQUIRED and not actual["questions"]:
        errors.append(f"status is {STATUS_ANSWERS_REQUIRED} but there are no questions")
    return errors


def validate_interview(interview: dict[str, Any], schema: dict[str, Any] | None = None) -> list[str]:
    """Schema plus semantics; schema violations come first so the semantic ones are readable."""
    errors = validate_schema(interview, schema or load_schema())
    if errors:
        return errors
    return validate_semantics(interview)


def placeholders(interview: dict[str, Any]) -> list[str]:
    """Every field whose value IS a HUMAN_CONFIRM placeholder, as 'path: value'.

    A placeholder starts with the token (HUMAN_CONFIRM_FACILITATOR, "HUMAN_CONFIRM: ..."); prose
    that merely mentions the convention, such as the instruction to replace them, is not one.
    """
    found: list[str] = []
    for path, text in validate_pir.iter_strings(interview):
        if text.startswith(HUMAN_CONFIRM):
            found.append(f"{path}: {text}")
    return found


def load_interview(path: Path, schema: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load and validate; raise InterviewError naming every defect otherwise."""
    interview = load_document(path)
    errors = validate_interview(interview, schema)
    if errors:
        joined = "\n  - ".join(errors)
        raise InterviewError(f"{path} is not a valid interview:\n  - {joined}")
    return interview
