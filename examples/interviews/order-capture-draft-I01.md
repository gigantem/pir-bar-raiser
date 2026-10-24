# PIR owner interview: PIR-2026-0412, round 1

## Outcome

- Status: `answers_required`
- Packet: `examples/draft/order-capture-draft.yaml` (status `draft`)
- Questions: 20 (16 blocking, 4 advisory) across 10 section(s)
- PIR owner: Order Capture product owner (A. Example)
- Facilitator: HUMAN_CONFIRM_FACILITATOR

## Source artifacts

- `examples/draft/order-capture-draft.yaml` (pir-packet)
- `catalogs/pir-section-expectations.yaml` (section-expectations)
- `catalogs/pir-rule-questions.yaml` (rule-questions)

## How to use this interview

- Work through the sections in the order given: it is the deck's writing order, so the timeline and metrics are settled before the analysis that depends on them, and the summary is written last.
- Answer blocking questions first; the packet cannot pass the gate while any is open. Advisory questions are the deck's softer guidance and may be answered, deferred with an owner and date, or waived with a reason.
- Every answer comes with its evidence (a log query, a dashboard panel, a ticket, a record), and the person or team who gave it. Nothing is invented to make the packet validate.
- The PIR stays blameless: when an answer names a person, restate it as the process, design or tooling gap.
- Replace every HUMAN_CONFIRM placeholder before using this interview with the owner.

## Order of work

| Order | Template section | Questions | Blocking |
| --- | --- | --- | --- |
| 0 | 0. Document control | 1 | 1 |
| 1 | 2. Timeline | 1 | 0 |
| 2 | 3. Metrics and graphs | 3 | 2 |
| 3 | 4. Customer impact | 1 | 1 |
| 4 | 5. Incident response and post-incident analysis | 3 | 3 |
| 5 | 6. Five Whys | 3 | 3 |
| 7 | 8. Corrective actions | 1 | 0 |
| 8 | 9. Action items | 2 | 1 |
| 9 | 1. Summary | 3 | 3 |
| 99 | all. Whole document | 2 | 2 |

## Sections

### 0. Document control (writing order 0)

**What good looks like.** The incident identity and the five lifecycle instants: impact start (when customers first experienced it, not when we noticed), detected, cause confirmed, mitigated, resolved. Every timestamp carries its timezone. The PIR owner is the product owner, named; the incident manager and contributors are roles and teams. Draft and publish due dates follow the deck: draft within 2 to 3 business days of mitigation, publish within 1 to 2 weeks.

**Common mistakes.**

- Recording detection time as impact start, which hides time to detect.
- Times without a timezone.
- Leaving the owner as "TBD", so nobody presents the PIR.

**Example.** INC-2026-0412, Sev-1, Order Capture API. Impact start 2026-09-03T09:12+10:00, detected 09:21 (first customer-care report), cause confirmed 10:05, mitigated 10:26, resolved 10:47. PIR owner: Order Capture product owner (A. Example). Draft due 2026-09-08, publish due 2026-09-17.

**Ask.** Confirm the five lifecycle times with their timezone, the severity, the primary service, and who owns and will present this PIR.

#### Q-001 (blocking, `PIR-TIMINGS-DECLARED` at `$.key_timings.time_to_detect_minutes`)

- **Finding:** time_to_detect_minutes is declared as 15 but the lifecycle timestamps give 9; timestamps drive metrics, so correct one or the other
- **Question:** The declared timing disagrees with what the lifecycle timestamps give. Which is right, the timestamp or the declared minutes?
- **A complete answer:** Either a corrected timestamp or the derived value. Time to detect, know, remediate, impact and resolve are all derived from the five timestamps, so the timestamps win.
- **Goes into:** `$.key_timings.time_to_detect_minutes`

### 2. Timeline (writing order 1)

