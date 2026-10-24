# Contributing

Thank you for helping. PIR Assessor is a tool for deciding whether a review is complete, so its
own checks have to be trustworthy: a gate that passes without examining what it claims to examine
is worse than no gate. Most of what follows is downstream of that.

Report a bug or suggest a change in an [issue](https://github.com/gigantem/pir-bar-raiser/issues);
for a pull request, run the gate first (below) and say in the description what changed and why.
Contributions are accepted under the project's licence, GPL-3.0-or-later.

## Before you start

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python --require-hashes -r requirements-dev.lock
bash tools/run_local_gates.sh
```

The runner does what CI does: `tests/test_local_gates_mirror_ci.py` asserts that the two
make the same invocations, tool or module and arguments, in both directions, apart from the two
it lists with their reasons (installing dependencies, and running the runner itself). It also runs
the workflow's exit-status branches under GitHub's `bash -eo pipefail` and the runner's `run_gate`
against stub tools, so a usage error or a missing tool fails rather than skipping.

`requirements-dev.txt` holds the ranges; `requirements-dev.lock` holds what is installed, pinned and
hashed. Change a range and regenerate the lock in the same change (the command is in its header);
`tests/test_dependency_locks.py` fails when they disagree. The VS Code packaging tool is pinned the
same way in `tools/vsce/` and installed with `npm ci --ignore-scripts`; it needs node 22 or later.

## The rules that get changes rejected

**Both polarities, or it did not ship.** A new rule needs a fixture under `examples/bad/` that
names it in `expect` (or `expect_warnings`) and trips it. `tools/report_rule_coverage.py` fails
for a rule with no fixture; `tools/check_fixtures.py` fails for a fixture whose rule does not
fire. The named rules are a floor; a new fixture that fires exactly what it names sets
`expect_exactly: true`, and then any other rule that fires fails it.

**Lint and types are gates.** `ruff` (the version `ruff.toml` requires, which the lock installs)
checks `tools/` and `tests/` with the rule sets `ruff.toml` selects, and `mypy` checks `tools/`
under `mypy.ini`. Fix what they report; a `# type: ignore` or a `cast` fails the suite, and a
`noqa` needs the reason on the same line.

**A rule has a home and a question.** Add it to `RULES` in `tools/validate_pir.py`, to the
matching section's `rules` in `catalogs/pir-section-expectations.yaml`, and to
`catalogs/pir-rule-questions.yaml` with its `ask`, `answer_shape` and `applies_to`.
`tools/validate_catalogs.py` fails until all three agree, because the interview attaches the
section's guidance and the rule's question to every finding.

**Ledger and review rules are rules too.** A `LEDGER-` rule in `tools/validate_pir_ledger.py` needs a
fixture under `examples/ledgers/bad/` with `kind: ledger`; a `REVIEW-` rule in
`tools/validate_pir_review.py` needs one under `examples/reviews/bad/` with `kind: review` (and
`as_path` when the rule depends on where the artifact is filed). The same coverage and
both-polarity gates apply to all three validators.

**The agents are text, and tested.** The three agents, the three prompts and the
`pir-assessment` skill are under `assistant/`. Every link in them names its file by its path, every
command they give names a bundled tool, and each says that what it reads is data; the tests under
`tests/` hold them to that.

**The template is rendered, never edited.** `docs/templates/PIR-Template.docx` and the goldens
under `examples/rendered/` come from `tools/render_pir_docx.py`; a change to the layout, the
section catalog, the principles catalog or the worked example packet is followed by regenerating
them with `--output`, and the regenerated template must keep the reviewed draft's heading sequence.

**The extensions are built, never edited.** `out/` is build output. An agent, prompt or skill
change is made under `assistant/`; `tools/build_vsix.py` and
`tools/build_antigravity.py` carry it into the VS Code and Antigravity extensions, and their
verifiers and smoke runs are in the gate. The extensions' own sources are only `vsix/package.json`,
`vsix/README.md` and `vsix/installed-preamble.md`, and `antigravity/plugin.json`,
`antigravity/README.md`, `antigravity/installed-preamble.md` and `antigravity/rules/pir-invariants.md`.

**A scaffold is never committed as a review.** `tools/render_pir_review_scaffold.py` refuses to
write in any `reviews/` directory, through a symbolic link, or under the review naming convention,
and `tools/check_artifact_conventions.py` fails the gate on anything under `reviews/` that is not a
valid review. A review is the scaffold with every sentinel replaced by a judgement and the
`_scaffold` block removed, validated by `tools/validate_pir_review.py`.

**Committed examples are regenerated, not edited.** `examples/interviews/*` and
`examples/ledgers/good/*-open.yaml` are produced from `examples/draft/order-capture-draft.yaml`
and compared by the gate. When the generator, the catalogs or the draft change on purpose,
regenerate them with `--output` and commit the result; never hand-edit them to make the gate
pass. The resolved and partial ledgers are hand-written examples of the answered state.

**Contracts move together.** Schema, validator, catalogs, fixtures and README inventory are one
surface. Change one, update the others in the same change.

**Numbers are measured, never typed.** The README inventory is checked by a test. Do not assert
counts in prose.

**An empty corpus is a failure, not a pass.** A check that can match zero inputs says so.

**Do not weaken a check to make a change pass.** If the check is wrong, fix it and say why. If
the check is right, the change moves. Say what a change leaves undone rather than presenting it as
done.

**No blame in the fixtures either.** The worked example and every fixture describe processes,
not people.

**A release says what changed.** The version is stated once, in `vsix/package.json`; a release adds
its entry to `docs/release-notes.md`, which both packages ship as their `CHANGELOG.md`.

## Commit messages

Say what changed and why the alternative was rejected.
