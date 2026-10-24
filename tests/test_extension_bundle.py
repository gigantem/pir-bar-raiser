# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""The two extensions are built from one bundle core.

The tool list, the resource list, the staging of the skill folder, the verifier and the smoke run
exist once, in `tools/extension_bundle.py`. These tests hold both builders to it, so a tool or a
check added there reaches both bundles, and the skill folder the two ship is the same.
"""

from __future__ import annotations

import ast
from pathlib import Path

import build_antigravity
import build_vsix
import extension_bundle as bundle
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILDERS = {"vsix": build_vsix, "antigravity": build_antigravity}


@pytest.fixture(scope="module")
def stages(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("bundles")
    return {name: builder.stage(root / name / "pir-assessor") for name, builder in BUILDERS.items()}


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_both_bundles_ship_the_same_skill_folder(stages: dict[str, Path]) -> None:
    """Only SKILL.md differs, by the host's preamble and Agent Skills metadata."""
    vsix = _files(stages["vsix"] / bundle.SKILL_DIR)
    antigravity = _files(stages["antigravity"] / bundle.SKILL_DIR)
    assert vsix.keys() == antigravity.keys()
    differing = sorted(name for name in vsix if vsix[name] != antigravity[name])
    assert differing == ["SKILL.md"]


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_every_runtime_tool_and_resource_reaches_the_bundle(stages: dict[str, Path], name: str) -> None:
    skill = stages[name] / bundle.SKILL_DIR
    for tool in bundle.RUNTIME_TOOLS:
        assert (skill / "tools" / tool).read_bytes() == (REPO_ROOT / "tools" / tool).read_bytes()
    for pattern in bundle.RESOURCES:
        for source in REPO_ROOT.glob(pattern):
            if source.is_file():
                assert (skill / source.relative_to(REPO_ROOT)).is_file(), source


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_neither_builder_keeps_its_own_copy_of_the_shared_core(name: str) -> None:
    """What the core defines is defined once: no builder assigns or defines one of its names."""
    shared = {
        node.name if isinstance(node, ast.FunctionDef) else node.targets[0].id
        for node in ast.parse((REPO_ROOT / "tools" / "extension_bundle.py").read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef)
        or (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name))
    }
    module = Path(BUILDERS[name].__file__)
    defined = {
        node.name if isinstance(node, ast.FunctionDef) else node.targets[0].id
        for node in ast.parse(module.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef)
        or (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name))
    }
    # A front-end may wrap a shared function under its own name with its own default argument.
    wrappers = {"load_manifest", "with_skill_metadata", "smoke"}
    assert not (shared & defined) - wrappers, sorted((shared & defined) - wrappers)


@pytest.mark.parametrize(
    ("defect", "symptom"),
    [
        (
            lambda t: (t / bundle.SKILL_DIR / "requirements.txt").write_text(
                "PyYAML>=0\njsonschema\npython-docx\n"
            ),
            "requirements.txt does not carry the pins",
        ),
        (lambda t: (t / bundle.SKILL_DIR / "tools" / "__pycache__").mkdir(), "byte-code cache in the bundle"),
        (lambda t: (t / "LICENSE").unlink(), "LICENSE is missing from the bundle"),
        (lambda t: (t / "CHANGELOG.md").unlink(), "CHANGELOG.md is missing from the bundle"),
    ],
    ids=["loose-pins", "byte-code", "no-licence", "no-changelog"],
)
@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_the_shared_checks_hold_both_bundles(tmp_path: Path, name: str, defect, symptom: str) -> None:
    """Before the core, the Antigravity verifier passed every one of these."""
    target = BUILDERS[name].stage(tmp_path / "pir-assessor")
    assert BUILDERS[name].verify(target) == []
    defect(target)
    assert any(symptom in p for p in BUILDERS[name].verify(target)), BUILDERS[name].verify(target)


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_a_companion_or_skill_with_a_bad_name_is_caught(tmp_path: Path, name: str) -> None:
    target = BUILDERS[name].stage(tmp_path / "pir-assessor")
    skill_md = target / bundle.SKILL_DIR / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8").replace("name: pir-assessment", "name: PIR--x", 1)
    )
    problems = BUILDERS[name].verify(target)
    assert any("does not match its directory" in p for p in problems)
    assert any("is not a valid Agent Skills name" in p for p in problems)


