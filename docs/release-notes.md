# PIR Assessor release notes

## 0.2.1 (2026-10-27)

- **Security.** The agents' prerequisite check and the install command now run Python with `-P`
  (`python -P -c "import yaml, jsonschema, docx"`, `python -P -m pip install ...`). Without it,
  Python imports a file from the folder it runs in before the real package, so a `yaml.py` or
  `pip.py` placed in a workspace could run as you when an agent checked its prerequisites. Upgrade
  to this release; if you run those commands yourself, add `-P` too.
- **Changed:** a validator given a file it cannot open (a mistyped path, a file it may not read, a
  directory) now exits `2` and says nothing was validated. Before, it reported one finding and exited
  `1`, which read as a PIR with one gap. A file that opens but is not valid YAML or JSON is still a
  finding, exit `1`.
- Documentation: the install guide gives the Windows paths in PowerShell's form, covers an older
  Python on Windows, and shows how to build from source with plain pip as well as uv; troubleshooting
  and the FAQ answer more of the questions first users ask; the repository has a security policy and
  an issue template. Report problems on the public repository's issues page, and security problems
  privately through its Security tab.
- Known limits, unchanged: neither package has yet been run in a live VS Code with Copilot Chat or a
  live Antigravity session.

## 0.2.0 (2026-10-24)

- Every file now carries the copyright notice: Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>.
  The licence is unchanged: GPL-3.0-or-later.
- No change to what the agents, workflows and tools do. The first public release: 0.1.1 was an
  internal build, and anyone who has it installs 0.2.0 over it as described in the README; nothing
  in a workspace needs to change.
- Packages and their `SHA256SUMS` are on the public repository's releases page; report problems on
  its issues page.

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