**What good looks like.** A distilled, timestamped sequence of the events that mattered: the precursor change, the first customer impact, the first signal, each hypothesis and the evidence that proved or rejected it, each decision, mitigation, resolution and the key communications. Every row has a timezone-qualified time and a source a reader could check. People appear by role, never by name. The phase column lets a reader see where the time went. Ten to thirty rows is typical for a Sev-1; summarise chat, do not paste it.

**Common mistakes.**

- Starting at detection instead of impact start.
- Omitting rejected hypotheses, which hides time to know.
- "Team investigated" rows with no content.

**Example.** 09:04 AEST CHG-88213 deployed (deploy log, precursor). 09:12 5xx rate rises from 0.2% to 8% (FIG-1, impact start). 09:21 customer care reports failures (CS-55120, detection). 09:27 alert pages on-call (A-2231, detection). 09:45 Hypothesis 1 rejected: catalogue p99 normal (FIG-2B, diagnosis). 10:05 Hypothesis 2 proven: pool 60/60 (FIG-2A, diagnosis). 10:14 decision to roll back (decision log, remediation). 10:26 rollback complete, 5xx below 1% (FIG-1, mitigated). 10:47 queue drained, resolved.

**Ask.** Walk through the incident from the precursor to the final communication. For each event give the time with timezone, what was observed or decided, the evidence, and the phase.

#### Q-002 (advisory, `PIR-TIMELINE-NO-DIAGNOSIS` at `$.timeline`)

- **Finding:** no diagnosis rows: record each hypothesis and the evidence that proved or rejected it, or time to know is invisible
- **Question:** Which hypotheses were considered, when was each proven or rejected, and on what evidence? Rejected hypotheses are where time to know went.
- **A complete answer:** One diagnosis row per hypothesis, including the rejected ones, each with evidence.
- **Goes into:** `$.timeline`

### 3. Metrics and graphs (writing order 2)

**What good looks like.** At least one graph of the customer-facing metric and one of the diagnostic metric that confirmed the cause, both over the same time range, annotated with impact start, detection, mitigation and resolution, and shown against a normal baseline (the same window on a comparable day). Use the most granular data available and avoid averages, which hide the shape of the failure. Add an architecture or network diagram when the failure path crosses several components. Capture the data immediately: high-resolution metrics are often downsampled or expire within days.

**Common mistakes.**

- Screenshots with no axis labels, no time range or no timezone.
- Charts of different windows that cannot be compared.
- Hourly averages over a 74-minute incident.
- Showing only the metric that looked bad and not the baseline that shows what normal is.

**Example.** FIG-1: POST /orders 5xx rate per minute, 3 Sep 08:30 to 11:30 AEST, overlaid with 27 Aug same window; annotated at deploy, impact start, alert, rollback. FIG-2: pool in-use vs maximum per 10 s, same window, flat at 60 from 09:11 to 10:25.

**Ask.** Which graphs show the customer-facing metric and the diagnostic metric over the incident window? Is each annotated and compared to a normal baseline? Where is the data?

#### Q-003 (blocking, `PIR-FIGURE-BASELINE` at `$.metrics.figures`)

- **Finding:** no figure is compared with a normal baseline; show the same window on a comparable day
- **Question:** Which figure can be shown against a normal baseline, the same window on a comparable day?
- **A complete answer:** A figure overlaid with or beside the baseline, with baseline_compared set true.
- **Goes into:** `$.metrics.figures`

#### Q-004 (blocking, `PIR-FIGURE-ANNOTATED` at `$.metrics.figures`)

- **Finding:** no figure is annotated with impact start, detection, mitigation and resolution
- **Question:** Which figure can be annotated with impact start, detection, mitigation and resolution?
- **A complete answer:** A figure with the four lifecycle instants marked, with annotated set true.
- **Goes into:** `$.metrics.figures`

#### Q-005 (advisory, `PIR-METRIC-AVERAGE` at `$.metrics.summary[0].during_incident`)