# --------------------------------------------------------- the bundle stands on its own


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_the_bundled_directory_readmes_run_the_bundled_tools(stages: dict[str, Path], name: str) -> None:
    """The READMEs the skill sends the agent to name the bundled tools, never a repository command."""
    skill = stages[name] / bundle.SKILL_DIR
    for readme in ("pirs", "interviews", "clarifications", "reviews"):
        text = (skill / readme / "README.md").read_text(encoding="utf-8")
        assert not bundle.REPO_COMMAND.search(text), readme
        assert "run_local_gates" not in text, readme
    assert "python <pir-assessment>/tools/open_pir_ledger.py" in (
        skill / "clarifications" / "README.md"
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_a_repository_command_in_a_bundled_readme_is_caught(tmp_path: Path, name: str) -> None:
    target = BUILDERS[name].stage(tmp_path / "pir-assessor")
    readme = target / bundle.SKILL_DIR / "reviews" / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\n.venv/bin/python tools/validate_pir.py x\n")
    assert any(
        "reviews/README.md: a command still says `.venv/bin/python tools/`" in p
        for p in BUILDERS[name].verify(target)
    )


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_a_cited_repository_document_must_be_in_the_bundle(tmp_path: Path, name: str) -> None:
    """A document an instruction names must be in the bundle, or a foreign workspace is sent nowhere."""
    target = BUILDERS[name].stage(tmp_path / "pir-assessor")
    readme = target / bundle.SKILL_DIR / "interviews" / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nSee `docs/not-in-the-bundle.md`.\n")
    assert any(
        "names `docs/not-in-the-bundle.md`, which is not in the bundled skill" in p
        for p in BUILDERS[name].verify(target)
    )


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_the_smoke_run_does_not_inherit_pythonpath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """With PYTHONPATH at this repository's tools/, a module missing from the bundle would be imported
    from the repository and the smoke run would pass; the smoke run drops PYTHONPATH."""
    target = BUILDERS[name].stage(tmp_path / "pir-assessor")
    (target / bundle.SKILL_DIR / "tools" / "json_pointer.py").unlink()
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT / "tools"))
    assert any("smoke:" in p for p in BUILDERS[name].smoke(target))


def test_the_vsix_preamble_says_where_to_find_the_skill_folder(stages: dict[str, Path]) -> None:
    """The hint covers the remote side too, where the README tells WSL and SSH users to install."""
    agent = (stages["vsix"] / "agents" / "pir-assessor.agent.md").read_text(encoding="utf-8")
    for directory in (
        "~/.vscode/extensions",
        "~/.vscode-server/extensions",
        "%USERPROFILE%\\.vscode\\extensions",
    ):
        assert directory in agent, directory
    assert "ls -d ~/.vscode*/extensions/gigantem.pir-assessor-" in agent


@pytest.mark.parametrize("tool", ["check_fixtures.py", "report_rule_coverage.py", "validate_catalogs.py"])
def test_the_gate_tools_answer_help_instead_of_running(tool: str) -> None:
    """`--help` answers instead of running the check, and a stray argument is refused."""
    import subprocess
    import sys

    helped = subprocess.run(
        [sys.executable, f"tools/{tool}", "--help"], capture_output=True, text=True, check=False
    )
    assert helped.returncode == 0 and helped.stdout.startswith(f"usage: {tool}"), helped.stdout[:200]
    assert (
        subprocess.run(
            [sys.executable, f"tools/{tool}", "--bogus"], capture_output=True, check=False
        ).returncode
        == 2
    )
