# Using PIR Assessor

This guide follows one PIR from raw sources to a finished document. It assumes the extension is
installed ([Install](install.md)); the commands are the same in VS Code with Copilot Chat and in
Antigravity.

- [Set up the workspace](#set-up-the-workspace)
- [1. Assess](#1-assess) · [2. Interview](#2-interview) · [3. Review](#3-review) · [4. Render](#4-render)
- [Try it on the worked example](#try-it-on-the-worked-example)
- [Running the tools yourself](#running-the-tools-yourself)
- [What the results mean](#what-the-results-mean)

## Set up the workspace

Open the repository that will hold the PIR as your workspace, in VS Code or Antigravity. Use a
**private** repository: a real PIR names the people who own it and answered for it.

The agents keep everything about a PIR in four folders at the workspace root, and create them as
they need them:

```text
pirs/<stem>.yaml                                     the packet: the PIR itself, one key per template section
interviews/<stem>/<YYYYMMDDTHHMMSSZ>-I<nn>.yaml      the owner interview for round nn, and its .md for the room
clarifications/<stem>/<YYYYMMDDTHHMMSSZ>-L<nn>.yaml  the ledger: who answered what, with what evidence, and where it went
reviews/<stem>/<YYYYMMDDTHHMMSSZ>-<reviewer>.json    a reviewer's findings, one per review stage
```

`<stem>` is a short name you choose for the incident (for example `order-capture-2026-09-04`); the
timestamps are UTC. The folder READMEs inside the extension's skill folder describe each convention
in detail.

## 1. Assess

```text
/assess-pir <your sources>
```

Point it at whatever exists: a chat export from the incident channel, the war-room decision log, a
draft PIR, dashboard exports, timelines. The `pir-assessor` agent transcribes them into
`pirs/<stem>.yaml`, section by section in the order the template is written (timeline first, summary
last), and runs the gate.

It never fills a gap with a guess. A section the sources do not support stays absent, and the gate
reports it. The result is the packet and a table of findings by section: that table *is* the
assessment.

If `pirs/<stem>.yaml` already exists, the agent treats it as the PIR: it validates it first and
changes it only where a source you gave says something the packet does not.

## 2. Interview

```text
/interview-pir pirs/<stem>.yaml 1
```

The `pir-interviewer` agent turns every finding into the question that closes it, grouped by
template section, each with what good looks like and an example. It writes the interview under
`interviews/<stem>/` and renders it as markdown for the meeting with the PIR owner.

As the owner answers, the agent records each answer in the ledger under `clarifications/<stem>/`:
the answer, the evidence for it, who gave it and when. It then applies the answers to the packet,
notes where each one landed, and re-runs the gate. Answers come only from people: a file can be the
evidence for an answer, never its author.

Repeat with round `2`, `3`… while findings remain. A question can also be deferred (with an owner and
a date) or waived (with a reason); both are recorded, and the gate still holds the packet to the rule.

## 3. Review

```text
/review-pir pirs/<stem>.yaml <stage>
```

`<stage>` is one of:

| Stage | When |
|---|---|
| `readiness` | Before the PIR goes to people: is it ready for a team review? Any packet status. |
| `team` | The team review. The packet's status must be `in_team_review` or later. |
| `go` | The GO review: the review a PIR passes before it is published. Status `in_go_review` or later. |
| `exec_go` | The executive GO review. Status `in_go_review` or later. |

The packet's `status` (`draft`, `in_team_review`, `in_go_review`, `published`) says how far the PIR has
got, and it is the PIR owner's to move on, by editing the packet or by telling the agent. A review
cannot be ahead of it: a `go` review of a packet still in `draft` is refused. Start with `readiness`,
which fits any status.

The `pir-reviewer` agent starts from a scaffold with every judgement left blank, then forms those
judgements itself: are the root causes at the level of process and design, not people; are the
lessons honest; would each corrective action actually prevent recurrence or shorten detection,
diagnosis or repair; is everything blameless. It records a coverage judgement for every template
section, so even a review with no findings says what was checked, and files the result under
`reviews/<stem>/`.

A packet the gate rejects cannot pass review. A passing review records the exact packet it reviewed;
if the packet changes afterwards, that pass no longer counts and the packet is reviewed again.

## 4. Render

When the PIR is complete, ask the agent to render it, or run the renderer yourself:

```bash
python "<skill folder>/tools/render_pir_docx.py" --packet pirs/<stem>.yaml --output <stem>.docx
python "<skill folder>/tools/render_pir_docx.py" --packet pirs/<stem>.yaml --format md
```

The document follows the PIR template section by section. A section the packet does not have says
"not yet provided" rather than being filled in. `<skill folder>` is the extension's
`pir-assessment` folder; [Install](install.md#2-python-and-its-packages) lists where it is.

The table of contents is a field the editor fills when asked: in Word, right-click it and choose
**Update Field**; in LibreOffice, **Tools › Update › Update All**.

## Try it on the worked example

The extension carries a fictional incident in every state of its life, under
`<skill folder>/examples/`: a day-two draft with gaps (`draft/`), its interview (`interviews/`), the
ledgers that answered it (`ledgers/good/`), the finished packet (`good/`) and two reviews
(`reviews/good/`). To see the whole loop on something safe, copy the draft into a scratch workspace:

```bash
mkdir -p pirs && cp "<skill folder>/examples/draft/order-capture-draft.yaml" pirs/
```

then run `/interview-pir pirs/order-capture-draft.yaml 1` and compare what the agent asks with
`examples/interviews/`.

## Running the tools yourself

Every step the agents take is a plain command-line tool in `<skill folder>/tools/`, and you can run
any of them yourself, from the root of the workspace that holds the PIR:

```bash
python "<skill folder>/tools/validate_pir.py" pirs/<stem>.yaml --gap-report gap.json
python "<skill folder>/tools/generate_pir_interview.py" --packet pirs/<stem>.yaml --round 1 --output interviews/<stem>/<ts>-I01.yaml
python "<skill folder>/tools/render_pir_interview.py" interviews/<stem>/<ts>-I01.yaml --output interviews/<stem>/<ts>-I01.md
python "<skill folder>/tools/open_pir_ledger.py" interviews/<stem>/<ts>-I01.yaml --output clarifications/<stem>/<ts>-L01.yaml
python "<skill folder>/tools/validate_pir_ledger.py" clarifications/<stem>/<ts>-L01.yaml
python "<skill folder>/tools/render_pir_review_scaffold.py" pirs/<stem>.yaml --review-stage go --output <stem>.scaffold.json
python "<skill folder>/tools/validate_pir_review.py" reviews/<stem>/<ts>-<reviewer>.json
python "<skill folder>/tools/check_artifact_conventions.py"
```

Each one answers `--help`. `<ts>` is the UTC time as `YYYYMMDDTHHMMSSZ`; in a POSIX shell,
`date -u +%Y%m%dT%H%M%SZ` prints it. Because the tools need nothing but Python, they also work with
any other assistant, or none.

## What the results mean

- **Exit codes.** The three validators exit `0` when the file passes, `1` when it has errors (the
  findings are the result, not a failure of the tool), and `2` when they could not run at all: a
  wrong argument, or a file that cannot be opened, such as a mistyped path ("cannot be opened, so
  nothing was validated"). Stop and fix that before reading anything into it. A file that opens but
  is not valid YAML or JSON is a finding, exit `1`. The generators and renderers exit `0` when they
  wrote their output and `1` when they could not.
- **Errors and warnings.** An error blocks: the PIR is not complete until it is gone. A warning is
  the softer guidance (averages instead of percentiles, a shallow Five Whys, a late due date) and asks
  a person to look.
- **Rule ids.** Every finding carries a stable id (`PIR-…`, `LEDGER-…`, `REVIEW-…`), the template
  section it belongs to and where in the file it is. The interview asks one question per finding.
- **SKIP is not PASS.** `check_artifact_conventions.py` reports a skip when there is nothing filed
  yet, with exit `2` and a line starting `SKIP:`; that means nothing was checked, not that everything
  is fine.
- **A green gate is not a finished PIR.** It proves presence, shape, consistency and vocabulary. The
  review is where substance is judged.

[docs/method.md](method.md) explains the whole method, rule by rule.
