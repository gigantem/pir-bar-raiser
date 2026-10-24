#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""report_rule_coverage.py: every validator rule has a fixture that proves it fires.

Reads the rule tables from tools/validate_pir.py, tools/validate_pir_ledger.py and tools/validate_pir_review.py (not by regex
over their source, so a renamed rule cannot leave a stale entry) and the `expect` /
`expect_warnings` lists of every mutation fixture of the matching kind. A rule with no fixture has never been shown to reject anything; a fixture naming a
rule that does not exist is asserting on nothing.

Exit 0 when every rule is covered; 1 otherwise. There is deliberately no ratchet flag: the
baseline is zero uncovered rules and it stays there.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_fixtures
import pir_fixtures
import validate_pir
import validate_pir_ledger
import validate_pir_review

REPO_ROOT = Path(__file__).resolve().parent.parent


def all_rules() -> dict[str, tuple[str, str]]:
    """Every rule id across both validators -> (home, severity). Ledger rules live in 'ledger'."""
    merged: dict[str, tuple[str, str]] = dict(validate_pir.RULES)
    for home, table in (("ledger", validate_pir_ledger.RULES), ("review", validate_pir_review.RULES)):
        for rule_id, severity in table.items():
            if rule_id in merged:
                raise ValueError(f"{rule_id} is defined by two validators")
            merged[rule_id] = (home, severity)
    return merged


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report, for every rule of the three validators, the fixtures that prove it fires; fail on a rule with none. Takes no arguments."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parse_args(argv if argv is not None else [])
    coverage: dict[str, list[str]] = defaultdict(list)
    unknown: list[tuple[str, str]] = []
    paths = check_fixtures.fixture_paths()
    if not paths:
        print("FAIL: no fixtures found; a coverage report over nothing is decoration")
        return 1
    rules = all_rules()
    broken: list[str] = []
    for path in paths:
        rel = str(path.relative_to(REPO_ROOT))
        try:
            fixture = pir_fixtures.load_fixture(path)
        except pir_fixtures.FixtureError as exc:
            broken.append(f"{rel}: {exc}")
            continue
        kind_rules = check_fixtures.RULE_TABLES[fixture.get("kind", pir_fixtures.DEFAULT_KIND)]
        for rule_id in list(fixture.get("expect") or []) + list(fixture.get("expect_warnings") or []):
            if rule_id in kind_rules:
                coverage[rule_id].append(rel)
            else:
                unknown.append((rel, rule_id))

    uncovered = sorted(rule for rule in rules if rule not in coverage)
    width = max(len(rule) for rule in rules)
    for rule_id, (section, severity) in rules.items():
        count = len(coverage.get(rule_id, []))
        marker = "ok " if count else "MISSING"
        print(f"{marker:8} {rule_id:{width}}  {severity:7}  {section:18}  {count} fixture(s)")

    status = 0
    if broken:
        status = 1
        print(f"\nFAIL: {len(broken)} fixture(s) could not be read:")
        for problem in broken:
            print(f"  - {problem}")
    if unknown:
        status = 1
        print(f"\nFAIL: {len(unknown)} fixture expectation(s) name a rule that does not exist:")
        for rel, rule_id in unknown:
            print(f"  - {rel}: {rule_id}")
    if uncovered:
        status = 1
        print(f"\nFAIL: {len(uncovered)} of {len(rules)} rule(s) have no fixture proving they fire:")
        for rule_id in uncovered:
            print(f"  - {rule_id}")
    if status == 0:
        print(f"\nPASS: all {len(rules)} rules are covered by at least one fixture")
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
