# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""`tools/run_local_gates.sh` runs what `pir-gate.yml` runs, and both are shaped so a failure fails.

A local runner that is a curated subset tells you the tree is clean when CI is about to disagree,
and it drifts silently because nothing compares the two lists. So the correspondence is asserted
mechanically, in both directions, by invocation: the tool or module run and its arguments, not a
substring of the runner's text.

The workflow's shape is asserted too: GitHub runs `shell: bash` as
`bash --noprofile --norc -eo pipefail {0}`, so a bare command that exits non-zero ends the step
before `rc=$?` is read, and the SKIP branch after it is dead code. The steps that branch on an
exit status are executed here under those flags against stub tools, as is the runner's own
`run_gate`, so a usage error, a crash or a missing tool can never read as a SKIP.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pir-gate.yml"
RUNNER = REPO_ROOT / "tools" / "run_local_gates.sh"
GITHUB_BASH = ["bash", "--noprofile", "--norc", "-eo", "pipefail"]

#: One command: an interpreter, then a module (`-m ruff`) or a repository tool, then its arguments
#: up to the end of the command (a newline, `;`, `|`, `&`, a closing `)` or the quote of a `bash -c`).
INVOCATION = re.compile(
    r"""(?:^|[\s(;'"])(?:python3?|"\$PY"|\$PY|"\$0"|bash)\s+"""
    r"""(?:-m\s+(?P<module>[\w.]+)|(?P<tool>tools/[\w./*-]+\.(?:py|sh)))"""
    r"""(?P<args>[^\n;|&)']*)""",
    re.MULTILINE,
)
REDIRECTION = re.compile(r"^\d?>&?\d*$")
ARRAY = re.compile(r"^\$\{\w+\[@\]\}$")

#: Invocations one side makes and the other deliberately does not, each with its reason.
WORKFLOW_ONLY: dict[tuple[str, tuple[str, ...]], str] = {
    ("pip", ("--require-hashes", "-r", "install", "requirements-dev.lock")): (
        "the runner uses the interpreter it finds; installing is the bootstrap's job (README)"
    ),
    ("tools/run_local_gates.sh", ("--quiet",)): "the runner is what the workflow is compared with",
}
RUNNER_ONLY: dict[tuple[str, tuple[str, ...]], str] = {}


def _arguments(raw: str) -> tuple[str, ...]:
    tokens = []
    for token in raw.split():
        token = token.strip("\"'")
        if not token or REDIRECTION.match(token):
            continue
        tokens.append("${files[@]}" if ARRAY.match(token) else token)
    return tuple(sorted(tokens))


def invocations(text: str) -> set[tuple[str, tuple[str, ...]]]:
    """Every (tool or module, sorted arguments) that `text` runs, comments and continuations aside."""
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    joined = re.sub(r"\\\n\s*", " ", "\n".join(lines))
    return {
        (match.group("module") or match.group("tool"), _arguments(match.group("args")))
        for match in INVOCATION.finditer(joined)
    }


def _steps() -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return [step for job in workflow["jobs"].values() for step in job.get("steps") or []]


def _workflow_invocations() -> set[tuple[str, tuple[str, ...]]]:
    found: set[tuple[str, tuple[str, ...]]] = set()
    for step in _steps():
        if step.get("run"):
            found |= invocations(step["run"])
    return found