- **Finding:** metric summary row 0 uses an average in 'during_incident'; averages hide the shape of the failure, use the most granular metric available
- **Question:** This row reports an average. What is the most granular value available (per minute, per ten seconds, the peak)?
- **A complete answer:** The granular value and its resolution in place of the average.
- **Goes into:** `$.metrics.summary[0].during_incident`

### 4. Customer impact (writing order 3)

**What good looks like.** Who was affected, what they experienced in their terms, how many, for how long, and which business metrics and commitments were hit. Say how each number was derived so a reviewer can trust it. Contact affected customers or partners to confirm impact; a PIR that reflects the customer's own account restores trust faster than one that guesses. State clearly what was not affected and whether any data was lost, duplicated or corrupted.

**Common mistakes.**

- "Some customers were impacted."
- Counting requests instead of customers.
- Omitting partners and internal consumers.
- Silence on data integrity, which readers will assume is bad news.

**Example.** 4,180 failed submissions from 3,090 distinct customer IDs between 09:12 and 10:26 (log query PIR-0412-failed, de-duplicated by customer ID), about 11% of submissions in the window. Two enterprise partners contacted at 11:30; both confirmed the estimate. No orders lost or duplicated, verified by reconciling the queue against the orders table at 11:05.

**Ask.** Who was affected, what did they see, how many (and how was that counted), for how long, what business metrics and commitments were hit, who was contacted, what was not affected, and was any data lost?

#### Q-006 (blocking, `PIR-IMPACT-QUANTIFIED` at `$.customer_impact.how_many`)

- **Finding:** how_many carries no number (digits in an id, a date or a time do not count); give the count and its basis, or write 'not determined: <why>'
- **Question:** How many customers were affected, and how was that counted? If it cannot be determined, say why.
- **A complete answer:** A count with its basis (the query and any de-duplication), or "not determined:" followed by the reason.
- **Goes into:** `$.customer_impact.how_many`

### 5. Incident response and post-incident analysis (writing order 4)

**What good looks like.** An honest account of what the response missed and how it can be fixed, broken down by detection, diagnosis, remediation, coordination and prevention. Each gap states its effect on the incident in time or impact, which is what makes corrective actions prioritisable. Record what went well and why, because those practices should be kept. This section identifies the distinct problems as channels of inquiry; the Five Whys explain them.

**Common mistakes.**

- Only listing what went well.
- Gaps with no stated effect.
- Mixing causes with symptoms.
- Writing "human error" anywhere.

**Example.** Detection: the only alert requires 5% errors for 10 minutes, so it fired 15 minutes after impact start and 6 after customer care had noticed; effect, 9 minutes with no signal and 6 more without monitoring. Diagnosis: pool saturation not on the dashboard; effect, around 25 of the 44 minutes of time to know. Channels: (1) why the change exhausted the pool; (2) why the alert took 15 minutes; (3) why diagnosis took 44.

**Ask.** For detection, diagnosis and remediation in turn: what slowed us down or what did we miss, and what did it cost in time or impact? What went well? What distinct problems need their own Five Whys chain?

#### Q-007 (blocking, `PIR-MISSED-AREAS` at `$.response_analysis.missed`)

- **Finding:** response_analysis.missed has no 'diagnosis' entry; say what slowed diagnosis down and what it cost, or that nothing did and why
- **Question:** For this area of the response: what slowed it down or what was missed, and what did it cost in time or impact? If nothing did, say so and why.
- **A complete answer:** An entry with the area, the gap and its effect.
- **Goes into:** `$.response_analysis.missed`

#### Q-008 (blocking, `PIR-MISSED-AREAS` at `$.response_analysis.missed`)

- **Finding:** response_analysis.missed has no 'remediation' entry; say what slowed remediation down and what it cost, or that nothing did and why
- **Question:** For this area of the response: what slowed it down or what was missed, and what did it cost in time or impact? If nothing did, say so and why.
- **A complete answer:** An entry with the area, the gap and its effect.
- **Goes into:** `$.response_analysis.missed`

