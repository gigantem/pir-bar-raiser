#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""validate_pir.py: the PIR gate, and the producer of the gap report the interview is built from.

Two layers:

1. **Schema** (schemas/pir-packet.schema.json): presence, types, closed vocabularies, identifier
   formats. Reported as PIR-SCHEMA.
2. **Semantics**: ordering, derivation, traceability and the lexicons. Every finding carries a
   stable rule id (``PIR-...``), the template section it belongs to, a severity and a path, so
   it can be named, counted, grouped by section by the interview generator, and asserted on
   individually.

Exit code: 1 when any packet carries an error-severity finding, 0 otherwise. Warnings never
change the exit code unless ``--warnings-as-errors`` is given; they are still written to the
gap report, because the interview asks about them too.

The lexicons are read from catalogs/ so that there is one definition of "blaming" and "vague"
shared by the validator, the interview and the template appendix.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

if sys.version_info < (3, 12):  # noqa: UP036 - the floor guard is for interpreters below the target
    raise RuntimeError(
        f"validate_pir.py requires Python 3.12 or later; running under {sys.version.split()[0]}. "
        "Run the PIR tools with a Python 3.12 or later interpreter."
    )

import yaml
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA_PATH = REPO_ROOT / "schemas" / "pir-packet.schema.json"
BLAME_LEXICON_PATH = REPO_ROOT / "catalogs" / "blame-lexicon.yaml"
VAGUE_ACTION_LEXICON_PATH = REPO_ROOT / "catalogs" / "vague-action-lexicon.yaml"
SUPPORTED_SUFFIXES = {".json", ".yaml", ".yml"}

ERROR = "error"
WARNING = "warning"

# ------------------------------------------------------------------------------ the rule table
#
# Every rule this validator can emit, with the template section it belongs to and its default
# severity. tools/validate_catalogs.py asserts that catalogs/pir-section-expectations.yaml lists
# exactly these ids under exactly these sections, so a rule cannot exist without a home in the
# guidance and the guidance cannot name a rule that does not fire.
RULES: dict[str, tuple[str, str]] = {
    "PIR-SCHEMA": ("cross_cutting", ERROR),
    "PIR-BLAME-LANGUAGE": ("cross_cutting", ERROR),
    "PIR-ID-DUPLICATE": ("cross_cutting", ERROR),
    "PIR-OWNER-PLACEHOLDER": ("cross_cutting", ERROR),
    "PIR-DATE-INVALID": ("cross_cutting", ERROR),
    "PIR-EVIDENCE-PLACEHOLDER": ("cross_cutting", ERROR),
    "PIR-TIME-ORDER": ("document_control", ERROR),
    "PIR-TIMESTAMPS-COLLAPSED": ("document_control", ERROR),
    "PIR-TIMINGS-DECLARED": ("document_control", ERROR),
    "PIR-DUE-DRAFT-LATE": ("document_control", WARNING),
    "PIR-DUE-PUBLISH-LATE": ("document_control", WARNING),
    "PIR-DUE-BEFORE-INCIDENT": ("document_control", ERROR),
    "PIR-SUMMARY-SERVICE": ("summary", ERROR),
    "PIR-SUMMARY-NUMBER": ("summary", ERROR),
    "PIR-SUMMARY-DATE": ("summary", ERROR),
    "PIR-TIMELINE-ORDER": ("timeline", ERROR),
    "PIR-TIMELINE-PHASE-MISSING": ("timeline", ERROR),
    "PIR-TIMELINE-ANCHOR": ("timeline", ERROR),
    "PIR-TIMELINE-NO-DIAGNOSIS": ("timeline", WARNING),
    "PIR-FIGURES-NONE": ("metrics", ERROR),
    "PIR-FIGURE-BASELINE": ("metrics", ERROR),
    "PIR-FIGURE-ANNOTATED": ("metrics", ERROR),
    "PIR-METRIC-SUMMARY-EMPTY": ("metrics", ERROR),
    "PIR-METRIC-AVERAGE": ("metrics", WARNING),
    "PIR-IMPACT-QUANTIFIED": ("customer_impact", ERROR),
    "PIR-IMPACT-DURATION": ("customer_impact", ERROR),
    "PIR-MISSED-AREAS": ("response_analysis", ERROR),
    "PIR-CHANNELS-NONE": ("response_analysis", ERROR),
    "PIR-CHANNEL-NO-CHAIN": ("response_analysis", ERROR),
    "PIR-CHAIN-UNKNOWN-CHANNEL": ("response_analysis", ERROR),
    "PIR-CHAIN-KINDS": ("five_whys", ERROR),
    "PIR-CHAIN-PRIOR-ACTIONS": ("five_whys", ERROR),
    "PIR-WHY-DEPTH": ("five_whys", ERROR),
    "PIR-WHY-SHALLOW": ("five_whys", WARNING),
    "PIR-ROOTCAUSE-ACTOR": ("five_whys", ERROR),
    "PIR-WHY-REPEATED": ("five_whys", WARNING),
    "PIR-CHAIN-DUPLICATE": ("five_whys", WARNING),
    "PIR-LESSONS-NONE": ("lessons", ERROR),
    "PIR-LESSON-RC-UNKNOWN": ("lessons", ERROR),
    "PIR-RC-NO-LESSON": ("lessons", ERROR),
    "PIR-CA-NONE": ("corrective_actions", ERROR),
    "PIR-CA-LL-UNKNOWN": ("corrective_actions", ERROR),
    "PIR-LESSON-NO-CA": ("corrective_actions", ERROR),
    "PIR-CA-NO-HALVING": ("corrective_actions", WARNING),
    "PIR-AI-NONE": ("action_items", ERROR),
    "PIR-AI-CA-UNKNOWN": ("action_items", ERROR),
    "PIR-CA-NO-AI": ("action_items", ERROR),
    "PIR-AI-VAGUE": ("action_items", ERROR),
    "PIR-AI-NOT-AGREED": ("action_items", ERROR),
    "PIR-AI-DUE-BEFORE-INCIDENT": ("action_items", ERROR),
    "PIR-AI-DUE-FAR": ("action_items", ERROR),
    "PIR-GO-REVIEW-NO-TEAM": ("review", ERROR),
    "PIR-PUBLISHED-NO-REVIEW": ("review", ERROR),
    "PIR-PUBLISHED-OPEN-QUESTION": ("review", ERROR),
}

#: Minimum whys for a chain to count as a chain; below WHY_TYPICAL_FLOOR it is a warning.
WHY_MINIMUM = 3
WHY_TYPICAL_FLOOR = 4

#: The deck: draft within 2 to 3 business days, publish within 1 to 2 weeks. Calendar
#: approximations, so the rule stays a warning rather than a verdict on a public holiday.
DRAFT_DUE_MAX_DAYS = 5
PUBLISH_DUE_MAX_DAYS = 14

#: An action item is a concrete, trackable step. One due more than a year after the incident was
#: resolved is a placeholder date ("2099-12-31") or a programme; a programme is tracked as dated
#: milestones within the year.
ACTION_DUE_MAX_DAYS = 365

#: Values that name nobody, matched against the whole value once it is normalised (lower case,
#: whitespace collapsed, surrounding punctuation and a leading article removed; see `core_text`).
#: A denylist: it proves a value IS a placeholder, never that a value IS a person or a team.
PLACEHOLDER_OWNERS: tuple[str, ...] = (
    "tbd",
    "tba",
    "tbc",
    "todo",
    "unknown",
    "n/a",
    "na",
    "n.a",
    "none",
    "nobody",
    "no one",
    "unassigned",
    "pending",
    "owner",
    "someone",
    "anyone",
    "everyone",
)

