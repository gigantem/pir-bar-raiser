# How PIR Assessor works

What the tools and agents do with a Post-Incident Review, what the gate holds a PIR to, and what
it deliberately leaves to people. The agents read this before they transcribe or review.

## 1. What it is for

An implementation request that does not say who the actors are, what triggers the behaviour or what
happens on the failure path is not a specification but a prompt: the decisions nobody made get made
silently by whoever implements it. A Post-Incident Review has the same failure mode with the roles
reversed. The PIR owner has the knowledge; the document is the specification of what the
organisation will change. A PIR that says "some customers were impacted", that stops its Five Whys
at "the engineer changed the config", or whose action items read "investigate the alerting" is not
a review but a prompt: the decisions about what actually happened and what will prevent recurrence
get made silently, later, by whoever reads it. Or never.

So PIR Assessor does one thing: **it makes the gaps in a PIR explicit, asks the owner the
exact question that closes each gap, and refuses to call the PIR complete until the chain from
evidence to root cause to lesson to corrective action to owned, dated action item is unbroken.**

The reference for "what good looks like" is the deck *What Good Looks Like for Post-Incident
Reviews* and the PIR template derived from it (`docs/templates/PIR-Template-DRAFT.docx`). The
template is used in both directions: its sections and appendix define what is expected, and the
finished PIR is rendered back into it.

## 2. Lifecycle

```
PIR source                packet              gap report           interview            answers
(docx / notes / chat) --> pirs/<stem>.yaml --> validate_pir.py --> generate_pir_interview --> owner
                               ^                                                              |
                               |            clarification ledger (audit trail of Q&A)         |
                               +---- agent transcribes answers into the packet <--------------+
                               |
                               v
                         validate again --> reviewer findings (PASS/FAIL) --> render PIR (.docx / .md)
```

1. **Ingest.** The agent (or a person) transcribes whatever exists into a PIR packet. Nothing
   is invented: a section with no source material is left absent, which the validator reports.
2. **Validate.** `tools/validate_pir.py` applies the schema and the semantic rules and writes a
   gap report: every finding carries a rule id, a section, a severity and a path.
3. **Interview.** `tools/generate_pir_interview.py` turns the gap report into one
   question program for the PIR owner, grouped by section in writing order, each question
   carrying the section's expectation and example from the catalog. Nothing the tool cannot
   derive is guessed: owner-only facts are `HUMAN_CONFIRM` placeholders.
4. **Record.** Answers go into a clarification ledger (who answered, when, from what source)
   and the agent applies them to the packet. The ledger is the audit trail, the packet is the
   state.
5. **Review.** The reviewer persona produces findings against the findings schema. A blocker
   is a FAIL. The deck's reviewer checklist is the review focus, and the artifact records the
   walk: a coverage judgement for every template section, so a review with no findings still
   says what was checked. A passing review names the packet bytes it reviewed (their digest);
   when those bytes change, or were never observed, or live in another repository, a PASS is an
   error and the packet is reviewed again. A FAIL on changed bytes stands as history.
6. **Render.** The finished packet is rendered into the template. The template's
   Appendix A is itself rendered from the catalog, so the guidance a reader sees and the
   guidance the interview asks from are the same bytes.

## 3. The packet contract

One key per template section, in reading order. Identifiers follow the template exactly:
`RC-A` root causes, `LL-1` lessons, `CA-1` corrective actions, `AI-1` action items, `CH-1`
channels of inquiry.

The schema enforces structure and the validator enforces meaning. The semantic rules, grouped by section:

- **Document control.** The five lifecycle timestamps (impact start, detected, cause
  confirmed, mitigated, resolved) carry an explicit UTC offset and are non-decreasing.
  *Detected* is the first signal of any kind, including a customer or staff report that beat
  the alert, so time to detect measures how long impact was invisible.
  Declared key timings, when present, agree with the derived ones to within a minute, so a
  value rounded either way from the exact span passes. A lifecycle whose instants are all the
  same is an error: every timing would be 0 and no time rule could see the incident. Draft and
  publish due dates may not be before mitigation (an error) and are checked against the deck's
  2–3 day and 1–2 week guidance (warnings).
- **Summary.** Names the primary service, carries at least one figure, says when, and is long
  enough to have followed the deck's pattern. Digits inside an identifier ("INC-2026-0412"), a
  date or a time are not a figure; "when" is a year, a numeric date, or a month beside a day or
  a year, never a month prefix inside another word ("decreased", "marketing") or a bare "may". The validator cannot check it was written last; the
  interview asks it last.
- **Timeline.** Ascending; every row has evidence; the impact-start, detection, mitigated and
  resolved phases are present and agree with the lifecycle timestamps.
- **Metrics.** At least one figure, at least one with a normal baseline and annotations, as the
  figures declare them (`baseline_compared`, `annotated`): the validator reads the flags and
  cannot see the graph, so whether the graph shows the failure is the reviewer's question.
  Averages in the metric summary are a warning (the deck: avoid averages).
- **Customer impact.** The count carries a figure (not an id) or says "not determined:" and a
  reason that is not a placeholder; the counting method, what was not affected, and data
  integrity are stated.
- **Response analysis.** Detection, diagnosis and remediation are each addressed; at least one
  channel of inquiry; every channel has a Five Whys chain and vice versa.
- **Five Whys.** Chains of kind failure, detection and resolution are required (prior-actions
  when the incident is a repeat); at least three whys per chain, warning below four; every
  answer cites evidence, never a placeholder; no sentence of the root cause has a person (an
  engineer, an SRE, "they") as the subject of an action, which is where a chain starts rather
  than ends ("The on-call rota failed to include a specialist" names a rota and passes); a why
  that repeats an earlier answer, or a chain that copies another, warns.
- **Lessons, corrective actions, action items.** The chain is total in both directions: every
  root cause has a lesson, every lesson a corrective action, every corrective action an action
  item, and every reference resolves. No corrective action set whose declared `improves` tags
  name none of TTD, TTK or TTR passes without a warning; the tags are not a measured effect. Action items are not vague: no lexicon verb or its noun form
  opens the statement or a clause of its first sentence, even behind a subject and a modal
  ("We will investigate"); naming the output the verb's remediation asks for ("Monitor ... with
  a new alert at 80%") makes it a warning for a person to confirm rather than a block. They have
  a non-generic owner who has agreed, a due date after the incident and within a year of it (a
  programme is split into milestones), and a stated recurrence effect. A cancelled action item
  does not count towards its corrective action.
- **Review.** `published` requires team and GO review outcomes recorded and no unanswered
  review question.
- **Everywhere.** Blame language (lexicon) is a blocker in any prose field, matched after
  Unicode folding, invisible-character and lookalike removal, and separator collapsing. Owners
  name a person or team, never a placeholder, a left-in `HUMAN_CONFIRM` or a bare role. Every
  date and timestamp is a real one; a date-shaped value the calendar rejects (hour 25, 30
  February) is an error, because every time rule depends on it. Evidence and effect fields cite
  something.

## 4. What is deliberately not mechanical

The validator can prove a field is present, shaped, consistent and free of the lexicon terms.
It cannot prove a root cause is true, a lesson is honest, or an action item would prevent
recurrence. Those judgements belong to the owner and the reviewer; the tooling's job is to
make sure the question is asked and the answer is recorded with provenance. A green gate is not a finding-free PIR, and the reviewer artifact must never be generated
with judgement fields filled.