#### Q-009 (blocking, `PIR-CHANNEL-NO-CHAIN` at `$.five_whys`)

- **Finding:** CH-2 has no Five Whys chain; every channel of inquiry is explained by one
- **Question:** This channel of inquiry has no Five Whys chain. Starting from the observed fact, why did it happen, and why that, until the answer is a process, design or tooling gap?
- **A complete answer:** A chain with an id RC-x, a kind, the channel, the problem statement, at least three whys each with evidence, and a root cause.
- **Goes into:** `$.five_whys`

### 6. Five Whys (writing order 5)

**What good looks like.** One chain per channel of inquiry. Each chain starts from an observed fact and asks why until it reaches a cause that is a process, design or tooling gap rather than an action by an individual, and that would have prevented the problem regardless of who was on shift. Four to six whys is typical; the number is not magic. Each answer cites evidence from the timeline or metrics. Chains of kind failure, detection and resolution are required; a prior-actions chain is required for a repeat incident.

**Common mistakes.**

- Stopping at "the engineer changed the config" (that is where the chain starts).
- A chain that reaches the right answer at why 2 and then pads to five.
- Answers with no evidence.
- One chain for everything.

**Example.** Chain A (failure). Why did requests fail? Pool in-use 60 of 60 (FIG-2A). Why exhausted? CHG-88213 raised concurrency 50 to 200 against 60 connections. Why could it be raised alone? The two settings are tuned independently. Why not caught? Not load-tested. Why not? Change policy classes config-only changes as low risk. RC-A: change policy treats capacity-affecting configuration as low risk.

**Ask.** For each channel of inquiry, state the problem as an observed fact, then ask why until the answer is a process, design or tooling gap. Give the evidence for each answer.

#### Q-010 (blocking, `PIR-CHAIN-KINDS` at `$.five_whys`)

- **Finding:** no Five Whys chain of kind 'detection'; the deck asks for separate chains that follow the failure, the detection gap and the slow fix
- **Question:** No chain follows this line of inquiry. What is the observed fact it starts from, and why did it happen?
- **A complete answer:** A chain of that kind with at least three evidenced whys and a root cause.
- **Goes into:** `$.five_whys`

#### Q-011 (blocking, `PIR-CHAIN-KINDS` at `$.five_whys`)

- **Finding:** no Five Whys chain of kind 'resolution'; the deck asks for separate chains that follow the failure, the detection gap and the slow fix
- **Question:** No chain follows this line of inquiry. What is the observed fact it starts from, and why did it happen?
- **A complete answer:** A chain of that kind with at least three evidenced whys and a root cause.
- **Goes into:** `$.five_whys`

#### Q-012 (blocking, `PIR-WHY-DEPTH` at `$.five_whys[0].whys`)

- **Finding:** RC-A has 2 why(s); fewer than 3 has not reached a process cause
- **Question:** This chain stops before it reaches a process cause. Why did the last answer happen?
- **A complete answer:** Further whys, each with evidence, until the cause would hold regardless of who was on shift.
- **Goes into:** `$.five_whys[0].whys`

### 8. Corrective actions (writing order 7)

**What good looks like.** High-level solutions that follow from the lessons, each tied to the lesson it addresses and each decomposed into action items. For every lesson ask the halving questions: what would halve the time to detect (health metrics, alarms)? the time to know (diagnostic metrics, triage tools)? the time to remediate (recovery tools, automation, automated rollback for deployment-related incidents)? Then ask what prevents recurrence altogether.

**Common mistakes.**

- Corrective actions with no action items (they never happen).
- Only prevention and nothing for detection or recovery.
- Actions scoped to this team when the gap is shared.

**Example.** CA-2 (LL-2, halves TTD): alert on the order-submit success SLO using multi-window burn rate, so a real 11% failure pages within 2 minutes without adding noise. Action items AI-3, AI-4.