#: Bare role words: they say what someone does, not who agreed (accountability is named). Whole-value
#: only, so "Order Capture product owner (A. Example)" and "Platform team" still pass.
ROLE_WORDS: tuple[str, ...] = (
    "product owner",
    "pir owner",
    "service owner",
    "source owner",
    "team",
    "team lead",
    "lead",
    "manager",
    "engineering manager",
    "incident manager",
    "engineer",
    "developer",
    "operator",
    "on-call",
    "on call",
    "oncall",
    "on-call engineer",
    "facilitator",
)

#: Marks of unfinished text that no name, answer or piece of evidence carries, wherever they appear:
#: "Owner: TBD", "N/A (tbc)", "HUMAN_CONFIRM_OWNER", "???".
PLACEHOLDER_MARKS = re.compile(
    r"\b(?:tbd|tba|tbc|todo|fixme)\b|human_confirm|assessor_judgement_required|\?{2,}"
    r"|\bto be (?:decided|confirmed|determined|assigned|agreed)\b",
    re.IGNORECASE,
)

#: A value that opens by naming nobody: "None yet", "Pending confirmation", "Unknown at this time".
#: Owners and answerers only; evidence may legitimately open with "None of the three alerts fired".
LEADING_PLACEHOLDER = re.compile(r"^(?:unknown|n/?a|none|nobody|no one|unassigned|pending|someone|anyone)\b")

#: Whole values that cite no evidence and claim no effect.
EVIDENCE_PLACEHOLDERS: frozenset[str] = frozenset(
    (
        *PLACEHOLDER_OWNERS,
        "see above",
        "see below",
        "as above",
        "same as above",
        "same",
        "ditto",
        "various",
        "misc",
        "other",
        "nothing",
        "evidence",
        "link",
        "url",
        "here",
        "yes",
        "no",
        "ok",
        "prevents recurrence",
        "will prevent recurrence",
        "stops recurrence",
    )
)

#: Characters that render as nothing yet split a word for a regex: zero-width space, non-joiner,
#: joiner, word joiner, byte-order mark, soft hyphen.
INVISIBLE = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad]")

#: Cyrillic and Greek letters that render like Latin ones, so "human error" typed with a Cyrillic "a"
#: is still "human error". str.maketrans raises if the two sides ever differ in length.
CONFUSABLES = str.maketrans(
    "\u0430\u0435\u043e\u0440\u0441\u0443\u0445\u0456\u0458\u0455\u0501\u04cf\u043a\u043c\u043d\u0442\u0432"
    "\u0410\u0412\u0415\u041a\u041c\u041d\u041e\u0420\u0421\u0422\u0425\u0406\u0408\u0405"
    "\u03b1\u03bf\u03c1\u03b9\u03ba\u03bd\u03c5"
    "\u0391\u0392\u0395\u0397\u0399\u039a\u039c\u039d\u039f\u03a1\u03a4\u03a5\u03a7\u0396",
    "aeopcyxijsdlkmhtbABEKMHOPCTXIJSaopikvuABEHIKMNOPTYXZ",
)

#: Runs of whitespace, hyphens and dashes, underscores and markdown emphasis between words.
SEPARATORS = re.compile(r"[\s\-\u2010-\u2015\u2212_*~`]+")
#: The same characters inside a word ("care-lessly"), which a reader's eye joins.
INTRAWORD = re.compile(r"(?<=[^\W_])[\-\u2010-\u2015\u2212_*~`]+(?=[^\W_])")

#: Timeline phases that must appear, and the lifecycle timestamp each must agree with.
ANCHORED_PHASES: dict[str, str] = {
    "impact_start": "impact_start",
    "detection": "detected_at",
    "mitigated": "mitigated_at",
    "resolved": "resolved_at",
}

REQUIRED_MISSED_AREAS = ("detection", "diagnosis", "remediation")
REQUIRED_CHAIN_KINDS = ("failure", "detection", "resolution")
HALVING_IMPROVEMENTS = frozenset({"ttd", "ttk", "ttr"})

#: A sentence of a root cause whose subject is a person and whose verb is what they did: one why
#: short of the process. Subject position only, sentence by sentence: "The on-call rota
#: failed to include a database specialist" names a rota, not a person, and passes; "The engineers
#: deployed" and a second sentence "An SRE then ran the script" do not.
ACTOR_NOUNS = (
    r"(?:engineers?|operators?|developers?|devs?|sres?|dbas?|admins?|administrators?|responders?|"
    r"on-?call(?:\s+(?:engineers?|responders?|persons?|people|staff))?|persons?|people|individuals?|"
    r"team\s+members?|staff(?:\s+members?)?|employees?|contractors?|someone|somebody|he|she|they)"
)
#: What a person did, past tense and active: an explicit list rather than any "-ed" word, so a cause
#: phrased from the responder's side ("Responders lacked the diagnostic metric") is not mistaken
#: for one. Passive forms ("The engineer was paged") are not actions and are not matched.
ACTOR_VERBS = (
    r"(?:made|forgot|missed|failed|ran|changed|deployed|typed|clicked|pushed|merged|ignored|overlooked|"
    r"skipped|approved|misconfigured|mistyped|misread|executed|applied|released|restarted|deleted|dropped|"
    r"removed|entered|chose|decided|neglected|committed|rolled|raised|lowered|increased|reduced|decreased|"
    r"set|modified|edited|updated|upgraded|downgraded|configured|reconfigured|disabled|enabled|turned|"
    r"killed|stopped|started|triggered|scaled|resized|migrated|shipped|reverted|bypassed|overrode|"
    r"silenced|muted|snoozed|acknowledged|closed|assumed|used|tested|put|took|wrote|broke|left|sent|"
    r"(?:did|had|has|have|was|were|could|would)(?:\s+not|n't|nt)\s+\w+|should\s+have\s+\w+)"
)
ACTOR_ROOT_CAUSE = re.compile(
    r"^\s*(?:[a-z]+,\s+)?(?:(?:because|when|after|since|as|so)\s+)?"
    r"(?:(?:the|an?|our|one|two|three|several|some|a\s+few|multiple|both|that|this)\s+)?"
    r"(?:[\w-]+\s+){0,2}?" + ACTOR_NOUNS + r"\s+"
    r"(?:(?:had|has|have|then|also|accidentally|mistakenly|inadvertently|wrongly|incorrectly|"
    r"manually|just|simply|never)\s+)*" + ACTOR_VERBS + r"\b",
    re.IGNORECASE,
)
SENTENCE_BREAK = re.compile(r"(?<=[.!?;])\s+")
AVERAGE_WORDS = re.compile(r"\b(?:average|avg|mean)\b", re.IGNORECASE)
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_DAY = (
    r"(?:[0-3]?\d(?:st|nd|rd|th)?|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    r"eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|nineteenth|"
    r"twentieth|thirtieth|(?:twenty|thirty)[\s-](?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth))"
)
_YEAR = r"(?:19|20)\d{2}"
#: A summary says when: a year, a numeric date, or a month next to a day or a year ("3 September",
#: "the third of September", "Sep 3", "September 2026"). A month prefix inside another word
#: ("decreased", "separate", "marketing") or a bare "may" is not a date.
SUMMARY_DATE = re.compile(
    rf"\b{_YEAR}\b|\b\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?\b"
    rf"|\b{_DAY}(?:\s+of)?\s+{_MONTH}\b|\b{_MONTH}\.?\s+(?:{_DAY}|{_YEAR})\b",
    re.IGNORECASE,
)
#: An identifier with digits in it: "INC-2026-0412", "CHG-88213", "CA-1", "p99". Its digits are neither a
#: figure nor a date ("INC-2026-0412" is not "in 2026").
ID_TOKEN = re.compile(r"\b[A-Za-z]+(?:[-_/.]?[A-Za-z]*\d)+[A-Za-z]*\b")
#: Digits that are not figures: identifiers, ISO dates and timestamps, times of day, and dates in
#: words. What is left must carry the figure.
NOT_A_FIGURE = re.compile(
    rf"{ID_TOKEN.pattern}"
    rf"|\b\d{{4}}-\d{{2}}-\d{{2}}(?:T[0-9:.]+(?:Z|[+-]\d{{2}}:?\d{{2}})?)?"
    rf"|\b\d{{1,2}}:\d{{2}}(?::\d{{2}})?\b"
    rf"|{SUMMARY_DATE.pattern}",
    re.IGNORECASE,
)
DIGIT = re.compile(r"\d")
NOT_DETERMINED = "not determined:"


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    section: str
    message: str
    path: str = ""

    def render(self) -> str:
        where = f" (at {self.path})" if self.path else ""
        return f"{self.rule}: {self.message}{where}"


