# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""The ways a packet, a ledger or a review could slip past the gate are caught, and the legitimate
prose beside them is not: blame, placeholders and evidence, dates, timings, pointers, the summary,
vague actions, actors, and the rules' own items.

Each defect class has a mutation fixture under examples/*/bad/ that proves it through the gate; these
tests carry the full lists, both polarities, so a widened or narrowed denylist shows here first.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import json_pointer
import pir_fixtures
import pytest
import validate_pir
import validate_pir_ledger
import validate_pir_review
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
GOOD = REPO_ROOT / "examples" / "good" / "order-capture-pool-exhaustion.yaml"
RESOLVED = REPO_ROOT / "examples" / "ledgers" / "good" / "order-capture-draft-L01-resolved.yaml"
GO_REVIEW = REPO_ROOT / "examples" / "reviews" / "good" / "order-capture-go-review.json"
CYRILLIC_A = chr(0x430)
NBSP, ZWSP = chr(0xA0), chr(0x200B)


@pytest.fixture(scope="module")
def gate():
    return validate_pir.load_schema(), validate_pir.blame_patterns(), validate_pir.vague_action_patterns()


def _packet() -> dict:
    return copy.deepcopy(yaml.safe_load(GOOD.read_text(encoding="utf-8")))


def _rules(packet: dict, gate) -> set[str]:
    return {f.rule for f in validate_pir.validate_packet(packet, *gate).items}


# ------------------------------------------------------------------------ the blame lexicon


@pytest.mark.parametrize(
    "text",
    [
        "Human-error",
        "Humanerror",
        f"Human{NBSP}error",
        f"Hum{CYRILLIC_A}n error",
        f"Human er{ZWSP}ror",
        "**Human** **error**",
        "care-lessly",
        "recklessly and irresponsibly",
        "culpable",
        "inattentive",
        "should be disciplined",
        "user error",
        "pilot error",
        "fat-fingered the config",
        "this was their fault",
        "they should have tested it",
        "should've known",
        "lazily",
        "blaming the deployer",
        "placed on a performance improvement plan",
    ],
)
def test_blame_evasions_are_caught(text: str) -> None:
    assert validate_pir.blame_terms_in(
        f"In the end {text}, as the record shows.", validate_pir.blame_patterns()
    )


@pytest.mark.parametrize(
    "text",
    [
        "The review is blameless.",
        "Lazy loading of the pool configuration.",
        "Settings are lazily evaluated at start-up.",
        "The pods and their fault tolerance held.",
        "A fault domain boundary was crossed.",
        "The canary should have caught it.",
        "The alert failed to fire for ten minutes.",
        "A configuration mistake reached production.",
        "The users saw an error page.",
    ],
)
def test_legitimate_process_prose_is_not_blame(text: str) -> None:
    assert validate_pir.blame_terms_in(text, validate_pir.blame_patterns()) == []


def test_the_review_holds_all_of_its_own_prose_to_the_lexicon() -> None:
    schema = validate_pir_review.load_schema()
    base = json.loads(GO_REVIEW.read_text(encoding="utf-8"))
    assert "REVIEW-BLAME-LANGUAGE" not in {
        f.rule for f in validate_pir_review.validate_review(base, schema).items
    }
    for mutate, path in (
        (
            lambda r: r.__setitem__("summary", "Sound, though the outage was human error by the deployer."),
            "$.summary",
        ),
        (lambda r: r.__setitem__("notes", ["The deployer was negligent."]), "$.notes[0]"),
        (lambda r: r["findings"][0].__setitem__("target", "careless engineer"), "$.findings[0].target"),
    ):
        review = copy.deepcopy(base)
        mutate(review)
        found = [
            f
            for f in validate_pir_review.validate_review(review, schema).items
            if f.rule == "REVIEW-BLAME-LANGUAGE"
        ]
        assert [f.path for f in found] == [path]


def test_rule_ids_naming_blame_are_not_blame() -> None:
    """'PIR-BLAME-LANGUAGE' contains 'blame'; the review's closed vocabulary is not prose."""
    review = json.loads(GO_REVIEW.read_text(encoding="utf-8"))
    paths = [path for path, _ in validate_pir_review.review_prose(review)]
    assert "$.gate_evidence.rule_ids[0]" not in paths and not any(
        ".rule" in p or "category" in p for p in paths
    )


# ------------------------------------------------------------- placeholders and evidence


@pytest.mark.parametrize(
    "owner",
    [
        "TBC",
        "the team",
        "@someone",
        "N/A (tbd)",
        "Owner: TBD",
        "???",
        "To be decided",
        "nobody",
        "unassigned",
        "pending",
        "n.a.",
        "Unknown!",
        "TBD (will confirm)",
        "Product owner",
        "HUMAN_CONFIRM_OWNER",
        "HUMAN_CONFIRM: ask the team",
        "-",
        "None yet",
        "the on-call engineer",
    ],
)
def test_owners_that_name_nobody_accountable_are_caught(owner: str) -> None:
    assert validate_pir.is_placeholder_owner(owner), owner


@pytest.mark.parametrize(
    "owner",
    [
        "Order Capture product owner (A. Example)",
        "Platform team",
        "A. Example",
        "Order Capture SRE",
        "Change Management practice lead",
        "D. Case (Change Management practice lead)",
    ],
)
def test_accountable_owners_pass(owner: str) -> None:
    assert not validate_pir.is_placeholder_owner(owner), owner


@pytest.mark.parametrize(
    "answerer", ["ChatGPT", "Claude", "Copilot", "me", "the assistant", "Product owner", "TBD"]
)
def test_answerers_who_cannot_be_asked_are_generic(answerer: str) -> None:
    assert validate_pir_ledger.generic_answerer(answerer), answerer


def test_a_named_person_with_a_role_is_not_generic() -> None:
    assert validate_pir_ledger.generic_answerer("Product Owner Smith") is None
    assert validate_pir_ledger.generic_answerer("A. Example (Order Capture product owner)") is None


@pytest.mark.parametrize(
    "evidence", ["TBD", "...", "n/a", "see above", "Various", "Nothing.", "-", "Prevents recurrence."]
)
def test_evidence_that_cites_nothing_is_caught(evidence: str) -> None:
    assert validate_pir.evidence_placeholder(evidence), evidence


@pytest.mark.parametrize(
    "evidence",
    [
        "Grafana: order-capture overview, error-rate panel",
        "None of the three alerts fired (alertmanager log)",
        "Unknown-host errors in the API log from 09:11",
    ],
)
def test_real_evidence_passes(evidence: str) -> None:
    assert validate_pir.evidence_placeholder(evidence) is None


@pytest.mark.parametrize("answer", ["No", "None", "Yes, from 09:12.", "Not determined: the logs rotated."])
def test_short_real_answers_are_answers(answer: str) -> None:
    assert validate_pir_ledger.non_answer(answer) is None


@pytest.mark.parametrize("answer", ["TBD", "   ", "pending", "???", "Unknown."])
def test_non_answers_are_caught(answer: str) -> None:
    assert validate_pir_ledger.non_answer(answer)


def test_every_evidence_field_is_checked(gate) -> None:
    packet = _packet()
    targets = [path for path, _ in validate_pir.evidence_fields(packet)]
    for prefix in (
        "$.timeline[0].evidence",
        "$.metrics.figures[0].source",
        "$.customer_impact.how_counted",
        "$.response_analysis.missed[0].gap",
        "$.response_analysis.missed[0].effect",
        "$.five_whys[0].whys[0].evidence",
        "$.action_items[0].prevents_recurrence",
    ):
        assert prefix in targets, prefix


# ---------------------------------------------------------------------------- dates


@pytest.mark.parametrize(
    ("pointer", "value"),
    [
        ("/document_control/timestamps/impact_start", "2026-09-03T25:00:00+10:00"),
        ("/document_control/timestamps/resolved_at", "2026-02-30T09:12:00+10:00"),
        ("/document_control/timestamps/detected_at", "2026-09-03T09:21:00+24:00"),
        ("/document_control/draft_due", "2026-13-01"),
        ("/timeline/0/at", "2026-09-03T09:61:00+10:00"),
        ("/action_items/0/due_date", "2026-02-30"),
        ("/review/open_questions/0/answer_due", "2026-04-31"),
    ],
)
def test_every_date_the_calendar_rejects_is_reported(pointer: str, value: str, gate) -> None:
    packet = _packet()
    pir_fixtures.apply_mutation(packet, {"op": "replace", "path": pointer, "value": value})
    findings = [f for f in validate_pir.validate_packet(packet, *gate).items if f.rule == "PIR-DATE-INVALID"]
    assert len(findings) == 1 and findings[0].severity == "error"


def test_a_malformed_date_is_the_schemas_finding_not_this_rule(gate) -> None:
    packet = _packet()
    packet["action_items"][0]["due_date"] = "next week"
    rules = _rules(packet, gate)
    assert "PIR-SCHEMA" in rules and "PIR-DATE-INVALID" not in rules


# ---------------------------------------------------------------- timings and cancellations


def test_a_float_timing_equal_to_the_derived_one_passes(gate) -> None:
    packet = _packet()
    packet["key_timings"]["time_to_detect_minutes"] = float(packet["key_timings"]["time_to_detect_minutes"])
    assert "PIR-TIMINGS-DECLARED" not in _rules(packet, gate)


def test_one_live_action_item_is_enough_for_a_corrective_action(gate) -> None:
    packet = _packet()
    packet["action_items"][0]["status"] = "cancelled"  # AI-2 still implements CA-1
    assert "PIR-CA-NO-AI" not in _rules(packet, gate)


# ------------------------------------------------------------------- pointers and questions


@pytest.mark.parametrize("segment", ["-1", "+1", " 1", "01"])
def test_only_canonical_array_indices_resolve(segment: str) -> None:
    with pytest.raises(json_pointer.PointerError, match="not a list index"):
        json_pointer.resolve({"rows": [1, 2, 3]}, f"/rows/{segment}")


def test_canonical_indices_still_resolve() -> None:
    assert json_pointer.resolve({"rows": [1, 2, 3]}, "/rows/0") == 1
    assert json_pointer.resolve({"rows": list(range(11))}, "/rows/10") == 10


def test_an_external_interview_is_refused_too() -> None:
    schema = validate_pir_ledger.load_schema()
    ledger = yaml.safe_load(RESOLVED.read_text(encoding="utf-8"))
    ledger["scope"]["interview"] = "external:SRE/interviews/order-capture-I01.yaml"
    found = [
        f
        for f in validate_pir_ledger.validate_ledger(ledger, schema).items
        if f.rule == "LEDGER-SCOPE-EXTERNAL"
    ]
    assert [f.path for f in found] == ["$.scope.interview"]


def test_external_evidence_is_still_only_reported() -> None:
    """source_artifacts and answer_source may live elsewhere; only the two files the ledger is held against may not."""
    schema = validate_pir_ledger.load_schema()
    ledger = yaml.safe_load(RESOLVED.read_text(encoding="utf-8"))
    findings = validate_pir_ledger.validate_ledger(ledger, schema)
    assert not findings.errors and findings.external


# ------------------------------------------------------------------------- summary


@pytest.mark.parametrize(
    "summary",
    [
        "Order Capture API errors decreased in a separate marketing push; 11% of submissions failed.",
        "Order Capture API may fail again; 11% of submissions failed in the window.",
        "Order Capture API failed (INC-2026-0412); 11% of submissions failed.",
        "Order Capture API failed for 74 minutes at 09:12; 11% of submissions failed.",
    ],
)
def test_a_summary_that_does_not_say_when_is_caught(summary: str, gate) -> None:
    packet = _packet()
    packet["summary"] = summary
    assert "PIR-SUMMARY-DATE" in _rules(packet, gate)


@pytest.mark.parametrize(
    "when",
    [
        "on 3 September 2026",
        "on the third of September",
        "on Sep 3",
        "in September 2026",
        "on 2026-09-03",
        "on 3/9",
    ],
)
def test_a_summary_that_says_when_passes(when: str, gate) -> None:
    packet = _packet()
    packet["summary"] = (
        f"Order Capture API experienced an 11% error rate {when}; about 4,200 submissions failed."
    )
    assert "PIR-SUMMARY-DATE" not in _rules(packet, gate)


@pytest.mark.parametrize(
    "summary",
    [
        "Order Capture API experienced errors (INC-2026-0412) on 3 September 2026.",
        "Order Capture API experienced errors from 09:12 to 10:26 on 2026-09-03 after CHG-88213.",
        "Order Capture API experienced errors on 3 September 2026; CA-1 to CA-4 follow.",
    ],
)
def test_digits_in_ids_dates_and_times_are_not_figures(summary: str, gate) -> None:
    packet = _packet()
    packet["summary"] = summary
    assert "PIR-SUMMARY-NUMBER" in _rules(packet, gate)


@pytest.mark.parametrize("figure", ["11%", "4,200 submissions", "74 minutes", "p99 of 2.4 s", "3x the norm"])
def test_a_figure_beside_an_id_counts(figure: str, gate) -> None:
    packet = _packet()
    packet["summary"] = f"Order Capture API (INC-2026-0412) on 3 September 2026: {figure}."
    assert "PIR-SUMMARY-NUMBER" not in _rules(packet, gate)


# ---------------------------------------------------------------------- vague actions


def _vague(statement: str, gate) -> list[validate_pir.Finding]:
    packet = _packet()
    packet["action_items"][0]["statement"] = statement
    return [f for f in validate_pir.validate_packet(packet, *gate).items if f.rule == "PIR-AI-VAGUE"]


@pytest.mark.parametrize(
    "statement",
    [
        "We will investigate the connection pool sizing.",
        "Team to investigate the connection pool sizing.",
        "The Order Capture team will look into pool sizing.",
        "Investigation of connection pool sizing.",
        "Look at the connection pool sizing.",
        "Analyse connection pool usage across services.",
        "Analyze connection pool usage across services.",
        "Assessment of the change policy.",
        "Raise awareness of pool limits.",
        "By 2026-10-10, review the change policy.",
        "Platform team to also evaluate pool defaults.",
        "Keep an eye on pool saturation.",
        "Investigate the alert.",
        "Re-evaluate the connection pool sizing relationship.",
        "Reassess pool defaults across services.",
    ],
)
def test_vague_openings_block(statement: str, gate) -> None:
    findings = _vague(statement, gate)
    assert [f.severity for f in findings] == [validate_pir.ERROR], statement


@pytest.mark.parametrize(
    "statement",
    [
        "Monitor pool saturation with a new alert at 80%, paging on-call, owned by the SRE champion.",
        "Investigate whether pool size must scale with concurrency, record the answer in the capacity runbook, and decide the default in the change policy.",
        "Evaluate the two pool-sizing options and choose one for the change policy.",
    ],
)
def test_a_vague_opening_that_names_its_output_is_a_warning(statement: str, gate) -> None:
    findings = _vague(statement, gate)
    assert [f.severity for f in findings] == [validate_pir.WARNING], statement


@pytest.mark.parametrize(
    "statement",
    [
        "Add an alert to monitor pool saturation at 80% of max connections.",
        "Add a saturation panel so responders can review pool state without an ad-hoc query.",
        "Engineering to add a load-test stage to the pipeline.",
        "Amend the change policy so that capacity changes are reviewed as performance-impacting.",
        "Reviewers sign off capacity changes in the change board.",
    ],
)
def test_concrete_actions_are_not_vague(statement: str, gate) -> None:
    assert _vague(statement, gate) == []


# ---------------------------------------------------------------------------- actors


@pytest.mark.parametrize(
    "root_cause",
    [
        "The engineers deployed the change without a load test.",
        "The SRE deployed the change without a load test.",
        "An operator mistakenly ran the migration twice.",
        "Change policy is weak. An SRE then ran the script by hand.",
        "Because the engineer had not tested the change, it reached production.",
        "They deployed without a canary.",
        "The on-call engineer ignored the page.",
        "The engineer raised the concurrency limit without raising the pool.",
        "Ultimately, a developer disabled the alert during the batch window.",
    ],
)
def test_a_root_cause_that_stops_at_a_person_is_caught(root_cause: str, gate) -> None:
    packet = _packet()
    packet["five_whys"][0]["root_cause"] = root_cause
    assert "PIR-ROOTCAUSE-ACTOR" in _rules(packet, gate)


@pytest.mark.parametrize(
    "root_cause",
    [
        "The on-call rota failed to include a database specialist.",
        "The deploy pipeline ran no load test for configuration changes.",
        "Engineering standards do not require a canary for configuration changes.",
        "The operator runbook omits the pool check, so responders cannot see saturation.",
        "Change policy treats capacity-affecting configuration as low risk.",
        "Responders lacked the diagnostic metric because the template omits saturation.",
        "The on-call engineer was paged 15 minutes after impact started because the alert window is 10 minutes.",
    ],
)
def test_a_process_root_cause_is_not_an_actor(root_cause: str, gate) -> None:
    packet = _packet()
    packet["five_whys"][0]["root_cause"] = root_cause
    assert "PIR-ROOTCAUSE-ACTOR" not in _rules(packet, gate)


# ------------------------------------------------------------------------ rule items


def test_honest_rounding_of_a_timing_passes_and_a_real_disagreement_does_not(gate) -> None:
    packet = _packet()
    packet["document_control"]["timestamps"]["cause_confirmed_at"] = "2026-09-03T10:05:40+10:00"
    # time to remediate is now 20 min 20 s: 20 and 21 are both honest; 22 is not.
    for declared, expected in ((20, False), (21, False), (22, True)):
        packet["key_timings"]["time_to_remediate_minutes"] = declared
        assert ("PIR-TIMINGS-DECLARED" in _rules(packet, gate)) is expected, declared


def test_a_zero_length_incident_is_reported_once_and_a_zero_detect_time_is_not(gate) -> None:
    packet = _packet()
    stamps = packet["document_control"]["timestamps"]
    stamps["detected_at"] = stamps["impact_start"]
    packet["key_timings"]["time_to_detect_minutes"] = 0
    packet["key_timings"]["time_to_know_minutes"] = 53
    assert "PIR-TIMESTAMPS-COLLAPSED" not in _rules(packet, gate)
    for key in ("cause_confirmed_at", "mitigated_at", "resolved_at"):
        stamps[key] = stamps["impact_start"]
    assert "PIR-TIMESTAMPS-COLLAPSED" in _rules(packet, gate)


@pytest.mark.parametrize(
    ("field", "due", "caught"),
    [
        ("draft_due", "2020-01-01", True),
        ("publish_due", "2026-09-02", True),
        ("draft_due", "2026-09-03", False),
        ("publish_due", "2026-09-17", False),
    ],
)
def test_a_pir_due_before_the_incident_was_mitigated_is_caught(
    field: str, due: str, caught: bool, gate
) -> None:
    packet = _packet()
    packet["document_control"][field] = due
    assert ("PIR-DUE-BEFORE-INCIDENT" in _rules(packet, gate)) is caught


@pytest.mark.parametrize(("due", "far"), [("2027-09-03", False), ("2027-09-04", True), ("2099-12-31", True)])
def test_a_due_date_more_than_a_year_out_is_caught(due: str, far: bool, gate) -> None:
    packet = _packet()
    packet["action_items"][0]["due_date"] = due
    assert ("PIR-AI-DUE-FAR" in _rules(packet, gate)) is far


@pytest.mark.parametrize(
    ("how_many", "caught"),
    [
        ("not determined: n/a", True),
        ("not determined: unknown", True),
        ("Not determined: TBD", True),
        ("not determined:", True),
        ("Some customers; see INC-2026-0412.", True),
        ("Customers between 09:12 and 10:26.", True),
        ("not determined: gateway logs for the window were rotated before the count was run", False),
        ("4,180 failed submissions from 3,090 customers", False),
    ],
)
def test_the_impact_count_and_its_escape_hatch(how_many: str, caught: bool, gate) -> None:
    packet = _packet()
    packet["customer_impact"]["how_many"] = how_many
    assert ("PIR-IMPACT-QUANTIFIED" in _rules(packet, gate)) is caught


def _go_review() -> dict:
    return copy.deepcopy(json.loads(GO_REVIEW.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    "judgement", ["OK", "Looks good.", "LGTM", "No issues.", "n/a", "Checked.", "See above."]
)
def test_a_stock_coverage_entry_records_no_judgement(judgement: str) -> None:
    review = _go_review()
    review["coverage"]["lessons"] = judgement
    findings = validate_pir_review.validate_review(review, validate_pir_review.load_schema())
    assert any(f.rule == "REVIEW-COVERAGE" and f.path == "$.coverage.lessons" for f in findings.items), (
        judgement
    )


def test_a_coverage_entry_may_open_with_no_issues_and_say_what_was_checked() -> None:
    review = _go_review()
    review["coverage"]["lessons"] = (
        "No issues: each lesson traces to its root cause and says what was believed."
    )
    findings = validate_pir_review.validate_review(review, validate_pir_review.load_schema())
    assert findings.items == [], [f.render() for f in findings.items]


def test_coverage_is_held_to_the_blame_standard() -> None:
    review = _go_review()
    review["coverage"]["five_whys"] = "The chains are fine, though the deployer was careless."
    findings = validate_pir_review.validate_review(review, validate_pir_review.load_schema())
    assert any(f.rule == "REVIEW-BLAME-LANGUAGE" and f.path == "$.coverage.five_whys" for f in findings.items)


@pytest.mark.parametrize(
    ("relative", "misfiled"),
    [
        ("reviews/x.json", True),
        ("reviews/order-capture/archive/20260912T090000Z-pir-reviewer.json", True),
        ("reviews/order-capture/20260912T090000Z-pir-reviewer.json", False),
        ("elsewhere/x.json", False),
    ],
)
def test_only_the_stem_depth_is_a_review_filing(tmp_path: Path, relative: str, misfiled: bool) -> None:
    review = _go_review()
    review["subject"]["path"] = "pirs/order-capture.yaml"
    out = validate_pir_review.Findings()
    validate_pir_review.validate_filing(review, tmp_path / relative, tmp_path, out)
    assert any(f.rule == "REVIEW-FILING" for f in out.items) is misfiled