**Ask.** For each lesson: what will we change? Which of time to detect, time to know, time to remediate, or prevention does it improve?

#### Q-013 (advisory, `PIR-CA-NO-HALVING` at `$.corrective_actions`)

- **Finding:** no corrective action improves time to detect, time to know or time to remediate; the deck asks what would halve each
- **Question:** None of the corrective actions improves time to detect, time to know or time to remediate. What would halve each of them?
- **A complete answer:** At least one corrective action with improves set to ttd, ttk or ttr, or the reason none applies, recorded in the ledger.
- **Goes into:** `$.corrective_actions`

### 9. Action items (writing order 8)

**What good looks like.** Individual tasks that someone can do and someone else can verify as done, each traced to a corrective action, with an owner (a person or team who has agreed to it), a due date that is reasonable for the work rather than driven by the roadmap, a status, and a sentence on how it helps prevent recurrence. Be bold: if another team or a shared tool is the right place for the fix, say so and engage them. Never assign an action to someone who has not agreed. Five well-chosen items beat twenty.

**Common mistakes.**

- "Investigate" or "Consider" items with no end state.
- Owners who were not asked.
- Due dates of "Q4".
- Items that address the symptom but would not stop the next occurrence.

**Example.** AI-3 (CA-2): implement a multi-window burn-rate alert on the order-submit success SLO, paging the Order Capture on-call. Owner: Order Capture SRE champion (agreed). Due 2026-10-03. Halves TTD: an 11% failure pages within about 2 minutes.

**Ask.** For each corrective action: what are the concrete, verifiable tasks, who has agreed to own each, by when, and how does each prevent recurrence?

#### Q-014 (blocking, `PIR-AI-VAGUE` at `$.action_items[0].statement`)

- **Finding:** AI-1 opens with 'investigate', which has no done state; name the output, where it lands and the decision it feeds
- **Question:** This action item has no done state. What will exist or be true when it is complete?
- **A complete answer:** A statement someone other than the owner could verify as done.
- **Goes into:** `$.action_items[0].statement`

#### Q-015 (advisory, `PIR-AI-NOT-AGREED` at `$.action_items[0].owner_agreed`)

- **Finding:** AI-1's owner has not agreed to it; never blindly assign action items (blocking from GO review)
- **Question:** Has the owner agreed to this action item? If not, who will ask them, and by when?
- **A complete answer:** owner_agreed set true once confirmed with the owner. Never assign an action to someone who has not agreed.
- **Goes into:** `$.action_items[0].owner_agreed`

### 1. Summary (writing order 9)

**What good looks like.** A single paragraph a reader with no context can understand in under a minute. It names the application, the customer-facing metric that moved, when, what happened in rough sequence, and the customer impact in numbers. It is written last, after every other section, because it summarises them. It contains no new facts that are not in the body. Pattern: <Application> experienced <metric> at <date time>. <What happened, rough timeline>. <Customer impact>.

**Common mistakes.**

- Writing it first and never updating it.
- Describing the fix without the impact.
- Infrastructure language ("pods restarted") instead of customer language ("orders failed").
- Vague quantities ("some customers", "a short period").

**Example.** Order Capture API experienced an 11% HTTP 5xx error rate on order submissions from 09:12 to 10:26 AEST on 3 September 2026. Change CHG-88213, deployed at 09:04, raised the service's downstream concurrency limit from 50 to 200 without raising the database connection pool (fixed at 60), and the pool was exhausted under normal Wednesday-morning load. An alert fired at 09:27, pool exhaustion was confirmed as the cause at 10:05, and a rollback restored normal error rates at 10:26. Approximately 4,200 order submissions from around 3,100 customers failed during the window and 612 queued orders were delivered up to 40 minutes late. No orders were lost or duplicated.

**Ask.** Now that every other section is written, summarise it in one paragraph following the pattern. Name the service, the metric, the date and time, the sequence, and the impact in numbers.