class Findings:
    """Accumulates findings; `rule()` is the only way to add one, so every id is in RULES."""

    def __init__(self) -> None:
        self.items: list[Finding] = []

    def rule(self, rule_id: str, message: str, path: str = "", severity: str | None = None) -> None:
        if rule_id not in RULES:
            raise KeyError(f"unregistered rule id {rule_id}; add it to RULES and the catalog")
        section, default_severity = RULES[rule_id]
        self.items.append(Finding(rule_id, severity or default_severity, section, message, path))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.items if f.severity == ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.items if f.severity == WARNING]


# ------------------------------------------------------------------------------------- loading


#: The largest artifact any tool will read: some forty times the largest worked example (26 KB). A file
#: above it is refused unread.
MAX_DOCUMENT_BYTES = 1 << 20


class NoAliasLoader(yaml.SafeLoader):
    """SafeLoader that refuses YAML aliases. `safe_load` expands every alias, so a few hundred bytes
    of nested anchors become millions of nodes (210 bytes can make 262,144). No PIR artifact
    needs an alias; an anchor alone is harmless and still parses."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()
            raise yaml.composer.ComposerError(
                None,
                None,
                "YAML aliases (*name, <<: *name) are not accepted in a PIR artifact",
                event.start_mark,
            )
        return super().compose_node(parent, index)


def parse_document(path: Path, *, yaml_for_any_suffix: bool = False) -> Any:
    """The parsed content of a YAML or JSON artifact, refusing an oversized file and any YAML alias.

    `.json` is read as JSON; `.yaml` and `.yml` as YAML, and so is any other suffix when
    `yaml_for_any_suffix` is set; otherwise another suffix is an error."""
    size = path.stat().st_size
    if size > MAX_DOCUMENT_BYTES:
        raise ValueError(f"{path} is {size} bytes; an artifact may be at most {MAX_DOCUMENT_BYTES} bytes")
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    if path.suffix in {".yaml", ".yml"} or yaml_for_any_suffix:
        return yaml.load(text, Loader=NoAliasLoader)  # a SafeLoader subclass: no arbitrary objects
    raise ValueError(
        f"unsupported packet format '{path.suffix}'; expected one of {sorted(SUPPORTED_SUFFIXES)}"
    )


def contained_path(reference: str, repo_root: Path) -> Path | None:
    """`repo_root / reference` when it stays inside `repo_root`, else None.

    A cited path is joined onto the root and then read, and `root / "/etc/x"` is `/etc/x`, so an
    absolute reference, a drive or a `..` that climbs out, or a symbolic link leading out, is refused
    before anything is opened."""
    if PurePosixPath(reference).is_absolute() or PureWindowsPath(reference).anchor:
        return None
    target = repo_root / reference
    try:
        target.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return None
    return target


def load_document(path: Path) -> dict[str, Any]:
    data = parse_document(path)
    if not isinstance(data, dict):
        raise ValueError("packet root must be a mapping")
    return data


def load_schema(path: Path = DEFAULT_SCHEMA_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        schema = json.load(handle)
    if not isinstance(schema, dict):
        raise ValueError("schema root must be a JSON object")
    return schema


def load_lexicon_terms(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    terms = data.get("terms") if isinstance(data, dict) else None
    if not isinstance(terms, list) or not terms:
        raise ValueError(
            f"{path} carries no terms; a lexicon with nothing in it would silently disable a rule"
        )
    return terms


def blame_patterns(path: Path = BLAME_LEXICON_PATH) -> list[tuple[str, re.Pattern[str]]]:
    return [(str(t["term"]), re.compile(str(t["pattern"]), re.IGNORECASE)) for t in load_lexicon_terms(path)]


#: Who may open an action item before its verb, and the modal that hands them the work:
#: "We will", "Platform team to", "The SRE practice must", "To". A subject is a pronoun or a phrase
#: that ends in a group word, so "Add an alert to monitor X" does not read as "<subject> to monitor".
VAGUE_SUBJECT = (
    r"(?:we|they|i|(?:(?:the|our)\s+)?(?:[\w&/]+\s+){0,3}?(?:team|teams|squad|group|owner|owners|lead|leads|"
    r"champion|champions|practice|function|sre|sres|ops|dba|dbas|engineering|platform|on\s?call|coe))"
)
VAGUE_MODAL = (
    r"(?:will|shall|should|must|to|needs?\s+to|is\s+to|are\s+to|(?:is|are)\s+going\s+to|plans?\s+to|"
    r"intends?\s+to|agreed\s+to)"
)
VAGUE_PREAMBLE = rf"(?:(?:{VAGUE_SUBJECT})\s+)?{VAGUE_MODAL}\s+(?:(?:also|then|further|first|jointly)\s+)?"
#: Where a clause of an action item's first sentence starts.
CLAUSE_BREAK = re.compile(r"[,;:]\s*|\s+-\s+")


@dataclass(frozen=True)
class VagueTerm:
    """One vague-action lexicon entry, compiled: `opening` matches a clause that opens with one of
    its forms; `satisfied_by`, when present, matches the concrete output its remediation names."""

    term: str
    opening: re.Pattern[str]
    satisfied_by: re.Pattern[str] | None


def vague_action_patterns(path: Path = VAGUE_ACTION_LEXICON_PATH) -> list[VagueTerm]:
    compiled = []
    for entry in load_lexicon_terms(path):
        forms = entry.get("forms") or [entry["term"]]
        # Forms are read as the statement is: hyphens, dashes and spaces are one separator.
        alternatives = "|".join(
            r"\s+".join(re.escape(word) for word in SEPARATORS.split(str(form)) if word)
            for form in [entry["term"], *forms]
        )
        satisfied = entry.get("satisfied_by")
        compiled.append(
            VagueTerm(
                str(entry["term"]),
                re.compile(rf"^\W*(?:{VAGUE_PREAMBLE})?(?:{alternatives})\b", re.IGNORECASE),
                re.compile(str(satisfied), re.IGNORECASE) if satisfied else None,
            )
        )
    return compiled


def vague_opening(statement: str, vague: list[VagueTerm]) -> VagueTerm | None:
    """The lexicon term that opens the statement, or any clause of its first sentence, or None."""
    collapsed = lexicon_views(statement)[0].strip()
    first_sentence = re.split(r"(?<=[.!?])\s+", collapsed, maxsplit=1)[0]
    for clause in CLAUSE_BREAK.split(first_sentence):
        for entry in vague:
            if entry.opening.search(clause):
                return entry
    return None


def has_figure(text: str) -> bool:
    """True when `text` carries a digit that is a figure rather than part of an id, a date or a time."""
    return DIGIT.search(NOT_A_FIGURE.sub(" ", text)) is not None


# ------------------------------------------------------------------------------------- helpers


def format_error_path(error_path: list[Any]) -> str:
    formatted = "$"
    for item in error_path:
        formatted += f"[{item}]" if isinstance(item, int) else f".{item}"
    return formatted


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def whole_minutes(later: datetime, earlier: datetime) -> int:
    return int((later - earlier).total_seconds() // 60)


#: Each of the deck's five timings as the pair of lifecycle instants it runs between.
KEY_TIMING_SPANS: dict[str, tuple[str, str]] = {
    "time_to_detect_minutes": ("detected_at", "impact_start"),
    "time_to_know_minutes": ("cause_confirmed_at", "detected_at"),
    "time_to_remediate_minutes": ("mitigated_at", "cause_confirmed_at"),
    "customer_impact_minutes": ("mitigated_at", "impact_start"),
    "time_to_resolve_minutes": ("resolved_at", "impact_start"),
}


def derive_key_timings(timestamps: dict[str, datetime]) -> dict[str, int]:
    """The deck's five timings, in whole minutes, from the five lifecycle instants."""
    return {
        key: whole_minutes(timestamps[later], timestamps[earlier])
        for key, (later, earlier) in KEY_TIMING_SPANS.items()
    }


