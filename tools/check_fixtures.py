#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""check_fixtures.py: every mutation fixture proves exactly what it claims.

For each fixture under examples/bad/ (and each *.mutation.yaml under examples/good/), and for
each ledger fixture under examples/ledgers/bad/ (and *.mutation.yaml under examples/ledgers/good/):

* materialise it (tools/pir_fixtures.py), run the matching validator in-process (the packet
  validator for `kind: packet`, the default; the ledger validator for `kind: ledger`), and
* require every rule in `expect` to fire as an error and every rule in `expect_warnings` to
  fire as a warning; or, for `expect_clean`, require no error at all;
* reject a fixture that names a rule the validator does not define.

This is the by-message half of the both-polarity gate: an aggregate "all bad fixtures fail"
assertion stays green while any one fixture still fails for some other reason, so each fixture is
asserted on its own rule here. Refuses to pass over an empty corpus.

Exit 0 when every fixture holds; 1 otherwise, naming each failure.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pir_fixtures
import validate_pir
import validate_pir_ledger
import validate_pir_review

REPO_ROOT = Path(__file__).resolve().parent.parent
BAD_ROOT = REPO_ROOT / "examples" / "bad"
GOOD_ROOT = REPO_ROOT / "examples" / "good"
LEDGER_BAD_ROOT = REPO_ROOT / "examples" / "ledgers" / "bad"
LEDGER_GOOD_ROOT = REPO_ROOT / "examples" / "ledgers" / "good"
REVIEW_BAD_ROOT = REPO_ROOT / "examples" / "reviews" / "bad"
REVIEW_GOOD_ROOT = REPO_ROOT / "examples" / "reviews" / "good"
#: Rule tables by fixture kind: the ids a fixture of that kind may expect.
RULE_TABLES: dict[str, dict[str, Any]] = {
    "packet": validate_pir.RULES,
    "ledger": validate_pir_ledger.RULES,
    "review": validate_pir_review.RULES,
}


def fixture_paths() -> list[Path]:
    packet_bad = sorted(p for p in BAD_ROOT.glob("*.yaml") if p.is_file())
    packet_good = sorted(p for p in GOOD_ROOT.glob(f"*{pir_fixtures.MUTATION_SUFFIX}") if p.is_file())
    ledger_bad = sorted(p for p in LEDGER_BAD_ROOT.glob("*.yaml") if p.is_file())
    ledger_good = sorted(p for p in LEDGER_GOOD_ROOT.glob(f"*{pir_fixtures.MUTATION_SUFFIX}") if p.is_file())
    review_bad = sorted(p for p in REVIEW_BAD_ROOT.glob("*.yaml") if p.is_file())
    review_good = sorted(p for p in REVIEW_GOOD_ROOT.glob(f"*{pir_fixtures.MUTATION_SUFFIX}") if p.is_file())
    return packet_bad + packet_good + ledger_bad + ledger_good + review_bad + review_good


class FindingLike(Protocol):
    """One finding of any of the three validators: all this check reads is its rule id."""

    @property
    def rule(self) -> str: ...


class FindingsLike(Protocol):
    """The findings of any of the three validators, each its own class with the same shape."""

    @property
    def errors(self) -> Sequence[FindingLike]: ...

    @property
    def warnings(self) -> Sequence[FindingLike]: ...


def check_fixture(path: Path, schema, blame, vague, ledger_schema=None) -> list[str]:
    problems: list[str] = []
    try:
        fixture = pir_fixtures.load_fixture(path)
        document = pir_fixtures.materialise(fixture)
    except pir_fixtures.FixtureError as exc:
        return [str(exc)]

    kind = fixture.get("kind", pir_fixtures.DEFAULT_KIND)
    findings: FindingsLike
    if kind == "ledger":
        findings = validate_pir_ledger.validate_ledger(
            document, ledger_schema or validate_pir_ledger.load_schema()
        )
    elif kind == "review":
        as_path = fixture.get("as_path")
        artifact_path = REPO_ROOT / str(as_path) if isinstance(as_path, str) else None
        findings = validate_pir_review.validate_review(
            document, validate_pir_review.load_schema(), REPO_ROOT, artifact_path
        )
    else:
        findings = validate_pir.validate_packet(document, schema, blame, vague)
    rules = RULE_TABLES[kind]
    fired_errors = {f.rule for f in findings.errors}
    fired_warnings = {f.rule for f in findings.warnings}

    for rule_id in list(fixture.get("expect") or []) + list(fixture.get("expect_warnings") or []):
        if rule_id not in rules:
            problems.append(f"expects {rule_id}, which the {kind} validator does not define")
    for rule_id in fixture.get("expect") or []:
        if rule_id not in fired_errors:
            problems.append(
                f"expected error {rule_id} did not fire (errors fired: {sorted(fired_errors) or 'none'})"
            )
    for rule_id in fixture.get("expect_warnings") or []:
        if rule_id not in fired_warnings:
            problems.append(
                f"expected warning {rule_id} did not fire (warnings fired: {sorted(fired_warnings) or 'none'})"
            )
    if fixture.get("expect_clean") is True and fired_errors:
        problems.append(f"expected no errors but {sorted(fired_errors)} fired")
    if fixture.get("expect_exactly") is True:
        # Opt-in: the named rules are the whole set, not a floor.
        for kind_name, fired, named in (
            ("error", fired_errors, set(fixture.get("expect") or [])),
            ("warning", fired_warnings, set(fixture.get("expect_warnings") or [])),
        ):
            unnamed = sorted(fired - named)
            if unnamed:
                problems.append(f"expect_exactly: {kind_name}(s) {unnamed} fired but are not named")
    return problems


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialise every mutation fixture and require each one to fire the rules it names. Takes no arguments."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parse_args(argv if argv is not None else [])
    paths = fixture_paths()
    if not paths:
        print("FAIL: no mutation fixtures found; refusing to report a pass over an empty corpus")
        return 1
    schema = validate_pir.load_schema()
    blame = validate_pir.blame_patterns()
    vague = validate_pir.vague_action_patterns()
    ledger_schema = validate_pir_ledger.load_schema()

    failures = 0
    for path in paths:
        problems = check_fixture(path, schema, blame, vague, ledger_schema)
        rel = path.relative_to(REPO_ROOT)
        if problems:
            failures += 1
            print(f"FAIL {rel}")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print(f"PASS {rel}")
    if failures:
        print(f"\nFAIL: {failures} of {len(paths)} fixture(s) do not prove what they claim")
        return 1
    print(f"\nPASS: all {len(paths)} fixture(s) prove what they claim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