#### Q-016 (blocking, `PIR-SUMMARY-SERVICE` at `$.summary`)

- **Finding:** summary does not name the primary service 'Order Capture API'; the pattern starts '<Application> experienced <metric>'
- **Question:** The summary does not name the primary service. Rewrite the opening sentence as "<Application> experienced <metric> at <date time>".
- **A complete answer:** One paragraph whose first sentence starts with the primary service's name.
- **Goes into:** `$.summary`

#### Q-017 (blocking, `PIR-SUMMARY-NUMBER` at `$.summary`)

- **Finding:** summary carries no figure (digits in an id, a date or a time do not count); state the metric and the customer impact in figures
- **Question:** The summary carries no numbers. What value did the customer-facing metric reach, and how many customers, orders or requests were affected?
- **A complete answer:** The metric with its value and the impact counts, as figures, in the paragraph.
- **Goes into:** `$.summary`

#### Q-018 (blocking, `PIR-SUMMARY-DATE` at `$.summary`)

- **Finding:** summary does not say when; the pattern is '<Application> experienced <metric> at <date time>'
- **Question:** When did it happen? The summary must say the date and the time.
- **A complete answer:** The date and time with timezone in the opening sentence.
- **Goes into:** `$.summary`

### all. Whole document (writing order 99)

**What good looks like.** The PIR is blameless throughout: it describes processes, not people, and the blame lexicon (catalogs/blame-lexicon.yaml) is a blocker in any prose field. Identifiers are unique. Every accountable party (PIR owner, action-item owner, question owner) is a person or a team, never a placeholder.

**Common mistakes.**

- "Human error" in a root cause.
- Two action items with the same id after a copy-paste.
- An owner of "TBD".

**Example.** Not "the engineer carelessly raised the limit" but "the concurrency limit was raised without a corresponding pool change; nothing documents or enforces the relationship".

**Ask.** Reword any statement that names or judges a person so that it names the process gap instead.

#### Q-019 (blocking, `PIR-OWNER-PLACEHOLDER` at `$.action_items[0].owner`)

- **Finding:** AI-1 has no accountable owner ('TBD'); name the person or team who agreed to it
- **Question:** This accountability field names nobody. Which person or team has agreed to own it?
- **A complete answer:** A person or team name, confirmed with them, never a placeholder.
- **Goes into:** `$.action_items[0].owner`

#### Q-020 (blocking, `PIR-EVIDENCE-PLACEHOLDER` at `$.action_items[0].prevents_recurrence`)

- **Finding:** 'To be confirmed once the policy change is scoped.' cites nothing ('To be confirmed'); name the dashboard, log, record or decision it comes from
- **Question:** This field cites nothing yet. Which dashboard, log, record or decision supports it, or what effect does it actually have?
- **A complete answer:** A specific source (a dashboard and panel, a log query, a ticket, a decision log entry), or for an effect, the mechanism by which it prevents recurrence.
- **Goes into:** `$.action_items[0].prevents_recurrence`

## Response format for the PIR owner

One block per question:

```text
Question ID: <The Q-nnn id exactly as shown.>
Answer: <The fact, number, sentence or structure asked for, in the answer shape given.>
Evidence: <Where the answer can be checked: a query, panel, ticket, record or document.>
Answered by: <The person or team who gave the answer, never a role placeholder.>
Date: <When the answer was given, YYYY-MM-DD.>
Deferred or waived: <If not answered: deferred to whom and by when, or waived for what reason.>
```

## After the answers arrive

1. Open a clarification ledger from this interview (tools/open_pir_ledger.py) and record each answer in it: the answer, its evidence, who gave it and when.
2. Transcribe each answer into the packet and record where it landed in the ledger's applied_to (JSON pointers into the packet).
3. Re-run tools/validate_pir.py on the packet. If findings remain, generate the next round of this interview with --round incremented; otherwise the packet is ready for review.
