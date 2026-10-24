#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""check_artifact_conventions.py: every file under interviews/, clarifications/ and reviews/ is what it claims.

The three directories hold the artifacts of real assessments, one folder per packet stem, each
file named by the convention its README states:

    interviews/<stem>/<YYYYMMDDTHHMMSSZ>-I<nn>.yaml   an interview (and its .md rendering)
    clarifications/<stem>/<YYYYMMDDTHHMMSSZ>-L<nn>.yaml   a clarification ledger
    reviews/<stem>/<YYYYMMDDTHHMMSSZ>-<reviewer>.json   a reviewer-findings artifact

The lesson it is built on: a check that
globs `*/*` into one validator mis-routes the other kinds and then blames them. So this check
classifies each file by the naming rule, routes it to its own validator in-process, and fails
on anything it cannot classify, so a new kind of file cannot be skipped silently. A README at a
directory root is allowed; nothing else is. A rendered interview (.md) must sit beside its
YAML and match it byte for byte.

Exit codes: 0 every artifact conforms; 1 a violation; 2 no artifacts at all, which a caller
reports as a skip, never a pass: there was nothing to check.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pir_interview
import render_pir_interview
import validate_pir
import validate_pir_ledger
import validate_pir_review

REPO_ROOT = Path(__file__).resolve().parent.parent
TIMESTAMP = r"\d{8}T\d{6}Z"
PATTERNS: dict[str, dict[str, re.Pattern[str]]] = {
    "interviews": {
        "interview": re.compile(rf"^{TIMESTAMP}-I\d{{2}}\.yaml$"),
        "interview-markdown": re.compile(rf"^{TIMESTAMP}-I\d{{2}}\.md$"),
    },
    "clarifications": {"ledger": re.compile(rf"^{TIMESTAMP}-L\d{{2}}\.yaml$")},
    "reviews": {"review": re.compile(rf"^{TIMESTAMP}-[a-z0-9-]+\.json$")},
}
ROOT_ALLOWED = {"README.md"}
EMPTY = 2


def classify(relative: Path) -> str:
    """'root-doc', one of the artifact kinds, or 'unknown'."""
    if not relative.parts or relative.parts[0] not in PATTERNS:
        return "unknown"
    if len(relative.parts) == 2:
        return "root-doc" if relative.name in ROOT_ALLOWED else "unknown"
    if len(relative.parts) != 3:
        return "unknown"
    for kind, pattern in PATTERNS[relative.parts[0]].items():
        if pattern.match(relative.name):
            return kind
    return "unknown"


def check_interview(path: Path) -> list[str]:
    try:
        pir_interview.load_interview(path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [str(exc)]
    return []


def check_interview_markdown(path: Path) -> list[str]:
    source = path.with_suffix(".yaml")
    if not source.is_file():
        return [f"{path.name} has no {source.name} beside it"]
    try:
        interview = pir_interview.load_interview(source)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [f"{source.name}: {exc}"]
    if render_pir_interview.render_markdown(interview) != path.read_text(encoding="utf-8"):
        return [f"{path.name} is not the rendering of {source.name}; re-render it"]
    return []


def check_ledger(path: Path, repo_root: Path) -> list[str]:
    try:
        ledger = validate_pir.load_document(path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [str(exc)]
    findings = validate_pir_ledger.validate_ledger(ledger, validate_pir_ledger.load_schema(), repo_root)
    return [f.render() for f in findings.errors]


def check_review(path: Path, repo_root: Path) -> list[str]:
    try:
        review = validate_pir_review.load_review(path)
    except (OSError, ValueError) as exc:
        return [str(exc)]
    findings = validate_pir_review.validate_review(review, validate_pir_review.load_schema(), repo_root, path)
    return [f.render() for f in findings.errors]


def problems(repo_root: Path) -> tuple[list[str], int]:
    """(violations, artifact count). Zero artifacts with no violations is the EMPTY case."""
    violations: list[str] = []
    artifacts = 0
    for directory in PATTERNS:
        root = repo_root / directory
        if not root.exists():
            continue  # nothing filed there yet: no artifacts, which is a skip, never a pass
        if not root.is_dir():
            violations.append(f"{directory} is not a directory")
            continue
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            relative = path.relative_to(repo_root)
            kind = classify(relative)
            if kind == "root-doc":
                continue
            if kind == "unknown":
                violations.append(f"{relative}: does not match any artifact kind in {directory}/README.md")
                continue
            artifacts += 1
            if kind == "interview":
                issues = check_interview(path)
            elif kind == "interview-markdown":
                issues = check_interview_markdown(path)
            elif kind == "ledger":
                issues = check_ledger(path, repo_root)
            else:
                issues = check_review(path, repo_root)
            violations.extend(f"{relative}: {issue}" for issue in issues)
    return violations, artifacts


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check that every artifact under interviews/, clarifications/ and reviews/ conforms."
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path.cwd()),
        help="Repository root to check. Defaults to the current directory: run from the root that holds "
        "interviews/, clarifications/ and reviews/.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root)
    violations, artifacts = problems(repo_root)
    if violations:
        print(f"FAIL: {len(violations)} artifact-convention violation(s):", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1
    if artifacts == 0:
        print(
            "SKIP: no artifacts under interviews/, clarifications/ or reviews/ yet (a skip is not a pass)",
            file=sys.stderr,
        )
        return EMPTY
    print(
        f"PASS: {artifacts} artifact(s) match their directory's convention and validate against their own contract"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
