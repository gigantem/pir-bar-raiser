# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""Ratchets: every rule has a fixture, every rule has a home, every lexicon term fires."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import report_rule_coverage
import validate_catalogs
import validate_pir
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
GOOD = REPO_ROOT / "examples" / "good" / "order-capture-pool-exhaustion.yaml"


def test_every_rule_has_a_fixture(capsys) -> None:
    assert report_rule_coverage.main() == 0, capsys.readouterr().out


def test_catalogs_agree_with_schema_and_validator(capsys) -> None:
    assert validate_catalogs.main() == 0, capsys.readouterr().out


def test_a_rule_without_a_home_is_reported(monkeypatch, capsys) -> None:
    monkeypatch.setitem(validate_pir.RULES, "PIR-ORPHAN", ("summary", validate_pir.ERROR))
    assert validate_catalogs.main() == 1
    assert "PIR-ORPHAN has no home" in capsys.readouterr().out


def test_a_rule_filed_under_the_wrong_section_is_reported(monkeypatch, capsys) -> None:
    monkeypatch.setitem(validate_pir.RULES, "PIR-AI-VAGUE", ("summary", validate_pir.ERROR))
    assert validate_catalogs.main() == 1
    assert (
        "PIR-AI-VAGUE under action_items but the validator assigns it to summary" in capsys.readouterr().out
    )


@pytest.fixture(scope="module")
def gate():
    return validate_pir.load_schema(), validate_pir.blame_patterns(), validate_pir.vague_action_patterns()


def _packet() -> dict:
    return copy.deepcopy(yaml.safe_load(GOOD.read_text(encoding="utf-8")))


def _blame_terms() -> list[str]:
    data = yaml.safe_load(validate_pir.BLAME_LEXICON_PATH.read_text(encoding="utf-8"))
    return [t["term"] for t in data["terms"]]


def _vague_terms() -> list[str]:
    data = yaml.safe_load(validate_pir.VAGUE_ACTION_LEXICON_PATH.read_text(encoding="utf-8"))
    return [t["term"] for t in data["terms"]]


@pytest.mark.parametrize("term", _blame_terms())
def test_every_blame_term_fires_in_prose(term: str, gate) -> None:
    packet = _packet()
    packet["lessons"][0]["statement"] = (
        f"The outcome was {term} on the part of the team, and that is the whole lesson here."
    )
    findings = validate_pir.validate_packet(packet, *gate)
    assert any(
        f.rule == "PIR-BLAME-LANGUAGE" and f.path == "$.lessons[0].statement" for f in findings.errors
    ), term


def test_neutral_failure_language_is_not_blame(gate) -> None:
    packet = _packet()
    packet["response_analysis"]["missed"][0]["gap"] = (
        "The alert failed to fire for ten minutes because of its sustained-window threshold."
    )
    findings = validate_pir.validate_packet(packet, *gate)
    assert not any(f.rule == "PIR-BLAME-LANGUAGE" for f in findings.errors)


@pytest.mark.parametrize("term", _vague_terms())
def test_every_vague_opening_verb_fires(term: str, gate) -> None:
    packet = _packet()
    packet["action_items"][0]["statement"] = (
        f"{term.capitalize()} the connection pool sizing before the next release cycle."
    )
    findings = validate_pir.validate_packet(packet, *gate)
    assert any(f.rule == "PIR-AI-VAGUE" for f in findings.errors), term


def test_a_vague_verb_mid_sentence_is_allowed(gate) -> None:
    """'Add a dashboard panel so responders can review pool saturation' is concrete; only the opening verb counts."""
    packet = _packet()
    packet["action_items"][0]["statement"] = (
        "Add a saturation panel so responders can review pool state without an ad-hoc query."
    )
    findings = validate_pir.validate_packet(packet, *gate)
    assert not any(f.rule == "PIR-AI-VAGUE" for f in findings.errors)


def test_an_empty_lexicon_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "lex.yaml"
    empty.write_text("version: 0.1\nterms: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no terms"):
        validate_pir.load_lexicon_terms(empty)
