# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""The VS Code extension is assembled from the canonical surfaces and proven sound before packaging.

What is asserted: the stage carries exactly what package.json contributes; every relative link in
it resolves inside it; every `python <pir-assessment>/tools/...` command names a bundled tool and no
`python tools/` survives; the tools' imports close over the bundle; the skill is a valid Agent
Skills folder; the requirements are the dev pins; staging is deterministic; the verifier goes red
on each defect it exists for; and the bundle runs the whole loop from a foreign workspace
(the smoke, which is also what `--check` runs in the gate).
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import build_vsix as build
import extension_bundle as bundle
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
#: The release version, read from the one place it is stated (vsix/package.json), so a
#: version bump does not have to edit these tests.
VERSION = json.loads((REPO_ROOT / "vsix" / "package.json").read_text(encoding="utf-8"))["version"]
SKILL = Path(bundle.SKILL_DIR)


@pytest.fixture(scope="module")
def staged(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("vsix") / "pir-assessor"
    build.stage(target)
    return target


def _tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# --------------------------------------------------------------------------- the stage


def test_the_stage_verifies(staged: Path) -> None:
    assert build.verify(staged) == []


def test_the_manifest_and_the_stage_agree(staged: Path) -> None:
    manifest = json.loads((staged / "package.json").read_text(encoding="utf-8"))
    contributed = build._contributed_paths(manifest)
    assert sorted(contributed) == sorted(
        [f"agents/{p.name}" for p in (REPO_ROOT / "assistant" / "agents").glob("*.agent.md")]
        + [f"prompts/{p.name}" for p in (REPO_ROOT / "assistant" / "prompts").glob("*.prompt.md")]
        + [f"{bundle.SKILL_DIR}/SKILL.md"]
    )
    assert manifest["publisher"] == "gigantem"
    assert manifest["engines"]["vscode"] == "^1.109.0", (
        "chatSkills arrived in 1.109; the floor is measured, not guessed"
    )
    assert "main" not in manifest and "activationEvents" not in manifest, "declarative: no code runs"


def test_every_runtime_tool_and_resource_is_in_the_skill(staged: Path) -> None:
    for name in bundle.RUNTIME_TOOLS:
        assert (staged / SKILL / "tools" / name).is_file(), name
        assert (staged / SKILL / "tools" / name).read_bytes() == (REPO_ROOT / "tools" / name).read_bytes()
    for relative in (
        "schemas/pir-packet.schema.json",
        "catalogs/pir-section-expectations.yaml",
        "catalogs/blame-lexicon.yaml",
        "docs/method.md",
        "docs/templates/PIR-Template.docx",
        "docs/templates/PIR-Template-DRAFT.docx",
        "examples/good/order-capture-pool-exhaustion.yaml",
        "reviews/README.md",
        "references/review-checklist.md",
        "assets/finding.example.json",
        "requirements.txt",
    ):
        assert (staged / SKILL / relative).is_file(), relative
    assert not (staged / SKILL / "tools" / "run_local_gates.sh").exists(), (
        "repository-only tooling stays home"
    )
    assert not (staged / SKILL / "examples" / "bad").exists(), (
        "mutation fixtures are the gate's, not the user's"
    )


def test_the_requirements_are_the_dev_pins(staged: Path) -> None:
    text = (staged / SKILL / "requirements.txt").read_text(encoding="utf-8")
    dev = (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    for name in bundle.RUNTIME_REQUIREMENTS:
        pin = next(line for line in dev.splitlines() if line.lower().startswith(name.lower()))
        assert pin in text, pin
    assert "pytest" not in text and "ruff" not in text


def test_links_commands_and_preamble_are_rewritten(staged: Path) -> None:
    agent = (staged / "agents" / "pir-assessor.agent.md").read_text(encoding="utf-8")
    assert "](../skills/pir-assessment/schemas/pir-packet.schema.json)" in agent
    assert "](../skills/pir-assessment/catalogs/blame-lexicon.yaml)" in agent
    assert "](../../" not in agent
    assert "python <pir-assessment>/tools/validate_pir.py pirs/<stem>.yaml --gap-report <path>" in agent
    assert "python tools/" not in agent
    body = agent[bundle.frontmatter_end(agent) :]
    assert body.lstrip().startswith(
        f"> **Installed from the PIR Assessor extension (gigantem.pir-assessor {VERSION}).**"
    )
    assert agent.startswith("---\nname: pir-assessor\n"), "the frontmatter is untouched"

    reviewer = (staged / "agents" / "pir-reviewer.agent.md").read_text(encoding="utf-8")
    assert "](../skills/pir-assessment/references/review-checklist.md)" in reviewer, (
        "a one-level link is left alone"
    )

    prompt = (staged / "prompts" / "assess-pir.prompt.md").read_text(encoding="utf-8")
    assert "](../skills/pir-assessment/docs/templates/PIR-Template-DRAFT.docx)" in prompt
    assert 'agent: "pir-assessor"' in prompt

    skill = (staged / SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "](docs/method.md)" in skill and "](catalogs/pir-section-expectations.yaml)" in skill
    assert "](interviews/README.md)" in skill and "](./references/review-checklist.md)" in skill
    assert "license: GPL-3.0-or-later\n" in skill and "compatibility: " in skill
    assert f'pir-assessor-version: "{VERSION}"' in skill
    assert skill.index("compatibility:") < skill.index("\n---\n", 4), (
        "the added fields sit inside the frontmatter"
    )
    assert "name: pir-assessment\n" in skill


def test_rewrite_links_rewrites_exactly_the_requested_depth() -> None:
    text = "[a](../../x/y.md) [b](../z.md) [c](../../../q.md) [d](https://e.x/../../y) [e](./f.md)"
    assert bundle.rewrite_links(text, 2, "../skills/s/") == (
        "[a](../skills/s/x/y.md) [b](../z.md) [c](../../../q.md) [d](https://e.x/../../y) [e](./f.md)"
    )
    assert bundle.rewrite_links("[a](../../../x.md)", 3, "") == "[a](x.md)"


def test_the_preamble_needs_a_frontmatter() -> None:
    with pytest.raises(ValueError, match="frontmatter"):
        bundle.with_preamble("no frontmatter here\n", "> p")
    with pytest.raises(ValueError, match="not closed"):
        bundle.with_preamble("---\nname: x\n", "> p")
    assert bundle.with_preamble("---\nname: x\n---\nBody\n", "> p") == "---\nname: x\n---\n\n> p\n\nBody\n"


def test_the_skill_is_a_valid_agent_skills_folder(staged: Path) -> None:
    text = (staged / SKILL / "SKILL.md").read_text(encoding="utf-8")
    name = re.search(r"^name:\s*(.+)$", text, re.M).group(1).strip()
    assert name == (staged / SKILL).name and bundle.SKILL_NAME_RE.match(name)
    description = re.search(r"^description:\s*(.+)$", text, re.M).group(1)
    assert 1 <= len(description) <= 1024


def test_staging_is_deterministic(tmp_path: Path, staged: Path) -> None:
    again = build.stage(tmp_path / "again")
    assert _tree(again) == _tree(staged)


def test_restaging_replaces_only_a_previous_stage(tmp_path: Path) -> None:
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("mine\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="REFUSING TO REPLACE"):
        build.stage(foreign)
    assert (foreign / "keep.txt").is_file()
    first = build.stage(tmp_path / "stage")
    (first / "stale.txt").write_text("x\n", encoding="utf-8")
    build.stage(first)
    assert not (first / "stale.txt").exists()


# ------------------------------------------------------------------------ the verifier


def test_the_verifier_reports_a_broken_link(tmp_path: Path) -> None:
    target = build.stage(tmp_path / "s")
    (target / SKILL / "catalogs" / "blame-lexicon.yaml").unlink()
    problems = build.verify(target)
    assert any("blame-lexicon.yaml does not resolve" in p for p in problems)


def test_the_verifier_reports_a_backticked_path_the_bundle_lacks(tmp_path: Path) -> None:
    target = build.stage(tmp_path / "s")
    skill_md = target / "skills" / "pir-assessment" / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8") + "\nSee `catalogs/no-such-catalog.yaml`.\n", encoding="utf-8"
    )
    problems = build.verify(target)
    assert any("names `catalogs/no-such-catalog.yaml`" in p for p in problems)


def test_the_verifier_reports_a_link_that_leaves_the_bundle(tmp_path: Path) -> None:
    target = build.stage(tmp_path / "s")
    path = target / "agents" / "pir-assessor.agent.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n[out](../../README.md)\n", encoding="utf-8")
    assert any("leaves the bundle" in p for p in build.verify(target))


def test_the_verifier_reports_a_manifest_that_disagrees_with_the_stage(tmp_path: Path) -> None:
    target = build.stage(tmp_path / "s")
    manifest = json.loads((target / "package.json").read_text(encoding="utf-8"))
    manifest["contributes"]["chatPromptFiles"].pop()
    manifest["contributes"]["chatAgents"].append({"path": "./agents/ghost.agent.md"})
    (target / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    problems = build.verify(target)
    assert any(
        "review-pir.prompt.md is staged but package.json does not contribute it" in p for p in problems
    )
    assert any("ghost.agent.md, which is not in the bundle" in p for p in problems)


def test_the_verifier_reports_an_unrewritten_command_and_an_unbundled_tool(tmp_path: Path) -> None:
    target = build.stage(tmp_path / "s")
    path = target / "prompts" / "review-pir.prompt.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nAlso `python tools/validate_pir.py x` and `python <pir-assessment>/tools/nope.py`.\n",
        encoding="utf-8",
    )
    problems = build.verify(target)
    assert any("still says `python tools/`" in p for p in problems)
    assert any("names nope.py, which is not bundled" in p for p in problems)


def test_the_verifier_reports_a_broken_import_closure(tmp_path: Path) -> None:
    target = build.stage(tmp_path / "s")
    (target / SKILL / "tools" / "json_pointer.py").unlink()
    problems = build.verify(target)
    assert any("validate_pir_ledger.py imports json_pointer, which is not bundled" in p for p in problems)


def test_the_verifier_reports_stale_requirements(tmp_path: Path) -> None:
    target = build.stage(tmp_path / "s")
    (target / SKILL / "requirements.txt").write_text("PyYAML\n", encoding="utf-8")
    assert any("requirements.txt does not carry the pins" in p for p in build.verify(target))


# ---------------------------------------------------------------------------- the smoke


def test_the_bundle_runs_the_loop_from_a_foreign_workspace(staged: Path) -> None:
    assert build.smoke(staged) == []


@pytest.mark.parametrize(
    ("tool", "symptom"),
    [
        ("render_pir_review_scaffold.py", "did not discover the workspace's ledger"),
        ("validate_pir_review.py", "validate the review from the workspace exited 1"),
        ("validate_pir_ledger.py", "validate the ledger from the workspace exited 1"),
    ],
)
def test_the_smoke_notices_a_tool_that_stops_citing_the_workspace(
    tmp_path: Path, tool: str, symptom: str
) -> None:
    """A tool whose command line went back to resolving against its own home fails the smoke by name."""
    target = build.stage(tmp_path / "s")
    path = target / SKILL / "tools" / tool
    text = path.read_text(encoding="utf-8")
    assert text.count("default=str(Path.cwd())") == 1
    path.write_text(text.replace("default=str(Path.cwd())", "default=str(REPO_ROOT)"), encoding="utf-8")
    assert any(symptom in p for p in build.smoke(target))


# ------------------------------------------------------------------------------- the CLI


def test_check_mode_passes_and_takes_no_stage(capsys) -> None:
    assert build.main(["--check"]) == 0
    assert "PASS" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        build.parse_args(["--check", "--package"])


def test_staging_to_a_directory_reports_it(tmp_path: Path, capsys) -> None:
    target = tmp_path / "stage"
    assert build.main(["--stage", str(target), "--no-smoke"]) == 0
    assert f"staged {target}" in capsys.readouterr().err
    assert (target / "package.json").is_file()


# ------------------------------------------------------ the package is the stage, nothing else


def _vsix_of(stage: Path, artifact: Path, *, drop: str = "", add: str = "", alter: str = "") -> Path:
    """A .vsix laid out the way vsce 4.0.0 lays out this stage, with one defect when asked."""
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("extension.vsixmanifest", "<x/>")
        archive.writestr("[Content_Types].xml", "<x/>")
        for path in sorted(p for p in stage.rglob("*") if p.is_file()):
            relative = path.relative_to(stage).as_posix()
            if relative in build.VSCE_LEFT_OUT or relative == drop:
                continue
            data = path.read_bytes() + (b"\n# altered\n" if relative == alter else b"")
            archive.writestr(f"extension/{build.VSCE_RENAMES.get(relative, relative)}", data)
        if add:
            archive.writestr(add, "stray")
    return artifact


def test_a_package_that_is_the_stage_passes(staged: Path, tmp_path: Path) -> None:
    assert build.vsix_problems(_vsix_of(staged, tmp_path / "x.vsix"), staged) == []


@pytest.mark.parametrize(
    ("defect", "symptom"),
    [
        (
            {"drop": f"{SKILL}/catalogs/blame-lexicon.yaml"},
            "lacks extension/skills/pir-assessment/catalogs/blame-lexicon.yaml",
        ),
        ({"add": "extension/skills/pir-assessment/tools/__pycache__/x.pyc"}, "which is not staged"),
        ({"alter": f"{SKILL}/tools/validate_pir.py"}, "validate_pir.py differs from the staged file"),
        ({"drop": "README.md"}, "lacks extension/readme.md"),
    ],
    ids=["dropped-file", "stray-file", "altered-file", "dropped-readme"],
)
def test_a_package_that_differs_from_the_stage_is_caught(
    staged: Path, tmp_path: Path, defect: dict[str, str], symptom: str
) -> None:
    problems = build.vsix_problems(_vsix_of(staged, tmp_path / "x.vsix", **defect), staged)
    assert any(symptom in p for p in problems), problems


def test_the_package_steps_do_not_rerun_the_smoke() -> None:
    """The check step has just run the loop over an identical stage, so --package does not run it again."""
    runner = (REPO_ROOT / "tools" / "run_local_gates.sh").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github" / "workflows" / "pir-gate.yml").read_text(encoding="utf-8")
    for text in (runner, workflow):
        assert (
            "build_vsix.py --package --no-smoke" in text
            and "build_antigravity.py --package --no-smoke" in text
        )
        assert "build_vsix.py --check" in text and "build_antigravity.py --check" in text


def test_no_staged_text_runs_python_with_the_working_directory_on_its_path(staged: Path) -> None:
    """What the agents read in the installed extension is what they run: the preamble's check included."""
    import test_documentation_truth as truth

    found = {
        str(p.relative_to(staged)): runs
        for p in sorted(staged.rglob("*.md"))
        if (runs := truth.unsafe_python_runs(p.read_text(encoding="utf-8")))
    }
    assert found == {}
