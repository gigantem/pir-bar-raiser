# PIR Assessor for VS Code

Assess, interview and review Post-Incident Reviews with GitHub Copilot. The extension adds
three custom agents, three prompts and one skill to Copilot Chat; it runs no code of its own.
Full documentation (installing, using, troubleshooting, FAQ) and the source:
<https://github.com/gigantem/pir-bar-raiser>.

| You type in Copilot Chat | Agent | What happens |
|---|---|---|
| `/assess-pir <sources or packet>` | `pir-assessor` | Transcribes the PIR sources into `pirs/<stem>.yaml`, runs the gate, reports every gap. Nothing is invented. |
| `/interview-pir <packet> <round>` | `pir-interviewer` | Turns the gaps into the questions the owner must answer, records the answers in a ledger with who said what, applies them, re-validates. |
| `/review-pir <packet> <stage>` | `pir-reviewer` | Forms the judgements the gate cannot (root cause at process level, honest lessons, actions that prevent recurrence) and files a reviewer-findings artifact. |

The `pir-assessment` skill loads automatically when a request is about a PIR. It carries the gate
tools, the packet contract, the section catalog (the template's Appendix A, machine-readable),
the blame and vague-action lexicons, the reviewed template and a worked example.

## Prerequisites

- VS Code 1.109 or later with the GitHub Copilot Chat extension, agent mode enabled.
- Python 3.12 or later on `PATH` as `python`, with the three packages the tools import:

  ```
  python -m pip install -r "<extensions dir>/gigantem.pir-assessor-<version>/skills/pir-assessment/requirements.txt"
  ```

  `<extensions dir>` is `%USERPROFILE%\.vscode\extensions` on Windows, `~/.vscode/extensions`
  on macOS and Linux, and `~/.vscode-server/extensions` on the remote side of WSL, SSH or a
  container. The agents check the import before their first command and stop with this
  instruction if it fails; they do not work around it.
- Optional: Word, to open the rendered `.docx`.

## Install

The extension is installed from the file, not from the Marketplace. VS Code runs no code of
its own from it, and the bundled tools run locally and make no network call. The chat it drives
does. Whatever the agents read, the packet, the
interview and the ledger included, with the names of the owners and answerers a PIR must carry,
goes to the model behind GitHub Copilot Chat under your Copilot terms. Keep real PIRs in a
private repository, and give the agents only what your organisation lets you share with
Copilot.

You receive `pir-assessor-<version>.vsix` from whoever distributes the extension in your
organisation. This release has not yet been run in a VS Code with Copilot Chat enabled; report
anything that does not work to them.

- Extensions view (`Ctrl+Shift+X`) > `...` menu > **Install from VSIX...** > pick
  `pir-assessor-<version>.vsix`, or
- `code --install-extension pir-assessor-<version>.vsix`

Remote and WSL: the extension prefers the workspace side (`extensionKind: workspace`), so when you
are connected to WSL, a container or SSH, install it there too (the same command, run in that
VS Code window) so that the bundled tools sit where the shell runs.

To remove it: `code --uninstall-extension gigantem.pir-assessor`.

## Using it in a repository

Open the repository that will hold the PIR as the workspace. The agents keep the PIR's artifacts
in four directories at the workspace root and run every command from there:

```
pirs/<stem>.yaml                                  the packet, one key per template section
interviews/<stem>/<YYYYMMDDTHHMMSSZ>-I<nn>.yaml   the owner interview for round nn, plus its .md
clarifications/<stem>/<YYYYMMDDTHHMMSSZ>-L<nn>.yaml  the ledger: who answered what, and where it went
reviews/<stem>/<YYYYMMDDTHHMMSSZ>-<reviewer>.json  reviewer findings, one per review stage
```

Then, in Copilot Chat:

1. `/assess-pir` with the sources (the incident channel export, the war-room decision log, a draft
   PIR, dashboards). The packet lands under `pirs/`; the gate's findings are the report.
2. `/interview-pir pirs/<stem>.yaml 1`. The interview is rendered for the room; the ledger records
   each answer with the named person who gave it and the evidence; the agent applies the answers to
   the packet and re-runs the gate. Repeat with round 2 while findings remain.
3. `/review-pir pirs/<stem>.yaml go` (stages: `readiness`, `team`, `go`, `exec_go`). A packet the
   gate rejects cannot pass review; a green gate is not a finding-free PIR.
4. Ask the agent to render the finished PIR into the template:
   `python "<pir-assessment>/tools/render_pir_docx.py" --packet pirs/<stem>.yaml --output <stem>.docx`.

Each agent's instructions name the tools as `python <pir-assessment>/tools/<tool>.py`, where
`<pir-assessment>` is the skill folder inside the extension. Copilot sees that folder's location
when it loads the skill; if an agent asks for it, give the path from the prerequisites section.

## What the gate holds a PIR to

In brief: the five lifecycle timestamps carry a timezone and are ordered, and the declared key
timings equal the derived ones; the timeline is ascending, evidenced and anchored to those
timestamps; at least one annotated, baseline-compared figure; impact counts carry a number or say
`not determined:` and why; detection, diagnosis and remediation are each analysed; every channel
of inquiry has a Five Whys chain with evidence, and chains for the failure, its detection and its
resolution exist; every root cause has a lesson, every lesson a corrective action, every
corrective action an action item with a non-placeholder owner who agreed, a due date after the
incident and a stated recurrence effect; blame vocabulary anywhere is a blocker. The full rule
table, the catalogs and the worked example are inside the skill folder.

## Licence

GPL-3.0-or-later; see `LICENSE`. Every package is verified before release: every link resolves
inside it, every command names a bundled tool, and the bundled tools run the whole loop end to end
from a fresh workspace.
