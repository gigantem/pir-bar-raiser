#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
# run_local_gates.sh: run every gate this repo enforces, in one command.
#
# A runner over gates that already exist, not a curated subset: tests/test_local_gates_mirror_ci.py
# asserts that every tool .github/workflows/pir-gate.yml invokes also appears here.
#
# Contract:
#   * Runs ALL gates even when an early one fails, then prints a summary.
#   * Exits non-zero if any gate FAILED.
#   * A gate whose tooling is absent is reported SKIP, never PASS. A SKIP is not a pass.
#
# Usage:  bash tools/run_local_gates.sh [--quiet]
set -uo pipefail

QUIET=0
for arg in "$@"; do
  case "$arg" in
    --quiet) QUIET=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)" || exit 2

# Interpreter floor is 3.12 (.python-version). Prefer the repo's venv, then any conforming python.
PY=""
for cand in "${PYTHON:-}" .venv/bin/python python3.12 python3.13 python3.14 python3; do
  [ -z "$cand" ] && continue
  if command -v "$cand" >/dev/null 2>&1 || [ -x "$cand" ]; then
    if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
      PY="$cand"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo "FAIL: no Python >= 3.12 found; bootstrap with: uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python --require-hashes -r requirements-dev.lock" >&2
  exit 1
fi

PASS=(); FAIL=(); SKIP=()

run_gate() {
  local label="$1" probe="$2"; shift 2
  # Every probe is a tool this repository tracks. Its absence is damage to the tree, not a tool
  # that is "not installed", so it fails rather than skipping.
  if [ "$probe" != "-" ] && [ ! -e "$probe" ]; then
    FAIL+=("$label (missing: $probe)")
    printf '  FAIL  %s: %s is missing from the tree\n' "$label" "$probe"
    return
  fi
  local out rc last
  out="$("$@" 2>&1)"; rc=$?
  last="$(printf '%s\n' "$out" | tail -n 1)"
  if [ "$rc" -eq 0 ]; then
    PASS+=("$label"); printf '  PASS  %s\n' "$label"
  elif [ "$rc" -eq 2 ] && [ "${SKIP_ON_2:-0}" -eq 1 ] && [ "${last:0:5}" = "SKIP:" ]; then
    # Exit 2 with the tool's own SKIP: line is its "nothing to check" verdict, reported as SKIP,
    # never PASS. Exit 2 without it is argparse's usage error or a missing file, so it fails.
    SKIP+=("$label: ${last#SKIP: }"); printf '  SKIP  %s: %s\n' "$label" "$last"
  else
    FAIL+=("$label"); printf '  FAIL  %s (exit %d)\n' "$label" "$rc"
    [ "$QUIET" -eq 0 ] && printf '%s\n' "$out" | sed 's/^/          /' | tail -25
  fi
}

printf '=== local gates (%s) ===\n' "$PY"

