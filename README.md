# PIR Assessor

**Assess, interview and review Post-Incident Reviews (PIRs) with an AI assistant, without letting it
make anything up.**

PIR Assessor gives GitHub Copilot in VS Code, and Google Antigravity, three agents and a set of gate
tools for writing PIRs that hold up:

| Command | Agent | What it does |
|---|---|---|
| `/assess-pir <sources>` | `pir-assessor` | Transcribes what you have (incident chat, decision log, draft notes, dashboards) into a structured PIR *packet*, runs the gate, and reports every gap. Nothing is invented. |
| `/interview-pir <packet> <round>` | `pir-interviewer` | Turns the gaps into the exact questions the PIR owner must answer, records each answer with who gave it and the evidence, applies them, and re-runs the gate. |
| `/review-pir <packet> <stage>` | `pir-reviewer` | Forms the judgements the gate cannot (root causes at process level, honest lessons, actions that would prevent recurrence) and files a reviewer-findings record. |

When the gate is clean, the finished PIR is rendered into the PIR template as a Word document.

A PIR that says "some customers were impacted", stops its Five Whys at "the engineer changed the
config", or lists "investigate the alerting" as an action is not a review: the decisions about what
happened and what will change are left for someone to make later, or never. PIR Assessor makes each
gap explicit, asks the owner the question that closes it, and does not call a PIR complete until the
chain from evidence to root cause to lesson to corrective action to owned, dated action item is
unbroken. It is blameless throughout: the PIR is about processes and tools, never people, while every
owner and answerer is named.

## Get started

