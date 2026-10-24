# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""Both polarities of the PIR gate: the worked example passes, and every fixture trips its rule.

The committed corpus passing is a regression guard, not proof; what matters is that each
defect class is caught, which is why the negative half is parametrised over every fixture and
asserted on the fixture's own rule ids rather than on an aggregate exit code.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import check_fixtures
import pir_fixtures
import pytest
import validate_pir
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
GOOD = REPO_ROOT / "examples" / "good" / "order-capture-pool-exhaustion.yaml"
FIXTURES = check_fixtures.fixture_paths()


@pytest.fixture(scope="module")
def gate():
    return validate_pir.load_schema(), validate_pir.blame_patterns(), validate_pir.vague_action_patterns()


def _packet() -> dict:
    return copy.deepcopy(yaml.safe_load(GOOD.read_text(encoding="utf-8")))


def _validate(packet: dict, gate) -> validate_pir.Findings:
    schema, blame, vague = gate
    return validate_pir.validate_packet(packet, schema, blame, vague)


def test_the_worked_example_is_clean(gate) -> None:
    findings = _validate(_packet(), gate)
    assert findings.errors == [], [f.render() for f in findings.errors]
    assert findings.warnings == [], [f.render() for f in findings.warnings]


def test_there_are_fixtures() -> None:
    assert FIXTURES, "an empty fixture corpus proves nothing"


@pytest.mark.parametrize("path", FIXTURES, ids=[p.name for p in FIXTURES])
def test_every_fixture_proves_its_rule(path: Path, gate) -> None:
    problems = check_fixtures.check_fixture(path, *gate)
    assert problems == [], problems


def test_every_finding_carries_a_registered_section(gate) -> None:
    """The interview groups by section, so a finding with no section would have no home."""
    schema, blame, vague = gate
    for path in FIXTURES:
        document = pir_fixtures.materialise(pir_fixtures.load_fixture(path))
        for finding in validate_pir.validate_packet(document, schema, blame, vague).items:
            assert finding.section == validate_pir.RULES[finding.rule][0]
            assert finding.severity in (validate_pir.ERROR, validate_pir.WARNING)


def test_unregistered_rule_ids_cannot_be_emitted() -> None:
    with pytest.raises(KeyError):
        validate_pir.Findings().rule("PIR-NOT-A-RULE", "nothing")


def test_key_timings_are_derived_from_the_lifecycle_instants() -> None:
    stamps = {
        "impact_start": datetime.fromisoformat("2026-09-03T09:12:00+10:00"),
        "detected_at": datetime.fromisoformat("2026-09-03T09:21:00+10:00"),
        "cause_confirmed_at": datetime.fromisoformat("2026-09-03T10:05:00+10:00"),
        "mitigated_at": datetime.fromisoformat("2026-09-03T10:26:00+10:00"),
        "resolved_at": datetime.fromisoformat("2026-09-03T10:47:00+10:00"),
    }
    assert validate_pir.derive_key_timings(stamps) == {
        "time_to_detect_minutes": 9,
        "time_to_know_minutes": 44,
        "time_to_remediate_minutes": 21,
        "customer_impact_minutes": 74,
        "time_to_resolve_minutes": 95,
    }


def test_timings_compare_across_offsets() -> None:
    """A UTC detection after an AEST impact start is still 'after'; offsets are honoured."""
    stamps = {
        "impact_start": datetime.fromisoformat("2026-09-03T09:12:00+10:00"),
        "detected_at": datetime.fromisoformat("2026-09-02T23:21:00Z"),  # 09:21 AEST
        "cause_confirmed_at": datetime.fromisoformat("2026-09-03T10:05:00+10:00"),
        "mitigated_at": datetime.fromisoformat("2026-09-03T10:26:00+10:00"),
        "resolved_at": datetime.fromisoformat("2026-09-03T10:47:00+10:00"),
    }
    assert validate_pir.derive_key_timings(stamps)["time_to_detect_minutes"] == 9


def test_naive_timestamps_are_rejected_by_the_schema(gate) -> None:
    packet = _packet()
    packet["document_control"]["timestamps"]["impact_start"] = "2026-09-03T09:12:00"
    findings = _validate(packet, gate)
    assert any(f.rule == "PIR-SCHEMA" and "impact_start" in f.path for f in findings.errors)


def test_whitespace_cannot_satisfy_a_text_field(gate) -> None:
    packet = _packet()
    packet["customer_impact"]["data_integrity"] = "          "
    findings = _validate(packet, gate)
    assert any(f.rule == "PIR-SCHEMA" and "data_integrity" in f.path for f in findings.errors)