# ------------------------------------------------------------- lint and format
run_gate "ruff check"          "-" "$PY" -m ruff check tools/ tests/
run_gate "ruff format --check" "-" "$PY" -m ruff format --check tools/ tests/
run_gate "mypy (tools/)"       mypy.ini "$PY" -m mypy
run_gate "py_compile (tools)"  "-" "$PY" -m py_compile tools/*.py

# ------------------------------------------------------------- the PIR gate
run_gate "catalogs agree with schema and validator" tools/validate_catalogs.py "$PY" tools/validate_catalogs.py
run_gate "good examples validate" tools/validate_pir.py \
  bash -c 'shopt -s nullglob; files=(); for f in examples/good/*.yaml; do case "$f" in *.mutation.yaml) ;; *) files+=("$f");; esac; done; [ ${#files[@]} -gt 0 ] || { echo "no good examples"; exit 1; }; "$0" tools/validate_pir.py "${files[@]}"' "$PY"
run_gate "fixtures prove their rules (both polarities)" tools/check_fixtures.py "$PY" tools/check_fixtures.py
run_gate "every rule has a fixture" tools/report_rule_coverage.py "$PY" tools/report_rule_coverage.py

# ------------------------------------------------------------- the interview and the ledger
run_gate "ledger examples validate" tools/validate_pir_ledger.py \
  bash -c 'shopt -s nullglob; files=(); for f in examples/ledgers/good/*.yaml; do case "$f" in *.mutation.yaml) ;; *) files+=("$f");; esac; done; [ ${#files[@]} -gt 0 ] || { echo "no ledger examples"; exit 1; }; "$0" tools/validate_pir_ledger.py "${files[@]}"' "$PY"
run_gate "interview example is current" tools/generate_pir_interview.py "$PY" tools/generate_pir_interview.py \
  --packet examples/draft/order-capture-draft.yaml --check examples/interviews/order-capture-draft-I01.yaml
run_gate "interview markdown is current" tools/render_pir_interview.py "$PY" tools/render_pir_interview.py \
  examples/interviews/order-capture-draft-I01.yaml --check examples/interviews/order-capture-draft-I01.md
run_gate "open ledger example is current" tools/open_pir_ledger.py "$PY" tools/open_pir_ledger.py \
  examples/interviews/order-capture-draft-I01.yaml --check examples/ledgers/good/order-capture-draft-L01-open.yaml

# ------------------------------------------------------------- the review and the surfaces
run_gate "review examples validate" tools/validate_pir_review.py \
  bash -c 'shopt -s nullglob; files=(examples/reviews/good/*.json); [ ${#files[@]} -gt 0 ] || { echo "no review examples"; exit 1; }; "$0" tools/validate_pir_review.py "${files[@]}"' "$PY"
run_gate "review scaffold example is current" tools/render_pir_review_scaffold.py "$PY" tools/render_pir_review_scaffold.py \
  examples/draft/order-capture-draft.yaml --check examples/scaffolds/order-capture-draft.scaffold.json
SKIP_ON_2=1 run_gate "artifact conventions (interviews/, clarifications/, reviews/)" tools/check_artifact_conventions.py "$PY" tools/check_artifact_conventions.py

# ------------------------------------------------------------- the rendered document
run_gate "template docx renders from the catalogs (outline golden)" tools/render_pir_docx.py "$PY" tools/render_pir_docx.py \
  --check examples/rendered/template.outline.txt
run_gate "committed template docx is current" tools/docx_outline.py \
  bash -c 'diff <("$0" tools/docx_outline.py docs/templates/PIR-Template.docx) examples/rendered/template.outline.txt' "$PY"
run_gate "template markdown golden" tools/render_pir_docx.py "$PY" tools/render_pir_docx.py --format md --check examples/rendered/template.md
run_gate "worked example renders (markdown golden)" tools/render_pir_docx.py "$PY" tools/render_pir_docx.py \
  --packet examples/good/order-capture-pool-exhaustion.yaml --format md --check examples/rendered/order-capture.md
run_gate "worked example renders (docx outline golden)" tools/render_pir_docx.py "$PY" tools/render_pir_docx.py \
  --packet examples/good/order-capture-pool-exhaustion.yaml --check examples/rendered/order-capture.outline.txt

# ------------------------------------------------------------- the VS Code extension
run_gate "vsix bundle verifies and runs the loop from a foreign workspace" tools/build_vsix.py \
  "$PY" tools/build_vsix.py --check
# Packaging needs node and npm (the locked vsce in tools/vsce); without them the gate is a SKIP
# (exit 2 and a SKIP: line), never a pass. CI has both, so there it can only pass or fail.
SKIP_ON_2=1 run_gate "vsix packages (vsce)" tools/build_vsix.py "$PY" tools/build_vsix.py --package --no-smoke

# ------------------------------------------------------------- the Antigravity extension
run_gate "antigravity bundle verifies and runs the loop from a foreign workspace" tools/build_antigravity.py \
  "$PY" tools/build_antigravity.py --check
run_gate "antigravity packages (.tar.gz and .zip)" tools/build_antigravity.py \
  "$PY" tools/build_antigravity.py --package --no-smoke

# Real PIRs under pirs/. An empty corpus is reported, not laundered as a pass. (Real interviews,
# ledgers and reviews are covered by the conventions gate above, which routes each to its validator.)
shopt -s nullglob; pir_files=(pirs/*.yaml pirs/*.yml pirs/*.json); shopt -u nullglob
if [ ${#pir_files[@]} -eq 0 ]; then
  SKIP+=("pirs (no packets under pirs/ yet)"); printf '  SKIP  pirs: no packets under pirs/ yet\n'
else
  run_gate "pirs (validator)" tools/validate_pir.py "$PY" tools/validate_pir.py "${pir_files[@]}"
fi

# ------------------------------------------------------------- the test suite
run_gate "pytest" "-" "$PY" -m pytest -q tests/

# ------------------------------------------------------------- summary
printf '\n=== summary: %d passed, %d failed, %d skipped ===\n' "${#PASS[@]}" "${#FAIL[@]}" "${#SKIP[@]}"
for s in "${SKIP[@]}"; do printf '  SKIP  %s\n' "$s"; done
for f in "${FAIL[@]}"; do printf '  FAIL  %s\n' "$f"; done
[ "${#FAIL[@]}" -eq 0 ]