def exact_key_timings(timestamps: dict[str, datetime]) -> dict[str, float]:
    """The same five timings in exact (fractional) minutes, so honest rounding can be told from error."""
    return {
        key: (timestamps[later] - timestamps[earlier]).total_seconds() / 60
        for key, (later, earlier) in KEY_TIMING_SPANS.items()
    }


def core_text(value: str) -> str:
    """`value` lower-cased and compared as a whole: whitespace collapsed, surrounding punctuation and a
    leading article removed. An empty result means the value was nothing but punctuation."""
    core = " ".join(unicodedata.normalize("NFKC", value).lower().split())
    core = core.strip(" .,:;!?'\"`*_-()[]{}<>@/\\\u2010\u2011\u2012\u2013\u2014\u2015\u2026")
    return re.sub(r"^(?:the|an?)\s+", "", core)


def placeholder_mark(value: Any) -> str | None:
    """The unfinished-text mark anywhere in `value`, or None."""
    if not isinstance(value, str):
        return None
    match = PLACEHOLDER_MARKS.search(value)
    return match.group() if match else None


def owner_placeholder(value: Any) -> str | None:
    """Why `value` names nobody accountable (a placeholder, a bare role, nothing), or None."""
    if not isinstance(value, str):
        return None
    mark = placeholder_mark(value)
    if mark:
        return mark
    core = core_text(value)
    if not core:
        return "nothing but punctuation"
    if core in PLACEHOLDER_OWNERS or core in ROLE_WORDS:
        return core
    leading = LEADING_PLACEHOLDER.match(core)
    return leading.group() if leading else None


def is_placeholder_owner(value: Any) -> bool:
    return owner_placeholder(value) is not None


def evidence_placeholder(value: Any) -> str | None:
    """Why `value` cites nothing (a placeholder mark, a stock non-answer, nothing), or None."""
    if not isinstance(value, str):
        return None
    mark = placeholder_mark(value)
    if mark:
        return mark
    core = core_text(value)
    if not core:
        return "nothing but punctuation"
    return core if core in EVIDENCE_PLACEHOLDERS else None


def lexicon_views(text: str) -> tuple[str, str]:
    """`text` as the blame lexicon reads it, twice: with separators collapsed to one space
    ("Human-error" -> "Human error") and with in-word separators removed ("care-lessly" ->
    "carelessly"). Both are Unicode-folded, stripped of invisible characters and lookalikes."""
    folded = INVISIBLE.sub("", unicodedata.normalize("NFKC", text)).translate(CONFUSABLES)
    return SEPARATORS.sub(" ", folded), SEPARATORS.sub(" ", INTRAWORD.sub("", folded))


