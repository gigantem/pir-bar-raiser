# PIR Assessor release notes

## 0.2.0 (2026-10-24)

- Every file now carries the copyright notice: Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>.
  The licence is unchanged: GPL-3.0-or-later.
- No change to what the agents, workflows and tools do. Install it over 0.1.1 as described in the
  README; nothing in a workspace needs to change.

## 0.1.1 (2026-10-24)

The first release for users.

- Three agents: `pir-assessor` transcribes a Post-Incident Review's sources into a packet and
  reports every gap, `pir-interviewer` turns the gaps into the questions the PIR owner must answer
  and records who answered what, and `pir-reviewer` forms the judgements the gate cannot make.
- The `/assess-pir`, `/interview-pir` and `/review-pir` workflows, one per agent.
- The `pir-assessment` skill: the procedure and the review checklist, the gate tools, the packet,
  interview, ledger and review schemas, the section catalog, the blame and vague-action lexicons,
  the PIR template, and a worked example in every lifecycle state.
- In Antigravity, an always-on rule that holds the agents to the same invariants in any workspace.
- The tools need Python 3.12 or later with PyYAML, jsonschema and python-docx
  (`skills/pir-assessment/requirements.txt`). They run locally and make no network call.

Known limits: this release has not yet been run in VS Code with GitHub Copilot Chat, or in an
Antigravity App, IDE or CLI session. Every package is verified before release, and its tools run
the whole loop end to end from a fresh workspace, but report anything that does not work to whoever
gave you the package.
