#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""render_pir_review_scaffold.py: the mechanical half of a review, with the judgement half left blank.

The rule it enforces: a
tool must never emit something that could be mistaken for a review. This one emits a SCAFFOLD:
the subject block (path, packet id, sha256 digest), the gate's own verdict (`gate_evidence`,
from a fresh run of tools/validate_pir.py), and the ledgers found for the packet, all facts the
free gate computes. Every field that is a judgement (`status`, `summary`, the three counts,
`findings`, and each template section's entry in `coverage`) is the sentinel string
ASSESSOR_JUDGEMENT_REQUIRED, deliberately a string even where the schema wants an integer or an
array. There is no code path here that emits
`status: PASS` or `blocker_count: 0`.

Three mechanisms keep a scaffold from being read as a review, and all three are tested:

1. the sentinels, which tools/validate_pir_review.py rejects by name (REVIEW-SENTINEL);
2. the `_scaffold` block, which schemas/pir-review.schema.json rejects (additionalProperties
   false); before writing, this tool validates its own output and ABORTS if it would pass;
3. a refusal to write under reviews/ or under the committed-review naming convention.

`--check PATH` regenerates and compares with an existing scaffold instead of writing.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_pir_interview
import pir_interview
import validate_pir
import validate_pir_review

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = "tools/render_pir_review_scaffold.py"
JUDGEMENT = validate_pir_review.JUDGEMENT
JUDGEMENT_FIELDS = (
    "status",
    "summary",
    "blocker_count",
    "non_blocker_count",
    "waiver_count",
    "findings",
    "coverage",
)
MECHANICAL_FIELDS = (
    "subject.kind",
    "subject.path",
    "subject.id",
    "subject.revision",
    "reviewer",
    "review_stage",
    "gate_evidence",
    "clarification_ledgers",
)
NOT_AN_ATTESTATION = (
    "This document is a SCAFFOLD emitted by tools/render_pir_review_scaffold.py, NOT a review and "
    "NOT an attestation. Every field in _scaffold.judgement_fields holds the sentinel "
    "ASSESSOR_JUDGEMENT_REQUIRED and must be replaced by a reviewer who actually read the packet. "
    "Delete the _scaffold block when the judgements are in. This file deliberately FAILS "
    "schemas/pir-review.schema.json until that happens."
)


def discover_ledgers(packet_path: Path, repo_root: Path) -> list[str]:
    """Ledgers under clarifications/<stem>/ whose scope.packet is this packet, repo-relative."""
    stem_dir = repo_root / "clarifications" / packet_path.stem
    if not stem_dir.is_dir():
        return []
    relative_packet = relative_to_root(packet_path, repo_root)
    found: list[str] = []
    for candidate in sorted(stem_dir.glob("*.y*ml")):
        try:
            ledger = validate_pir.load_document(candidate)
        except (OSError, ValueError, yaml.YAMLError):
            continue
        scope = validate_pir.mapping(ledger.get("scope"))
        if scope.get("packet") == relative_packet:
            found.append(relative_to_root(candidate, repo_root))
    return found


def relative_to_root(path: Path, repo_root: Path) -> str:
    """A path as artifacts record it: relative to `repo_root` when inside it, else as given."""
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def build_scaffold(
    packet_path: Path,
    packet: dict[str, Any],
    reviewer: str,
    review_stage: str,
    ledgers: list[str],
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    return {
        "_scaffold": {
            "generator": GENERATOR,
            "not_an_attestation": NOT_AN_ATTESTATION,
            "judgement_sentinel": JUDGEMENT,
            "judgement_fields": list(JUDGEMENT_FIELDS),
            "mechanically_derived_fields": list(MECHANICAL_FIELDS),
        },
        "subject": {
            "kind": "pir-packet",
            "path": generate_pir_interview.repo_relative(packet_path, repo_root),
            "id": packet.get("id") if isinstance(packet.get("id"), str) else None,
            "revision": validate_pir_review.packet_digest(packet_path),
        },
        "reviewer": reviewer,
        "review_stage": review_stage,
        "status": JUDGEMENT,
        "summary": JUDGEMENT,
        "gate_evidence": validate_pir_review.gate_evidence_for(packet),
        "clarification_ledgers": ledgers,
        "blocker_count": JUDGEMENT,
        "non_blocker_count": JUDGEMENT,
        "waiver_count": JUDGEMENT,
        "findings": JUDGEMENT,
        "coverage": {section: JUDGEMENT for section in pir_interview.load_section_catalog()},
    }


def assert_not_a_review(document: dict[str, Any]) -> None:
    """Abort unless the scaffold is inadmissible as a review. The attestation boundary, machine-checked."""
    schema = validate_pir_review.load_schema()
    if not list(Draft202012Validator(schema).iter_errors(document)):
        raise SystemExit(
            "REFUSING TO EMIT: this scaffold validates as a reviewer-findings artifact, so it could be "
            "mistaken for a review. Check schemas/pir-review.schema.json and the JUDGEMENT sentinel."
        )
    findings = validate_pir_review.validate_review(document, schema)
    if not any(f.rule == "REVIEW-SENTINEL" for f in findings.items):
        raise SystemExit("REFUSING TO EMIT: the review validator no longer rejects the judgement sentinel.")


def assert_output_path_is_not_a_review_slot(output: Path) -> None:
    """Refuse any output a review could occupy, whatever directory the tool runs from.

    Refusing only `<repo-root>/reviews` is not enough, because the root defaults to the current
    directory, so an absolute path from anywhere else, a symbolic link or a `.JSON` name would get
    past it. So: a symbolic link is refused; a name that matches the review naming convention in any
    case is refused; and so is any path with a directory called `reviews`, in any case, either as
    written or once links are resolved. The gate's real backstop is still
    `tools/check_artifact_conventions.py`, which fails on anything under `reviews/` that is not a
    review."""
    if output.is_symlink():
        raise SystemExit(
            f"REFUSING TO WRITE {output}: it is a symbolic link, so it could point into reviews/; "
            "write the scaffold to a plain file."
        )
    resolved = output.resolve()
    if re.match(validate_pir_review.FILING_NAME.pattern, resolved.name, re.IGNORECASE):
        raise SystemExit(
            f"REFUSING TO WRITE {output}: '<timestamp>-<reviewer>.json' is the committed-review naming "
            "convention (reviews/README.md). A scaffold must not occupy it; use a '.scaffold.json' name."
        )
    directories = {part.lower() for path in (output.absolute(), resolved) for part in path.parts[:-1]}
    if "reviews" in directories:
        raise SystemExit(
            f"REFUSING TO WRITE {output}: reviews/ holds attestations a reviewer signed. A scaffold is not "
            "one; render it outside any directory called reviews/ and let the reviewer write the review."
        )


def serialise(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a reviewer-findings SCAFFOLD for one PIR packet: mechanical fields prefilled, every judgement a sentinel."
    )
    parser.add_argument("packet", help="The PIR packet to scaffold a review for.")
    parser.add_argument(
        "--reviewer", default="pir-reviewer", help="Who is expected to fill the judgements, not who did."
    )
    parser.add_argument("--review-stage", default="readiness", choices=("readiness", "team", "go", "exec_go"))
    parser.add_argument(
        "--output", help="Output path; refused inside reviews/ or named like a committed review."
    )
    parser.add_argument(
        "--check",
        help="Regenerate and compare with this existing scaffold; exit 1 with a diff if they differ.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path.cwd()),
        help="Root the subject path is recorded relative to, where clarifications/<stem>/ is searched for "
        "ledgers and whose reviews/ is refused as an output. Defaults to the current directory.",
    )
    args = parser.parse_args(argv)
    if args.output and args.check:
        parser.error("--output and --check are exclusive")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    packet_path = Path(args.packet)
    repo_root = Path(args.repo_root)
    if args.output:
        assert_output_path_is_not_a_review_slot(Path(args.output))
    try:
        packet = validate_pir.load_document(packet_path)
    except FileNotFoundError:
        print(f"ERROR: packet not found: {packet_path}", file=sys.stderr)
        return 1
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    scaffold = build_scaffold(
        packet_path,
        packet,
        args.reviewer,
        args.review_stage,
        discover_ledgers(packet_path, repo_root),
        repo_root=repo_root,
    )
    assert_not_a_review(scaffold)
    text = serialise(scaffold)

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
    evidence = scaffold["gate_evidence"]
    print(
        f"scaffold for {scaffold['subject']['path']}: gate {evidence['validator_status']} "
        f"({evidence['error_count']} error(s), {evidence['warning_count']} warning(s)); judgements left to the reviewer",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