1. **[Download](https://github.com/gigantem/pir-bar-raiser/releases/latest)** the package for your
   editor from the latest release: `pir-assessor-<version>.vsix` for VS Code, or
   `pir-assessor-<version>-antigravity.zip` (Windows) / `.tar.gz` (macOS, Linux) for Antigravity.
2. **[Install](docs/install.md)** Python 3.12 or later and the three packages the tools need, then
   the extension.
3. **[Use it](docs/usage.md):** open the repository that will hold your PIR and run `/assess-pir`.

If something does not work, see **[Troubleshooting](docs/troubleshooting.md)** and the
**[FAQ](docs/faq.md)**. How the method works, in full, is **[docs/method.md](docs/method.md)**; what
changed in each release is **[docs/release-notes.md](docs/release-notes.md)**.

## What you need

- **VS Code 1.109 or later with GitHub Copilot Chat** (agent mode), or **Google Antigravity** (App,
  IDE or CLI).
- **Python 3.12 or later**, with PyYAML, jsonschema and python-docx. The extension carries a
  `requirements.txt` for them; [Install](docs/install.md) shows the command for each system.
- Optional: Word or LibreOffice, to open the rendered `.docx`.

## Your data

The extensions run no code of their own, and the bundled tools run on your machine and make no
network call. The assistant they drive does: whatever the agents read (your sources, the packet, the
interview and the ledger, including the names of the owners and answerers a PIR must carry) goes to
the model behind GitHub Copilot Chat or Antigravity, under your terms with that service. Keep real
PIRs in a **private** repository, and give the agents only what your organisation lets you share with
that service.

## What the gate holds a PIR to

In brief: the five lifecycle timestamps carry a timezone and are in order, and the declared key
timings equal the ones derived from them; the timeline is ascending, evidenced and anchored to those
timestamps; at least one figure is compared with a normal baseline and annotated; impact counts carry
a number or say `not determined:` and why; detection, diagnosis and remediation are each analysed;
every channel of inquiry has a Five Whys chain with evidence, and chains for the failure, its
detection and its resolution exist; every root cause has a lesson, every lesson a corrective action,
and every corrective action an action item with a named owner who agreed, a due date after the
incident and within a year of it, and a stated effect on recurrence; an action that opens with a
vague verb ("investigate", "raise awareness") is refused, and one that names the concrete output that
makes it done is left for a person to confirm; and blame vocabulary anywhere is a blocker.

A green gate is not a finished PIR. The gate proves presence, shape, consistency and vocabulary;
whether a root cause is true or an action would prevent recurrence is the owner's and the reviewer's
judgement, and the tools make sure the question is asked and the answer recorded with who gave it.
The full rule set is in [docs/method.md](docs/method.md).

## Working from source

Everything the extensions contain is built from this repository, and the tools run from a clone too:

```bash
git clone https://github.com/gigantem/pir-bar-raiser.git && cd pir-bar-raiser
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python --require-hashes -r requirements-dev.lock

.venv/bin/python tools/validate_pir.py examples/good/order-capture-pool-exhaustion.yaml   # a PIR that passes
.venv/bin/python tools/validate_pir.py examples/draft/order-capture-draft.yaml            # a draft and its gaps
.venv/bin/python tools/render_pir_docx.py --packet examples/good/order-capture-pool-exhaustion.yaml --output PIR.docx

bash tools/run_local_gates.sh          # every gate CI runs, in one command
python tools/build_vsix.py --package   # out/pir-assessor-<version>.vsix (needs node 22 and npm)
python tools/build_antigravity.py --package
```

[CONTRIBUTING.md](CONTRIBUTING.md) explains how the pieces fit and what a change must carry.

### What is in this repository

The inventory is checked by `tests/test_tool_and_doc_inventory.py`: it fails if a tool, schema or
catalog is missing below, or if the list names a file that does not exist.

**Contracts** (`schemas/`)

- `schemas/pir-packet.schema.json`: the PIR packet, one key per template section.
- `schemas/pir-interview.schema.json`: the owner interview, findings grouped by section with the
  catalog's question attached to each.
- `schemas/pir-clarification-ledger.schema.json`: the record of one interview round: every answer,
  its evidence, who gave it and where it went in the packet.
- `schemas/pir-review.schema.json`: one reviewer's findings on one packet at one review stage.

**Catalogs** (`catalogs/`)

- `catalogs/pir-section-expectations.yaml`: the template's Appendix A, machine-readable: per section,
  the expectation, common mistakes, a worked example, the interview prompt and the rules that belong
  to it.
- `catalogs/pir-rule-questions.yaml`: one question per validator rule; the interview attaches it to
  every finding.
- `catalogs/pir-principles.yaml`: the principles, timing, presenting and reviewing guidance; rendered
  as the template's Appendix B.
- `catalogs/blame-lexicon.yaml`: terms that make a PIR about people; a blocker anywhere.
- `catalogs/vague-action-lexicon.yaml`: verbs that leave an action item with no done state, and the
  concrete output each one's remediation asks for.

**The gate**

- `tools/validate_pir.py`: the packet validator, with stable `PIR-` rule ids; writes the gap report.
- `tools/validate_pir_ledger.py`: the ledger validator (`LEDGER-` rules), held against its interview
  and its packet.
- `tools/validate_pir_review.py`: the review validator (`REVIEW-` rules); recomputes counts and gate
  evidence, and refuses a PASS the gate contradicts.
- `tools/check_artifact_conventions.py`: every file under `interviews/`, `clarifications/` and
  `reviews/` is named by its convention and valid against its own contract.
- `tools/validate_catalogs.py`: the catalogs agree with the schema and the validator.
- `tools/check_fixtures.py`: every mutation fixture trips the rules it names.
- `tools/report_rule_coverage.py`: every rule has a fixture, and no fixture names a rule that does
  not exist.

**The interview loop and the document**

- `tools/generate_pir_interview.py`: packet to owner interview, from a fresh validation.
- `tools/render_pir_interview.py`: interview to markdown for the room.
- `tools/open_pir_ledger.py`: interview to a ledger with every question open.
- `tools/render_pir_review_scaffold.py`: packet to a review scaffold, every judgement left blank;
  it cannot validate as a review.
- `tools/render_pir_docx.py`: the blank template, or a finished packet, as `.docx` or markdown.

**Libraries, packaging and the runner**

- `tools/pir_interview.py`: load, validate and walk interviews.
- `tools/json_pointer.py`: strict JSON Pointer resolution, used to prove each `applied_to` pointer
  names something in the packet.
- `tools/docx_outline.py`: a `.docx` as `[style] text` lines in document order, for comparison.
- `tools/pir_fixtures.py`: the mutation-fixture materialiser the fixture checks use.
- `tools/extension_bundle.py`: what both extensions share: the staged skill folder, its checks, the
  end-to-end run from a fresh workspace, and the reproducible archives.
- `tools/build_vsix.py`: builds, verifies and packages the VS Code extension.
- `tools/build_antigravity.py`: builds, verifies, packages and installs the Antigravity plugin.
- `tools/run_local_gates.sh`: runs every gate; a test holds it to CI, invocation by invocation.

The agents, prompts and skill the extensions carry are under `assistant/`; the extensions' own
manifests and user READMEs under `vsix/` and `antigravity/`; the worked example in every lifecycle
state, and the mutation fixtures that prove each rule, under `examples/`; the templates under
`docs/templates/`.

## Licence

GPL-3.0-or-later; see [LICENSE](LICENSE) and [NOTICE](NOTICE).
Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>.
