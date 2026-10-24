# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""The artifacts the tools read are someone else's input.

Containment: a cited path joined onto `--repo-root` and opened as given would let `root / "/etc/x"`
become `/etc/x`, so a ledger or a review could make the validator read, load and echo any file.
Loading: `yaml.safe_load` expands every alias, so a packet of a few hundred bytes could become
millions of nodes. Each attack is reproduced here against the real loaders and validators.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pir_interview
import pytest
import validate_pir
import validate_pir_ledger
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
GOOD = REPO_ROOT / "examples" / "good" / "order-capture-pool-exhaustion.yaml"
LEDGER = REPO_ROOT / "examples" / "ledgers" / "good" / "order-capture-draft-L01-resolved.yaml"
REVIEW = REPO_ROOT / "examples" / "reviews" / "good" / "order-capture-go-review.json"
INTERVIEW = REPO_ROOT / "examples" / "interviews" / "order-capture-draft-I01.yaml"

#: The review's measurement: 210 bytes of nested anchors became 262,144 nodes under safe_load.
ALIAS_BOMB = "a: &a [x, x, x, x, x, x, x, x]\n" + "".join(
    f"{chr(98 + i)}: &{chr(98 + i)} [*{chr(97 + i)}, *{chr(97 + i)}, *{chr(97 + i)}, *{chr(97 + i)}, *{chr(97 + i)}, *{chr(97 + i)}, *{chr(97 + i)}, *{chr(97 + i)}]\n"
    for i in range(5)
)


# -------------------------------------------------------------------------------- containment


@pytest.mark.parametrize(
    "reference",
    [
        "/etc/hostname",
        "../../../../../../etc/hostname",
        "examples/../../outside.yaml",
        "C:\\Windows\\win.ini",
        "C:x",
    ],
    ids=["absolute", "dot-dot", "dot-dot-inside", "windows-drive", "windows-drive-relative"],
)
def test_a_reference_that_leaves_the_root_is_not_contained(reference: str) -> None:
    assert validate_pir.contained_path(reference, REPO_ROOT) is None


def test_a_reference_inside_the_root_is_contained() -> None:
    assert validate_pir.contained_path("examples/good/order-capture-pool-exhaustion.yaml", REPO_ROOT) == GOOD
    assert validate_pir.contained_path("examples/../examples/good/x.yaml", REPO_ROOT) is not None


def test_a_symbolic_link_that_leads_out_is_not_contained(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.yaml").write_text("id: secret\n", encoding="utf-8")
    (root / "innocent.yaml").symlink_to(tmp_path / "secret.yaml")
    assert validate_pir.contained_path("innocent.yaml", root) is None


def _ledger_with(packet_reference: str) -> dict:
    ledger = validate_pir.load_document(LEDGER)
    ledger["scope"]["packet"] = packet_reference
    return ledger


def test_the_ledger_validator_refuses_to_open_a_path_outside_the_root() -> None:
    findings = validate_pir_ledger.validate_ledger(
        _ledger_with("/etc/hostname"), validate_pir_ledger.load_schema(), REPO_ROOT
    )
    rules = {f.rule for f in findings.items}
    assert "LEDGER-PATH-OUTSIDE" in rules and "LEDGER-PATH-UNRESOLVED" not in rules


def test_the_review_validator_refuses_to_open_a_path_outside_the_root(tmp_path: Path) -> None:
    """The review's reproduction: the target was loaded and its `id` echoed back."""
    secret = tmp_path / "secret.yaml"
    secret.write_text("id: TOP-SECRET-ID\n", encoding="utf-8")
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    review["subject"]["path"] = str(secret)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "tools/validate_pir_review.py", str(review_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1 and "REVIEW-PATH-OUTSIDE" in result.stderr
    assert "TOP-SECRET-ID" not in result.stdout + result.stderr


def test_an_external_reference_is_still_reported_not_refused() -> None:
    ledger = validate_pir.load_document(LEDGER)
    ledger["scope"]["source_artifacts"][0]["path"] = "external:/etc/hostname"
    findings = validate_pir_ledger.validate_ledger(ledger, validate_pir_ledger.load_schema(), REPO_ROOT)
    assert "LEDGER-PATH-OUTSIDE" not in {f.rule for f in findings.items}
    assert any("/etc/hostname" in e for e in findings.external)


# -------------------------------------------------------------------------------- the loaders


def test_the_alias_bomb_expands_under_safe_load_and_is_refused_here(tmp_path: Path) -> None:
    def count(node: object) -> int:
        return 1 + sum(count(v) for v in node) if isinstance(node, list) else 1

    assert count(yaml.safe_load(ALIAS_BOMB)["f"]) > 250_000, "the attack is real under safe_load"
    bomb = tmp_path / "bomb.yaml"
    bomb.write_text(ALIAS_BOMB, encoding="utf-8")
    with pytest.raises(yaml.YAMLError, match="aliases"):
        validate_pir.load_document(bomb)


@pytest.mark.parametrize("tool", ["tools/validate_pir.py", "tools/validate_pir_ledger.py"])
def test_a_validator_reports_an_aliased_document_as_a_failure(tool: str, tmp_path: Path) -> None:
    bomb = tmp_path / "bomb.yaml"
    bomb.write_text(ALIAS_BOMB, encoding="utf-8")
    result = subprocess.run([sys.executable, tool, str(bomb)], capture_output=True, text=True, check=False)
    assert result.returncode == 1 and "aliases" in result.stderr, result.stderr[-400:]


def test_the_interview_loader_refuses_an_alias(tmp_path: Path) -> None:
    text = INTERVIEW.read_text(encoding="utf-8").replace("round: 1\n", "round: &r 1\nalso: *r\n", 1)
    assert "*r" in text
    aliased = tmp_path / "interview.yaml"
    aliased.write_text(text, encoding="utf-8")
    with pytest.raises(pir_interview.InterviewError, match="aliases"):
        pir_interview.load_document(aliased)


def test_an_anchor_without_an_alias_still_parses(tmp_path: Path) -> None:
    anchored = tmp_path / "anchored.yaml"
    anchored.write_text("id: &id PIR-1\nname: x\n", encoding="utf-8")
    assert validate_pir.load_document(anchored) == {"id": "PIR-1", "name": "x"}


def test_an_oversized_document_is_refused_unread(tmp_path: Path) -> None:
    big = tmp_path / "big.yaml"
    big.write_text("x: " + "a" * validate_pir.MAX_DOCUMENT_BYTES + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="at most"):
        validate_pir.load_document(big)


def test_every_committed_artifact_is_well_inside_the_cap() -> None:
    """The cap is a ceiling for attacks, not for honest PIRs: the largest committed artifact is far below it."""
    artifacts = [
        p
        for d in ("examples", "pirs", "interviews", "clarifications", "reviews")
        for p in (REPO_ROOT / d).rglob("*")
        if p.suffix in (".yaml", ".yml", ".json")
    ]
    assert artifacts and max(p.stat().st_size for p in artifacts) * 10 < validate_pir.MAX_DOCUMENT_BYTES