def _runner_invocations() -> set[tuple[str, tuple[str, ...]]]:
    return invocations(RUNNER.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ runner and workflow agree


def test_the_extractor_reads_both_dialects() -> None:
    assert invocations('run_gate "x" tools/a.py "$PY" tools/a.py --check b.txt') == {
        ("tools/a.py", ("--check", "b.txt"))
    }
    assert invocations("python tools/a.py --check \\\n  b.txt\n") == {("tools/a.py", ("--check", "b.txt"))}
    assert invocations('bash -c \'diff <("$0" tools/o.py d.docx) g.txt\' "$PY"') == {
        ("tools/o.py", ("d.docx",))
    }
    assert invocations('out="$(python tools/c.py 2>&1)" || rc=$?') == {("tools/c.py", ())}
    assert invocations('"$PY" tools/v.py "${pir_files[@]}"') == {("tools/v.py", ("${files[@]}",))}
    assert invocations("python -m pytest -q tests/") == {("pytest", ("-q", "tests/"))}
    assert invocations("# python tools/commented.py\n") == set()


def test_every_workflow_invocation_is_run_locally_with_the_same_arguments() -> None:
    missing = sorted(_workflow_invocations() - _runner_invocations() - set(WORKFLOW_ONLY))
    assert not missing, f"tools/run_local_gates.sh does not run these as pir-gate.yml does: {missing}"


def test_every_runner_invocation_is_run_in_ci_with_the_same_arguments() -> None:
    extra = sorted(_runner_invocations() - _workflow_invocations() - set(RUNNER_ONLY))
    assert not extra, f"pir-gate.yml does not run these as tools/run_local_gates.sh does: {extra}"


def test_exemptions_are_still_real() -> None:
    stale = sorted(k for k in WORKFLOW_ONLY if k not in _workflow_invocations())
    stale += sorted(k for k in RUNNER_ONLY if k not in _runner_invocations())
    assert not stale, f"exemptions for invocations no longer made: {stale}"


def test_both_compile_every_tool_by_glob() -> None:
    """A tool added to tools/ is compiled without anyone remembering to list it."""
    expected = ("py_compile", ("tools/*.py",))
    assert expected in _workflow_invocations()
    assert expected in _runner_invocations()


# ---------------------------------------------------------------------- the workflow's shape


def test_no_step_launders_a_failure() -> None:
    for step in _steps():
        assert "continue-on-error" not in step, step.get("name")
        for line in (step.get("run") or "").splitlines():
            assert not re.search(r"\|\|\s*(?:true|:|exit\s+0)\s*$", line), (step.get("name"), line)


def test_every_exit_status_is_captured_the_e_safe_way() -> None:
    """`rc=$?` on its own line is dead under `-e`; only `cmd || rc=$?` reads the status."""
    for step in _steps():
        run = step.get("run") or ""
        for match in re.finditer(r"\$\?", run):
            assert re.search(r"\|\|\s*\w+=$", run[: match.start()]), (step.get("name"), run)


def test_dependencies_are_installed_from_the_hash_lock() -> None:
    installs = [s["run"] for s in _steps() if "pip install" in (s.get("run") or "")]
    assert installs == ["python -m pip install --require-hashes -r requirements-dev.lock"]


def _step(name_prefix: str) -> str:
    return next(s["run"] for s in _steps() if s.get("name", "").startswith(name_prefix))


def _stub(tmp_path: Path, name: str, lines: list[str], code: int) -> Path:
    stub = tmp_path / f"{name}.py"
    body = "".join(f"print({line!r})\n" for line in lines)
    stub.write_text(f"{body}raise SystemExit({code})\n", encoding="utf-8")
    return stub


@pytest.mark.parametrize(
    ("lines", "code", "expected"),
    [
        (["checked 3 artifacts"], 0, 0),
        (["reviews/x.json: REVIEW-SCHEMA"], 1, 1),
        (["SKIP: no artifacts yet (a skip is not a pass)"], 2, 0),
        (["usage: check_artifact_conventions.py", "error: unrecognized arguments: --x"], 2, 2),
    ],
    ids=["pass", "fail", "skip", "usage-error"],
)
def test_the_conventions_step_under_github_bash(
    tmp_path: Path, lines: list[str], code: int, expected: int
) -> None:
    stub = _stub(tmp_path, "conventions", lines, code)
    body = _step("Artifact conventions").replace(
        "python tools/check_artifact_conventions.py",
        f"{shlex.quote(sys.executable)} {shlex.quote(str(stub))}",
    )
    script = tmp_path / "step.sh"
    script.write_text(body, encoding="utf-8")
    result = subprocess.run([*GITHUB_BASH, str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == expected, result.stdout + result.stderr


def test_ci_packaging_cannot_skip() -> None:
    """The runner has node and npm, so exit 2 there must fail the step."""
    assert _step("VS Code extension packages").strip() == "python tools/build_vsix.py --package --no-smoke"


def test_ci_uploads_nothing() -> None:
    """Packaging on every run proves the build; the packages are published as release assets, never
    kept as workflow artifacts."""
    assert not any("upload-artifact" in str(s.get("uses", "")) for s in _steps())


# ---------------------------------------------------------------------- the runner's run_gate


def _run_gate(tmp_path: Path, invocation: str, env_prefix: str = "") -> str:
    function = re.search(
        r"^run_gate\(\) \{.*?^\}", RUNNER.read_text(encoding="utf-8"), re.DOTALL | re.MULTILINE
    )
    assert function
    script = tmp_path / "gate.sh"
    script.write_text(
        "set -uo pipefail\nQUIET=1; PASS=(); FAIL=(); SKIP=()\n"
        f"{function.group(0)}\n{env_prefix}run_gate {invocation}\n"
        'echo "PASS=${#PASS[@]} FAIL=${#FAIL[@]} SKIP=${#SKIP[@]}"\n',
        encoding="utf-8",
    )
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True, check=False, cwd=tmp_path)
    return result.stdout.strip().splitlines()[-1]


@pytest.mark.parametrize(
    ("lines", "code", "skip_on_2", "expected"),
    [
        (["ok"], 0, False, "PASS=1 FAIL=0 SKIP=0"),
        (["boom"], 1, False, "PASS=0 FAIL=1 SKIP=0"),
        (["SKIP: nothing to check"], 2, True, "PASS=0 FAIL=0 SKIP=1"),
        (["usage: x", "error: unrecognized arguments: --bogus"], 2, True, "PASS=0 FAIL=1 SKIP=0"),
        (["SKIP: nothing to check"], 2, False, "PASS=0 FAIL=1 SKIP=0"),
    ],
    ids=["pass", "fail", "skip", "usage-error-is-not-a-skip", "skip-only-where-allowed"],
)
def test_run_gate_skips_only_on_the_tools_own_verdict(
    tmp_path: Path, lines: list[str], code: int, skip_on_2: bool, expected: str
) -> None:
    stub = _stub(tmp_path, "tool", lines, code)
    invocation = f'"label" {shlex.quote(str(stub))} {shlex.quote(sys.executable)} {shlex.quote(str(stub))}'
    assert _run_gate(tmp_path, invocation, "SKIP_ON_2=1 " if skip_on_2 else "") == expected


def test_a_deleted_tool_fails_rather_than_skipping(tmp_path: Path) -> None:
    invocation = f'"label" tools/gone.py {shlex.quote(sys.executable)} tools/gone.py'
    assert _run_gate(tmp_path, invocation, "SKIP_ON_2=1 ") == "PASS=0 FAIL=1 SKIP=0"


def test_the_workflow_runs_the_test_suite() -> None:
    assert ("pytest", ("-q", "tests/")) in _workflow_invocations()
    assert ("pytest", ("-q", "tests/")) in _runner_invocations()


# ------------------------------------------------------------------------- the type check


def test_both_type_check_the_tools() -> None:
    """mypy is a gate, not a suggestion; CI and the runner both run it."""
    assert ("mypy", ()) in _workflow_invocations()
    assert ("mypy", ()) in _runner_invocations()


def test_the_type_check_is_not_loosened() -> None:
    config = (REPO_ROOT / "mypy.ini").read_text(encoding="utf-8")
    assert re.search(r"^files = tools$", config, re.MULTILINE)
    assert re.search(r"^warn_unused_ignores = True$", config, re.MULTILINE)
    assert not re.search(r"ignore_errors|ignore_missing_imports|follow_imports|disable_error_code", config)


def test_nothing_papers_over_a_type() -> None:
    """No `# type: ignore` and no `cast`: a type the checker cannot see is fixed, never silenced."""
    marker = re.compile(r"#\s*type:\s*ignore|\bcast\(|typing\.cast")
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{number}"
        for path in sorted([*(REPO_ROOT / "tools").glob("*.py"), *(REPO_ROOT / "tests").glob("*.py")])
        if path.name != Path(__file__).name
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if marker.search(line)
    ]
    assert not offenders, offenders