def test_not_determined_is_an_honest_count(gate) -> None:
    packet = _packet()
    packet["customer_impact"]["how_many"] = (
        "not determined: gateway access logs for the window were rotated before the PIR began"
    )
    findings = _validate(packet, gate)
    assert not any(f.rule == "PIR-IMPACT-QUANTIFIED" for f in findings.errors)


def test_gap_report_is_written_with_sections(tmp_path: Path) -> None:
    fixture = pir_fixtures.load_fixture(REPO_ROOT / "examples" / "bad" / "vague-action-item.yaml")
    packet_path = tmp_path / "packet.yaml"
    packet_path.write_text(
        yaml.safe_dump(pir_fixtures.materialise(fixture), sort_keys=False), encoding="utf-8"
    )
    report_path = tmp_path / "gap.json"
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "validate_pir.py"),
            str(packet_path),
            "--gap-report",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    entry = report["packets"][0]
    assert entry["status"] == "FAIL"
    assert entry["id"] == "PIR-2026-0412"
    vague = [f for f in entry["findings"] if f["rule"] == "PIR-AI-VAGUE"]
    assert (
        vague and vague[0]["section"] == "action_items" and vague[0]["path"] == "$.action_items[0].statement"
    )


def test_warnings_do_not_fail_unless_asked(tmp_path: Path) -> None:
    fixture = pir_fixtures.load_fixture(REPO_ROOT / "examples" / "bad" / "why-chain-shallow.yaml")
    packet_path = tmp_path / "packet.yaml"
    packet_path.write_text(
        yaml.safe_dump(pir_fixtures.materialise(fixture), sort_keys=False), encoding="utf-8"
    )
    tool = str(REPO_ROOT / "tools" / "validate_pir.py")
    lenient = subprocess.run(
        [sys.executable, tool, str(packet_path)], capture_output=True, text=True, check=False
    )
    strict = subprocess.run(
        [sys.executable, tool, str(packet_path), "--warnings-as-errors"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert lenient.returncode == 0 and "PIR-WHY-SHALLOW" in lenient.stderr
    assert strict.returncode == 1


def test_an_unreadable_packet_fails_rather_than_crashing(tmp_path: Path) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("id: [unclosed", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "validate_pir.py"), str(broken)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1 and "PIR-SCHEMA" in result.stderr


# ------------------------------------------------------------ an opt-in exact rule assertion


def _copy_with(tmp_path: Path, source: str, **extra: object) -> Path:
    fixture = yaml.safe_load((REPO_ROOT / source).read_text(encoding="utf-8"))
    fixture.update(extra)
    path = tmp_path / Path(source).name
    path.write_text(yaml.safe_dump(fixture, sort_keys=False), encoding="utf-8")
    return path


def test_expect_exactly_names_the_rules_a_fixture_fires_but_does_not_assert(tmp_path: Path, gate) -> None:
    """`no-lessons` names PIR-LESSONS-NONE and also fires PIR-CA-LL-UNKNOWN and PIR-RC-NO-LESSON."""
    plain = _copy_with(tmp_path, "examples/bad/no-lessons.yaml")
    assert check_fixtures.check_fixture(plain, *gate) == []
    exact = _copy_with(tmp_path, "examples/bad/no-lessons.yaml", expect_exactly=True)
    problems = check_fixtures.check_fixture(exact, *gate)
    assert problems and "PIR-CA-LL-UNKNOWN" in problems[0] and "PIR-RC-NO-LESSON" in problems[0]


def test_expect_exactly_passes_when_the_named_rules_are_the_whole_set(tmp_path: Path, gate) -> None:
    named = ["PIR-LESSONS-NONE", "PIR-CA-LL-UNKNOWN", "PIR-RC-NO-LESSON"]
    exact = _copy_with(tmp_path, "examples/bad/no-lessons.yaml", expect=named, expect_exactly=True)
    assert check_fixtures.check_fixture(exact, *gate) == []


@pytest.mark.parametrize("value", ["yes", 1])
def test_expect_exactly_must_be_a_boolean(tmp_path: Path, value: object) -> None:
    with pytest.raises(pir_fixtures.FixtureError, match="expect_exactly must be true or false"):
        pir_fixtures.load_fixture(_copy_with(tmp_path, "examples/bad/no-lessons.yaml", expect_exactly=value))