def blame_terms_in(text: str, patterns: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    """Every lexicon term found in either view of `text`."""
    views = lexicon_views(text)
    return [term for term, pattern in patterns if any(pattern.search(view) for view in views)]


def iter_strings(node: Any, path: str = "$"):
    """Every string in the document with its path, for whole-document lexicon checks."""
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from iter_strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from iter_strings(value, f"{path}[{index}]")


def mapping(value: object) -> dict[str, Any]:
    """`value` when it is a mapping, else an empty one: how a rule reads an optional section, so a
    missing or malformed section is reported by its own rule rather than crashing this one."""
    return value if isinstance(value, dict) else {}


def sequence(value: object) -> list[Any]:
    """`value` when it is a list, else an empty one; the list twin of `mapping`."""
    return value if isinstance(value, list) else []


def ids_of(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    return [str(item["id"]) for item in items if isinstance(item, dict) and "id" in item]


# ------------------------------------------------------------------------------------- schema


def validate_schema(packet: dict[str, Any], schema: dict[str, Any], out: Findings) -> None:
    validator = Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(packet), key=lambda item: list(item.path)):
        out.rule("PIR-SCHEMA", f"schema violation: {error.message}", format_error_path(list(error.path)))


# ------------------------------------------------------------------------------ cross-cutting


def validate_blame_language(
    packet: dict[str, Any], out: Findings, patterns: list[tuple[str, re.Pattern[str]]]
) -> None:
    for path, text in iter_strings(packet):
        for term in blame_terms_in(text, patterns):
            out.rule(
                "PIR-BLAME-LANGUAGE",
                f"'{term}' makes this about a person, not a process; restate the gap in process, design or tooling terms",
                path,
            )


def validate_unique_ids(packet: dict[str, Any], out: Findings) -> None:
    # Timeline rows carry no id, so the timeline is not listed: an entry for it would check nothing.
    collections = {
        "$.metrics.figures": ids_of(
            (packet.get("metrics") or {}).get("figures") if isinstance(packet.get("metrics"), dict) else None
        ),
        "$.response_analysis.channels_of_inquiry": ids_of(
            (packet.get("response_analysis") or {}).get("channels_of_inquiry")
            if isinstance(packet.get("response_analysis"), dict)
            else None
        ),
        "$.five_whys": ids_of(packet.get("five_whys")),
        "$.lessons": ids_of(packet.get("lessons")),
        "$.corrective_actions": ids_of(packet.get("corrective_actions")),
        "$.action_items": ids_of(packet.get("action_items")),
        "$.review.open_questions": ids_of(
            (packet.get("review") or {}).get("open_questions")
            if isinstance(packet.get("review"), dict)
            else None
        ),
    }
    for path, ids in collections.items():
        seen: set[str] = set()
        for identifier in ids:
            if identifier in seen:
                out.rule("PIR-ID-DUPLICATE", f"{identifier} appears more than once", path)
            seen.add(identifier)


def validate_owners(packet: dict[str, Any], out: Findings) -> None:
    control = packet.get("document_control")
    reason = owner_placeholder(control.get("pir_owner")) if isinstance(control, dict) else None
    if reason:
        out.rule(
            "PIR-OWNER-PLACEHOLDER",
            f"pir_owner names nobody accountable ({reason!r}); the product owner owns and presents the PIR",
            "$.document_control.pir_owner",
        )
    for index, item in enumerate(packet.get("action_items") or []):
        reason = owner_placeholder(item.get("owner")) if isinstance(item, dict) else None
        if reason:
            out.rule(
                "PIR-OWNER-PLACEHOLDER",
                f"{item.get('id', '<no id>')} has no accountable owner ({reason!r}); name the person or team who agreed to it",
                f"$.action_items[{index}].owner",
            )
    review = packet.get("review")
    if isinstance(review, dict):
        for index, question in enumerate(review.get("open_questions") or []):
            reason = owner_placeholder(question.get("owner")) if isinstance(question, dict) else None
            if reason:
                out.rule(
                    "PIR-OWNER-PLACEHOLDER",
                    f"{question.get('id', '<no id>')} has no accountable owner for its answer ({reason!r})",
                    f"$.review.open_questions[{index}].owner",
                )


def date_fields(packet: dict[str, Any]):
    """Every date or timestamp field in the packet: (path, value, is_timestamp)."""
    control = mapping(packet.get("document_control"))
    stamps = mapping(control.get("timestamps"))
    for key, value in stamps.items():
        yield f"$.document_control.timestamps.{key}", value, True
    for key in ("draft_due", "publish_due"):
        yield f"$.document_control.{key}", control.get(key), False
    for index, row in enumerate(packet.get("timeline") or []):
        if isinstance(row, dict):
            yield f"$.timeline[{index}].at", row.get("at"), True
    for index, item in enumerate(packet.get("action_items") or []):
        if isinstance(item, dict):
            yield f"$.action_items[{index}].due_date", item.get("due_date"), False
    review = mapping(packet.get("review"))
    for index, stage in enumerate(review.get("stages") or []):
        if isinstance(stage, dict):
            yield f"$.review.stages[{index}].date", stage.get("date"), False
    for index, question in enumerate(review.get("open_questions") or []):
        if isinstance(question, dict):
            yield f"$.review.open_questions[{index}].answer_due", question.get("answer_due"), False


def validate_dates(packet: dict[str, Any], schema: dict[str, Any], out: Findings) -> None:
    """A date the schema's shape accepts but the calendar does not (hour 25, 30 February, +24:00).

    The schema bounds digit counts only; without this rule such a value parsed to nothing and every
    time rule (order, declared timings, due dates, anchors) would be silently skipped.
    """
    shapes = schema.get("$defs", {}) if isinstance(schema.get("$defs"), dict) else {}
    timestamp_shape = re.compile(str(shapes.get("timestamp", {}).get("pattern", "^$")))
    date_shape = re.compile(str(shapes.get("date", {}).get("pattern", "^$")))
    for path, value, is_timestamp in date_fields(packet):
        if not isinstance(value, str):
            continue
        shape, parse = (timestamp_shape, parse_timestamp) if is_timestamp else (date_shape, parse_date)
        if shape.search(value) and parse(value) is None:
            kind = "time" if is_timestamp else "date"
            out.rule(
                "PIR-DATE-INVALID",
                f"{value!r} is shaped like a {kind} but is not a real one (check the month, day, hour and offset); every rule that reads it is blind until it is",
                path,
            )


def evidence_fields(packet: dict[str, Any]):
    """Every field that cites evidence or states an effect: (path, value)."""
    for index, row in enumerate(packet.get("timeline") or []):
        if isinstance(row, dict):
            yield f"$.timeline[{index}].evidence", row.get("evidence")
    metrics = mapping(packet.get("metrics"))
    for index, figure in enumerate(metrics.get("figures") or []):
        if isinstance(figure, dict):
            yield f"$.metrics.figures[{index}].source", figure.get("source")
    impact = mapping(packet.get("customer_impact"))
    yield "$.customer_impact.how_counted", impact.get("how_counted")
    analysis = mapping(packet.get("response_analysis"))
    for index, missed in enumerate(analysis.get("missed") or []):
        if isinstance(missed, dict):
            for field in ("gap", "effect"):
                yield f"$.response_analysis.missed[{index}].{field}", missed.get(field)
    for chain_index, chain in enumerate(packet.get("five_whys") or []):
        if isinstance(chain, dict):
            for why_index, why in enumerate(chain.get("whys") or []):
                if isinstance(why, dict):
                    yield f"$.five_whys[{chain_index}].whys[{why_index}].evidence", why.get("evidence")
    for index, item in enumerate(packet.get("action_items") or []):
        if isinstance(item, dict):
            yield f"$.action_items[{index}].prevents_recurrence", item.get("prevents_recurrence")


def validate_evidence(packet: dict[str, Any], out: Findings) -> None:
    for path, value in evidence_fields(packet):
        reason = evidence_placeholder(value)
        if reason:
            out.rule(
                "PIR-EVIDENCE-PLACEHOLDER",
                f"{value!r} cites nothing ({reason!r}); name the dashboard, log, record or decision it comes from",
                path,
            )


# ------------------------------------------------------------------------- document control


def lifecycle_timestamps(packet: dict[str, Any]) -> dict[str, datetime] | None:
    control = packet.get("document_control")
    if not isinstance(control, dict) or not isinstance(control.get("timestamps"), dict):
        return None
    parsed = {key: parse_timestamp(value) for key, value in control["timestamps"].items()}
    needed = ("impact_start", "detected_at", "cause_confirmed_at", "mitigated_at", "resolved_at")
    result: dict[str, datetime] = {}
    for key in needed:
        value = parsed.get(key)
        if value is None:
            return None  # PIR-SCHEMA or PIR-DATE-INVALID has reported the malformed or missing instant
        result[key] = value
    return result


def validate_time_order(timestamps: dict[str, datetime], out: Findings) -> None:
    order = ("impact_start", "detected_at", "cause_confirmed_at", "mitigated_at", "resolved_at")
    for earlier, later in itertools.pairwise(order):
        if timestamps[later] < timestamps[earlier]:
            out.rule(
                "PIR-TIME-ORDER",
                f"{later} ({timestamps[later].isoformat()}) is before {earlier} ({timestamps[earlier].isoformat()})",
                f"$.document_control.timestamps.{later}",
            )
    if timestamps["resolved_at"] == timestamps["impact_start"]:
        out.rule(
            "PIR-TIMESTAMPS-COLLAPSED",
            f"every lifecycle instant is {timestamps['impact_start'].isoformat()}: the incident has no duration, so every "
            f"timing is 0 and no time rule can see the incident; record when each instant actually happened",
            "$.document_control.timestamps",
        )


def validate_declared_timings(packet: dict[str, Any], timestamps: dict[str, datetime], out: Findings) -> None:
    declared = packet.get("key_timings")
    if not isinstance(declared, dict):
        return
    derived = derive_key_timings(timestamps)
    exact = exact_key_timings(timestamps)
    for key, value in declared.items():
        # The schema's "integer" admits 15.0, so a float is compared too; bool is not a timing.
        is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
        # Within a minute of the exact span is honest rounding: 9 min 40 s may be declared 9 or 10.
        if key in derived and is_number and abs(value - exact[key]) >= 1:
            out.rule(
                "PIR-TIMINGS-DECLARED",
                f"{key} is declared as {value} but the lifecycle timestamps give {derived[key]}; timestamps drive metrics, so correct one or the other",
                f"$.key_timings.{key}",
            )


def validate_due_dates(packet: dict[str, Any], timestamps: dict[str, datetime], out: Findings) -> None:
    control = packet["document_control"]
    mitigated = timestamps["mitigated_at"].date()
    draft_due = parse_date(control.get("draft_due"))
    publish_due = parse_date(control.get("publish_due"))
    if draft_due and draft_due > mitigated + timedelta(days=DRAFT_DUE_MAX_DAYS):
        out.rule(
            "PIR-DUE-DRAFT-LATE",
            f"draft_due {draft_due} is more than {DRAFT_DUE_MAX_DAYS} days after mitigation ({mitigated}); the deck asks for a draft within 2 to 3 business days while memory and metrics are fresh",
            "$.document_control.draft_due",
        )
    for field, due in (("draft_due", draft_due), ("publish_due", publish_due)):
        if due and due < mitigated:
            # A PIR cannot be drafted before the incident is mitigated; a past date is a placeholder.
            out.rule(
                "PIR-DUE-BEFORE-INCIDENT",
                f"{field} {due} is before the incident was mitigated ({mitigated}); record the date the PIR is actually due",
                f"$.document_control.{field}",
            )
    if publish_due and publish_due > mitigated + timedelta(days=PUBLISH_DUE_MAX_DAYS):
        out.rule(
            "PIR-DUE-PUBLISH-LATE",
            f"publish_due {publish_due} is more than {PUBLISH_DUE_MAX_DAYS} days after mitigation ({mitigated}); the deck asks for publication within 1 to 2 weeks",
            "$.document_control.publish_due",
        )


# -------------------------------------------------------------------------------------- summary


def validate_summary(packet: dict[str, Any], out: Findings) -> None:
    summary = packet.get("summary")
    control = packet.get("document_control")
    if not isinstance(summary, str) or not isinstance(control, dict):
        return
    services = control.get("services")
    primary = (
        services[0] if isinstance(services, list) and services and isinstance(services[0], str) else None
    )
    if primary and primary.lower() not in summary.lower():
        out.rule(
            "PIR-SUMMARY-SERVICE",
            f"summary does not name the primary service '{primary}'; the pattern starts '<Application> experienced <metric>'",
            "$.summary",
        )
    if not has_figure(summary):
        out.rule(
            "PIR-SUMMARY-NUMBER",
            "summary carries no figure (digits in an id, a date or a time do not count); state the metric and the customer impact in figures",
            "$.summary",
        )
    if not SUMMARY_DATE.search(ID_TOKEN.sub(" ", summary)):
        out.rule(
            "PIR-SUMMARY-DATE",
            "summary does not say when; the pattern is '<Application> experienced <metric> at <date time>'",
            "$.summary",
        )


# ------------------------------------------------------------------------------------- timeline


def validate_timeline(packet: dict[str, Any], timestamps: dict[str, datetime] | None, out: Findings) -> None:
    rows = packet.get("timeline")
    if not isinstance(rows, list):
        return
    parsed: list[tuple[int, datetime, str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        at = parse_timestamp(row.get("at"))
        if at is not None and isinstance(row.get("phase"), str):
            parsed.append((index, at, row["phase"]))

    for (prev_index, prev_at, _), (index, at, _) in itertools.pairwise(parsed):
        if at < prev_at:
            out.rule(
                "PIR-TIMELINE-ORDER",
                f"row {index} ({at.isoformat()}) is earlier than row {prev_index} ({prev_at.isoformat()}); the timeline must read forwards",
                f"$.timeline[{index}].at",
            )

    phases_present = {phase for _, _, phase in parsed}
    for phase in ANCHORED_PHASES:
        if phase not in phases_present:
            out.rule(
                "PIR-TIMELINE-PHASE-MISSING",
                f"no timeline row has phase '{phase}'; the reader cannot see where that moment was",
                "$.timeline",
            )
    if "diagnosis" not in phases_present:
        out.rule(
            "PIR-TIMELINE-NO-DIAGNOSIS",
            "no diagnosis rows: record each hypothesis and the evidence that proved or rejected it, or time to know is invisible",
            "$.timeline",
        )

    if timestamps is None:
        return
    for phase, key in ANCHORED_PHASES.items():
        candidates = [(index, at) for index, at, row_phase in parsed if row_phase == phase]
        if not candidates:
            continue
        # The FIRST detection row is the first signal; the lifecycle 'detected_at' is defined the same way.
        # impact_start, mitigated and resolved are single moments, so any row carrying that phase must match.
        checked = [candidates[0]] if phase == "detection" else candidates
        for index, at in checked:
            if at != timestamps[key]:
                out.rule(
                    "PIR-TIMELINE-ANCHOR",
                    f"the '{phase}' row at {at.isoformat()} disagrees with document_control.timestamps.{key} ({timestamps[key].isoformat()})",
                    f"$.timeline[{index}].at",
                )


# -------------------------------------------------------------------------------------- metrics


def validate_metrics(packet: dict[str, Any], out: Findings) -> None:
    metrics = packet.get("metrics")
    if not isinstance(metrics, dict):
        return
    figures = metrics.get("figures")
    if not isinstance(figures, list) or not figures:
        out.rule(
            "PIR-FIGURES-NONE",
            "no figures: include at least the customer-facing metric over the incident window",
            "$.metrics.figures",
        )
    else:
        dict_figures = [f for f in figures if isinstance(f, dict)]
        if not any(f.get("baseline_compared") is True for f in dict_figures):
            out.rule(
                "PIR-FIGURE-BASELINE",
                "no figure is compared with a normal baseline; show the same window on a comparable day",
                "$.metrics.figures",
            )
        if not any(f.get("annotated") is True for f in dict_figures):
            out.rule(
                "PIR-FIGURE-ANNOTATED",
                "no figure is annotated with impact start, detection, mitigation and resolution",
                "$.metrics.figures",
            )
    summary = metrics.get("summary")
    if not isinstance(summary, list) or not summary:
        out.rule(
            "PIR-METRIC-SUMMARY-EMPTY",
            "the metric summary is empty; name each metric, its baseline and its value during the incident",
            "$.metrics.summary",
        )
        return
    for index, row in enumerate(summary):
        if not isinstance(row, dict):
            continue
        for field in ("metric", "normal_baseline", "during_incident"):
            value = row.get(field)
            if isinstance(value, str) and AVERAGE_WORDS.search(value):
                out.rule(
                    "PIR-METRIC-AVERAGE",
                    f"metric summary row {index} uses an average in '{field}'; averages hide the shape of the failure, use the most granular metric available",
                    f"$.metrics.summary[{index}].{field}",
                )


# ------------------------------------------------------------------------------ customer impact


def validate_customer_impact(packet: dict[str, Any], out: Findings) -> None:
    impact = packet.get("customer_impact")
    if not isinstance(impact, dict):
        return
    how_many = impact.get("how_many")
    if isinstance(how_many, str):
        stated = how_many.strip()
        if stated.lower().startswith(NOT_DETERMINED):
            # The escape hatch needs its reason: "not determined: n/a" says nothing.
            why = stated[len(NOT_DETERMINED) :]
            if evidence_placeholder(why):
                out.rule(
                    "PIR-IMPACT-QUANTIFIED",
                    f"how_many is 'not determined' without a reason ({evidence_placeholder(why)!r}); say why it could not be counted",
                    "$.customer_impact.how_many",
                )
        elif not has_figure(stated):
            out.rule(
                "PIR-IMPACT-QUANTIFIED",
                "how_many carries no number (digits in an id, a date or a time do not count); give the count and its basis, or write 'not determined: <why>'",
                "$.customer_impact.how_many",
            )
    duration = impact.get("duration")
    if isinstance(duration, str) and not DIGIT.search(duration):
        out.rule(
            "PIR-IMPACT-DURATION",
            "duration carries no number; state the impact window in minutes or hours",
            "$.customer_impact.duration",
        )


# ---------------------------------------------------------------------------- response analysis


def validate_response_analysis(packet: dict[str, Any], out: Findings) -> set[str]:
    """Returns the set of declared channel ids, for the chain checks."""
    analysis = packet.get("response_analysis")
    if not isinstance(analysis, dict):
        return set()
    missed = analysis.get("missed")
    areas = {m.get("area") for m in missed if isinstance(m, dict)} if isinstance(missed, list) else set()
    for area in REQUIRED_MISSED_AREAS:
        if area not in areas:
            out.rule(
                "PIR-MISSED-AREAS",
                f"response_analysis.missed has no '{area}' entry; say what slowed {area} down and what it cost, or that nothing did and why",
                "$.response_analysis.missed",
            )
    channels = ids_of(analysis.get("channels_of_inquiry"))
    if not channels:
        out.rule(
            "PIR-CHANNELS-NONE",
            "no channels of inquiry; list each distinct problem that contributed so each gets a Five Whys chain",
            "$.response_analysis.channels_of_inquiry",
        )
    return set(channels)


# ------------------------------------------------------------------------------------ five whys


def validate_five_whys(packet: dict[str, Any], channels: set[str], out: Findings) -> set[str]:
    """Returns the set of root-cause ids, for the lesson checks."""
    chains = packet.get("five_whys")
    if not isinstance(chains, list):
        return set()
    dict_chains = [c for c in chains if isinstance(c, dict)]
    chained_channels = {c.get("channel") for c in dict_chains}
    for channel in sorted(channels):
        if channel not in chained_channels:
            out.rule(
                "PIR-CHANNEL-NO-CHAIN",
                f"{channel} has no Five Whys chain; every channel of inquiry is explained by one",
                "$.five_whys",
            )
    for index, chain in enumerate(dict_chains):
        chain_channel = chain.get("channel")
        if isinstance(chain_channel, str) and chain_channel not in channels:
            out.rule(
                "PIR-CHAIN-UNKNOWN-CHANNEL",
                f"{chain.get('id', '<no id>')} follows channel {chain_channel}, which response_analysis does not declare",
                f"$.five_whys[{index}].channel",
            )

    kinds = {c.get("kind") for c in dict_chains}
    for kind in REQUIRED_CHAIN_KINDS:
        if kind not in kinds:
            out.rule(
                "PIR-CHAIN-KINDS",
                f"no Five Whys chain of kind '{kind}'; the deck asks for separate chains that follow the failure, the detection gap and the slow fix",
                "$.five_whys",
            )
    control = packet.get("document_control")
    if isinstance(control, dict) and control.get("repeat_incident") is True and "prior_actions" not in kinds:
        out.rule(
            "PIR-CHAIN-PRIOR-ACTIONS",
            "repeat_incident is true but no chain of kind 'prior_actions' asks why the previous actions did not prevent this",
            "$.five_whys",
        )

    for index, chain in enumerate(dict_chains):
        chain_id = chain.get("id", "<no id>")
        whys = chain.get("whys")
        count = len(whys) if isinstance(whys, list) else 0
        if count < WHY_MINIMUM:
            out.rule(
                "PIR-WHY-DEPTH",
                f"{chain_id} has {count} why(s); fewer than {WHY_MINIMUM} has not reached a process cause",
                f"$.five_whys[{index}].whys",
            )
        elif count < WHY_TYPICAL_FLOOR:
            out.rule(
                "PIR-WHY-SHALLOW",
                f"{chain_id} has {count} whys; four to six is typical, check the chain has reached a cause that would hold regardless of who was on shift",
                f"$.five_whys[{index}].whys",
            )
        root_cause = chain.get("root_cause")
        if isinstance(root_cause, str) and any(
            ACTOR_ROOT_CAUSE.search(sentence) for sentence in SENTENCE_BREAK.split(root_cause)
        ):
            out.rule(
                "PIR-ROOTCAUSE-ACTOR",
                f"{chain_id}'s root cause names an actor's action; that is where the chain starts, ask why the process allowed it",
                f"$.five_whys[{index}].root_cause",
            )
        seen: dict[str, int] = {}
        for why_index, why in enumerate(whys if isinstance(whys, list) else []):
            answer = why.get("because") if isinstance(why, dict) else None
            because = core_text(answer) if isinstance(answer, str) else ""
            if because and because in seen:
                out.rule(
                    "PIR-WHY-REPEATED",
                    f"{chain_id} gives the same answer at why {why_index + 1} as at why {seen[because] + 1}; a repeated why adds depth on paper only",
                    f"$.five_whys[{index}].whys[{why_index}].because",
                )
            seen.setdefault(because, why_index)

    signatures: dict[tuple[str, ...], str] = {}
    for index, chain in enumerate(dict_chains):
        whys = sequence(chain.get("whys"))
        signature = tuple(
            core_text(w["because"]) for w in whys if isinstance(w, dict) and isinstance(w.get("because"), str)
        )
        if not signature:
            continue
        chain_id = str(chain.get("id", "<no id>"))
        if signature in signatures:
            out.rule(
                "PIR-CHAIN-DUPLICATE",
                f"{chain_id} repeats {signatures[signature]}'s whys answer for answer; each chain follows its own problem",
                f"$.five_whys[{index}].whys",
            )
        signatures.setdefault(signature, chain_id)
    return set(ids_of(dict_chains))


# ------------------------------------------------------------- lessons, corrective actions, AIs


def validate_traceability(packet: dict[str, Any], root_causes: set[str], out: Findings) -> None:
    lessons = [item for item in packet.get("lessons") or [] if isinstance(item, dict)]
    actions = [item for item in packet.get("corrective_actions") or [] if isinstance(item, dict)]
    items = [item for item in packet.get("action_items") or [] if isinstance(item, dict)]

    if not lessons:
        out.rule("PIR-LESSONS-NONE", "no lessons learned; each root cause yields at least one", "$.lessons")
    if not actions:
        out.rule(
            "PIR-CA-NONE", "no corrective actions; each lesson yields at least one", "$.corrective_actions"
        )
    if not items:
        out.rule(
            "PIR-AI-NONE", "no action items; each corrective action yields at least one", "$.action_items"
        )

    lesson_ids = {str(item.get("id")) for item in lessons}
    action_ids = {str(item.get("id")) for item in actions}

    referenced_root_causes: set[str] = set()
    for index, lesson in enumerate(lessons):
        rc = lesson.get("root_cause")
        if isinstance(rc, str):
            referenced_root_causes.add(rc)
            if rc not in root_causes:
                out.rule(
                    "PIR-LESSON-RC-UNKNOWN",
                    f"{lesson.get('id')} derives from {rc}, which no Five Whys chain defines",
                    f"$.lessons[{index}].root_cause",
                )
    for rc in sorted(root_causes - referenced_root_causes):
        out.rule(
            "PIR-RC-NO-LESSON",
            f"{rc} has no lesson; a root cause nobody learned from will recur",
            "$.lessons",
        )

    addressed_lessons: set[str] = set()
    improvements: set[str] = set()
    for index, action in enumerate(actions):
        for lesson_id in action.get("addresses") or []:
            if isinstance(lesson_id, str):
                addressed_lessons.add(lesson_id)
                if lesson_id not in lesson_ids:
                    out.rule(
                        "PIR-CA-LL-UNKNOWN",
                        f"{action.get('id')} addresses {lesson_id}, which is not a lesson in this PIR",
                        f"$.corrective_actions[{index}].addresses",
                    )
        for improvement in action.get("improves") or []:
            if isinstance(improvement, str):
                improvements.add(improvement)
    for lesson_id in sorted(lesson_ids - addressed_lessons):
        out.rule(
            "PIR-LESSON-NO-CA",
            f"{lesson_id} has no corrective action; a lesson with nothing done about it is a wish",
            "$.corrective_actions",
        )
    if actions and not (improvements & HALVING_IMPROVEMENTS):
        out.rule(
            "PIR-CA-NO-HALVING",
            "no corrective action improves time to detect, time to know or time to remediate; the deck asks what would halve each",
            "$.corrective_actions",
        )

    covered_actions: set[str] = set()
    for index, item in enumerate(items):
        ca = item.get("corrective_action")
        if isinstance(ca, str):
            if item.get("status") != "cancelled":  # a cancelled task will never happen
                covered_actions.add(ca)
            if ca not in action_ids:
                out.rule(
                    "PIR-AI-CA-UNKNOWN",
                    f"{item.get('id')} implements {ca}, which is not a corrective action in this PIR",
                    f"$.action_items[{index}].corrective_action",
                )
    for action_id in sorted(action_ids - covered_actions):
        out.rule(
            "PIR-CA-NO-AI",
            f"{action_id} has no action item that is not cancelled; a corrective action with no task never happens",
            "$.action_items",
        )


def validate_action_items(
    packet: dict[str, Any],
    timestamps: dict[str, datetime] | None,
    out: Findings,
    vague: list[VagueTerm],
) -> None:
    status = packet.get("status")
    agreement_is_blocking = status in ("in_go_review", "published")
    incident_date = timestamps["resolved_at"].date() if timestamps else None
    for index, item in enumerate(packet.get("action_items") or []):
        if not isinstance(item, dict):
            continue
        item_id = item.get("id", "<no id>")
        statement = item.get("statement")
        entry = vague_opening(statement, vague) if isinstance(statement, str) else None
        if entry is not None and isinstance(statement, str):
            if entry.satisfied_by is not None and entry.satisfied_by.search(statement):
                out.rule(
                    "PIR-AI-VAGUE",
                    f"{item_id} opens with '{entry.term}' but names the output its remediation asks for; confirm that output is what marks it done",
                    f"$.action_items[{index}].statement",
                    severity=WARNING,
                )
            else:
                out.rule(
                    "PIR-AI-VAGUE",
                    f"{item_id} opens with '{entry.term}', which has no done state; name the output, where it lands and the decision it feeds",
                    f"$.action_items[{index}].statement",
                )
        if item.get("owner_agreed") is False:
            out.rule(
                "PIR-AI-NOT-AGREED",
                f"{item_id}'s owner has not agreed to it; never blindly assign action items"
                + ("" if agreement_is_blocking else " (blocking from GO review)"),
                f"$.action_items[{index}].owner_agreed",
                severity=ERROR if agreement_is_blocking else WARNING,
            )
        due = parse_date(item.get("due_date"))
        if due and incident_date and due < incident_date:
            out.rule(
                "PIR-AI-DUE-BEFORE-INCIDENT",
                f"{item_id} is due {due}, before the incident was resolved ({incident_date})",
                f"$.action_items[{index}].due_date",
            )
        if due and incident_date and due > incident_date + timedelta(days=ACTION_DUE_MAX_DAYS):
            out.rule(
                "PIR-AI-DUE-FAR",
                f"{item_id} is due {due}, more than {ACTION_DUE_MAX_DAYS} days after the incident was resolved ({incident_date}); "
                f"a placeholder date is not tracking, and a programme is split into milestones due within the year",
                f"$.action_items[{index}].due_date",
            )


# --------------------------------------------------------------------------------------- review


def validate_review(packet: dict[str, Any], out: Findings) -> None:
    review = packet.get("review")
    status = packet.get("status")
    if not isinstance(review, dict):
        return
    stages = {s.get("stage") for s in review.get("stages") or [] if isinstance(s, dict)}
    if status == "in_go_review" and "team" not in stages:
        out.rule(
            "PIR-GO-REVIEW-NO-TEAM",
            "status is in_go_review but no team review outcome is recorded; reviews are sequential",
            "$.review.stages",
        )
    if status == "published":
        for stage in ("team", "go"):
            if stage not in stages:
                out.rule(
                    "PIR-PUBLISHED-NO-REVIEW",
                    f"status is published but no '{stage}' review outcome is recorded",
                    "$.review.stages",
                )
        for index, question in enumerate(review.get("open_questions") or []):
            answer = question.get("answer") if isinstance(question, dict) else None
            # A placeholder ("TBD", "Unknown.") is not an answer.
            if isinstance(question, dict) and (answer in (None, "") or evidence_placeholder(answer)):
                out.rule(
                    "PIR-PUBLISHED-OPEN-QUESTION",
                    f"status is published but {question.get('id', '<no id>')} is unanswered",
                    f"$.review.open_questions[{index}].answer",
                )


# ----------------------------------------------------------------------------------- orchestration


def validate_packet(
    packet: dict[str, Any],
    schema: dict[str, Any],
    blame: list[tuple[str, re.Pattern[str]]],
    vague: list[VagueTerm],
) -> Findings:
    out = Findings()
    validate_schema(packet, schema, out)
    validate_blame_language(packet, out, blame)
    validate_unique_ids(packet, out)
    validate_owners(packet, out)
    validate_dates(packet, schema, out)
    validate_evidence(packet, out)

    timestamps = lifecycle_timestamps(packet)
    if timestamps is not None:
        validate_time_order(timestamps, out)
        validate_declared_timings(packet, timestamps, out)
        validate_due_dates(packet, timestamps, out)
    validate_summary(packet, out)
    validate_timeline(packet, timestamps, out)
    validate_metrics(packet, out)
    validate_customer_impact(packet, out)
    channels = validate_response_analysis(packet, out)
    root_causes = validate_five_whys(packet, channels, out)
    validate_traceability(packet, root_causes, out)
    validate_action_items(packet, timestamps, out, vague)
    validate_review(packet, out)
    return out


def gap_report_entry(path: Path, packet: dict[str, Any] | None, findings: Findings) -> dict[str, Any]:
    return {
        "packet": str(path),
        "id": packet.get("id") if isinstance(packet, dict) else None,
        "status": "FAIL" if findings.errors else "PASS",
        "error_count": len(findings.errors),
        "warning_count": len(findings.warnings),
        "findings": [asdict(f) for f in findings.items],
    }


def validate_path(
    path: Path,
    schema: dict[str, Any],
    blame: list[tuple[str, re.Pattern[str]]],
    vague: list[VagueTerm],
    warnings_as_errors: bool,
) -> tuple[int, dict[str, Any]]:
    print(f"VALIDATING {path}", file=sys.stderr)
    try:
        packet = load_document(path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        findings = Findings()
        findings.rule("PIR-SCHEMA", f"packet could not be read: {exc}")
        print(f"FAIL {path}\n  - {findings.items[0].render()}", file=sys.stderr)
        return 1, gap_report_entry(path, None, findings)

    findings = validate_packet(packet, schema, blame, vague)
    failing = bool(findings.errors) or (warnings_as_errors and bool(findings.warnings))
    verdict = "FAIL" if failing else "PASS"
    suffix = f" ({len(findings.warnings)} warning(s))" if findings.warnings and not failing else ""
    print(f"{verdict} {path}{suffix}", file=sys.stderr)
    for finding in findings.errors:
        print(f"  - {finding.render()}", file=sys.stderr)
    for finding in findings.warnings:
        print(f"  - warning {finding.render()}", file=sys.stderr)
    return (1 if failing else 0), gap_report_entry(path, packet, findings)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate PIR packets and emit the gap report the interview is built from."
    )
    parser.add_argument("paths", nargs="+", help="PIR packet files (.yaml, .yml or .json).")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA_PATH), help="Schema to enforce.")
    parser.add_argument(
        "--gap-report", help="Write a JSON gap report covering every packet validated to this path."
    )
    parser.add_argument("--warnings-as-errors", action="store_true", help="Exit non-zero on warnings too.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        schema = load_schema(Path(args.schema))
        blame = blame_patterns()
        vague = vague_action_patterns()
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    exit_code = 0
    entries: list[dict[str, Any]] = []
    for raw in args.paths:
        code, entry = validate_path(Path(raw), schema, blame, vague, args.warnings_as_errors)
        exit_code = max(exit_code, code)
        entries.append(entry)

    if args.gap_report:
        report = {"generated_by": "tools/validate_pir.py", "packets": entries}
        Path(args.gap_report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"gap report written to {args.gap_report}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
