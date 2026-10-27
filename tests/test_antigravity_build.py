# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""Tests for build_antigravity.py: the Antigravity extension builder, verifier, packager and installer."""

from __future__ import annotations

import json
import os
import re
import tarfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

import build_antigravity as build
import extension_bundle as bundle
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
#: The release version, read from the one place it is stated (vsix/package.json), so a
#: version bump does not have to edit these tests.
VERSION = json.loads((REPO_ROOT / "vsix" / "package.json").read_text(encoding="utf-8"))["version"]
SKILL = f"skills/{bundle.SKILL_NAME}"


@pytest.fixture(scope="module")
def staged(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("antigravity-stage") / "pir-assessor"
    build.stage(target)
    return target


def _tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*") if p.is_file())


# ------------------------------------------------------------------------- the bundle


def test_stage_layout(staged: Path) -> None:
    manifest = build.load_manifest(staged / "plugin.json")
    assert set(manifest) == {"name", "description"}, "Antigravity's plugin schema allows nothing else"
    assert manifest["name"] == "pir-assessor"
    vsix = json.loads((build.RELEASE_SRC).read_text(encoding="utf-8"))
    assert build.release() == {key: vsix[key] for key in ("version", "license", "publisher")}
    assert (staged / "README.md").is_file()
    assert (staged / "CHANGELOG.md").is_file()
    assert (staged / "LICENSE").is_file()

    # Agents
    assert (staged / "agents" / "pir-assessor.md").is_file()
    assert (staged / "agents" / "pir-interviewer.md").is_file()
    assert (staged / "agents" / "pir-reviewer.md").is_file()

    # Rules
    assert (staged / "rules" / "pir-invariants.md").is_file()

    # Comprehensive skill
    assert (staged / SKILL / "SKILL.md").is_file()
    assert (staged / SKILL / "requirements.txt").is_file()
    assert (staged / SKILL / "docs" / "method.md").is_file()
    assert (staged / SKILL / "docs" / "templates" / "PIR-Template-DRAFT.docx").is_file()

    # Companion skills
    assert (staged / "skills" / "assess-pir" / "SKILL.md").is_file()
    assert (staged / "skills" / "interview-pir" / "SKILL.md").is_file()
    assert (staged / "skills" / "review-pir" / "SKILL.md").is_file()

    for name in bundle.RUNTIME_TOOLS:
        assert (staged / SKILL / "tools" / name).is_file()

    for schema in (
        "pir-packet.schema.json",
        "pir-interview.schema.json",
        "pir-clarification-ledger.schema.json",
        "pir-review.schema.json",
    ):
        assert (staged / SKILL / "schemas" / schema).is_file()

    for catalog in (
        "pir-section-expectations.yaml",
        "pir-rule-questions.yaml",
        "blame-lexicon.yaml",
        "vague-action-lexicon.yaml",
    ):
        assert (staged / SKILL / "catalogs" / catalog).is_file()


def test_runtime_requirements_pins() -> None:
    text = bundle.runtime_requirements()
    for pin in bundle.RUNTIME_REQUIREMENTS:
        assert pin in text, pin
    assert "pytest" not in text and "ruff" not in text


def test_links_commands_and_preamble_are_rewritten(staged: Path) -> None:
    agent = (staged / "agents" / "pir-assessor.md").read_text(encoding="utf-8")
    assert "](../skills/pir-assessment/schemas/pir-packet.schema.json)" in agent
    assert "](../skills/pir-assessment/catalogs/blame-lexicon.yaml)" in agent
    assert "../../" not in agent
    assert "python <pir-assessment>/tools/validate_pir.py pirs/<stem>.yaml --gap-report <path>" in agent
    assert "python tools/" not in agent
    body = agent[bundle.frontmatter_end(agent) :]
    assert body.lstrip().startswith(
        f"> **Installed from the PIR Assessor Antigravity extension (pir-assessor {VERSION}).**"
    )
    assert agent.startswith("---\nname: pir-assessor\n")

    skill = (staged / SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "](docs/method.md)" in skill and "](catalogs/pir-section-expectations.yaml)" in skill
    assert "](interviews/README.md)" in skill and "](./references/review-checklist.md)" in skill
    assert "license: GPL-3.0-or-later\n" in skill and "compatibility: " in skill
    assert f'pir-assessor-version: "{VERSION}"' in skill
    assert skill.index("compatibility:") < skill.index("\n---\n", 4)
    assert "name: pir-assessment\n" in skill

    companion = (staged / "skills" / "review-pir" / "SKILL.md").read_text(encoding="utf-8")
    assert "](../pir-assessment/references/review-checklist.md)" in companion
    assert "](../pir-assessment/catalogs/pir-section-expectations.yaml)" in companion


def test_the_skill_is_a_valid_agent_skills_folder(staged: Path) -> None:
    for sk in (bundle.SKILL_NAME, "assess-pir", "interview-pir", "review-pir"):
        text = (staged / "skills" / sk / "SKILL.md").read_text(encoding="utf-8")
        name = re.search(r"^name:\s*(.+)$", text, re.M).group(1).strip()
        assert name == sk and bundle.SKILL_NAME_RE.match(name)
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
    """A path an instruction names in backticks is one the agent will open, so it must be bundled;
    a plausible name that does not exist (`catalogs/pir-blame-lexicon.yaml`) is caught, not just links."""
    target = build.stage(tmp_path / "s")
    assert build.verify(target) == []
    rules = target / "rules" / "pir-invariants.md"
    rules.write_text(
        rules.read_text(encoding="utf-8").replace(
            "catalogs/blame-lexicon.yaml", "catalogs/pir-blame-lexicon.yaml"
        ),
        encoding="utf-8",
    )
    problems = build.verify(target)
    assert (
        "rules/pir-invariants.md: names `catalogs/pir-blame-lexicon.yaml`, which is not in the bundled skill"
        in problems
    )


def test_the_bundled_changelog_is_the_release_notes(tmp_path: Path) -> None:
    """Both hosts show a file called CHANGELOG.md; what it holds is what users are told changed."""
    target = build.stage(tmp_path / "s")
    shipped = (target / "CHANGELOG.md").read_text(encoding="utf-8")
    assert shipped == (REPO_ROOT / "docs" / "release-notes.md").read_text(encoding="utf-8")


def test_the_verifier_reports_a_link_that_leaves_the_bundle(tmp_path: Path) -> None:
    target = build.stage(tmp_path / "s")
    path = target / "agents" / "pir-assessor.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n[out](../../README.md)\n", encoding="utf-8")
    assert any("leaves the bundle" in p for p in build.verify(target))


@pytest.mark.parametrize("key", ["displayName", "version", "$schema", "keywords"])
def test_the_verifier_rejects_a_manifest_key_the_plugin_schema_does_not_allow(
    tmp_path: Path, key: str
) -> None:
    """The published schema is `required: [name]`, `additionalProperties: false`, with `name` and
    `description` its only properties, so any other key is refused."""
    target = build.stage(tmp_path / "s")
    manifest = json.loads((target / "plugin.json").read_text(encoding="utf-8"))
    manifest[key] = "0.1.0"
    (target / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert any(f"{key} is not in Antigravity's plugin schema" in p for p in build.verify(target))


def test_the_verifier_requires_a_valid_plugin_name(tmp_path: Path) -> None:
    target = build.stage(tmp_path / "s")
    (target / "plugin.json").write_text('{"description": "x"}\n', encoding="utf-8")
    problems = build.verify(target)
    assert any("plugin.json: missing name" in p for p in problems)
    (target / "plugin.json").write_text('{"name": "pir assessor", "description": "x"}\n', encoding="utf-8")
    assert any("invalid plugin name" in p for p in build.verify(target))


def test_companion_skills_carry_only_antigravity_frontmatter_and_say_whom_to_delegate_to(
    staged: Path,
) -> None:
    """Copilot's `agent:` and `argument-hint:` are not Antigravity skill fields; the delegation the
    `agent:` key carried is said in the body instead."""
    for prompt_stem, skill_name in build.COMPANION_SKILLS:
        prompt = (REPO_ROOT / "assistant" / "prompts" / f"{prompt_stem}.prompt.md").read_text(
            encoding="utf-8"
        )
        text = (staged / "skills" / skill_name / "SKILL.md").read_text(encoding="utf-8")
        assert set(build.frontmatter(text)) == {"name", "description"}
        assert build.frontmatter(text)["description"] == build.frontmatter(prompt)["description"]
        assert f"Delegate this to the `{build.frontmatter(prompt)['agent']}` subagent." in text
    main_skill = build.frontmatter((staged / SKILL / "SKILL.md").read_text(encoding="utf-8"))
    assert set(main_skill) <= build.SKILL_KEYS and "argument-hint" not in main_skill


def test_the_verifier_rejects_a_copilot_key_in_a_staged_skill(tmp_path: Path) -> None:
    target = build.stage(tmp_path / "s")
    path = target / "skills" / "assess-pir" / "SKILL.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("---\nname:", "---\nagent: pir-assessor\nname:", 1)
    )
    assert any(
        "skills/assess-pir/SKILL.md: frontmatter key agent is not an Antigravity" in p
        for p in build.verify(target)
    )


def test_archive_names_use_forward_slashes_whatever_the_os() -> None:
    """A Windows build must not write `pir-assessor\\plugin.json`, which in an archive is a file name, not a path."""
    root = PureWindowsPath("C:/out/antigravity")
    assert bundle.archive_name(root / "pir-assessor" / "skills" / "x" / "SKILL.md", root) == (
        "pir-assessor/skills/x/SKILL.md"
    )
    assert bundle.archive_name(PurePosixPath("/o/pir-assessor/plugin.json"), PurePosixPath("/o")) == (
        "pir-assessor/plugin.json"
    )


def test_the_preamble_names_every_plugins_directory_antigravity_documents(staged: Path) -> None:
    """The preamble tells the agent how to find the plugin's real path, in every directory Antigravity documents, the CLI's included."""
    agent = (staged / "agents" / "pir-assessor.md").read_text(encoding="utf-8")
    for directory in (".agents/plugins", "~/.gemini/config/plugins", "~/.gemini/antigravity-cli/plugins"):
        assert f"{directory}/pir-assessor/skills/pir-assessment" in agent, directory


def test_the_verifier_reports_an_unrewritten_command_and_an_unbundled_tool(tmp_path: Path) -> None:
    target = build.stage(tmp_path / "s")
    path = target / "skills" / "review-pir" / "SKILL.md"
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


# ------------------------------------------------------------------------ packaging & install


def test_package_creates_valid_archives(staged: Path, tmp_path: Path) -> None:
    code, artifacts, problems = build.package(staged, tmp_path / "out")
    assert code == 0
    assert not problems
    assert len(artifacts) == 2
    tar_path, zip_path = artifacts
    assert tar_path.is_file() and tar_path.stat().st_size > 10_000
    assert zip_path.is_file() and zip_path.stat().st_size > 10_000

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert "pir-assessor/plugin.json" in names
        assert "pir-assessor/skills/pir-assessment/SKILL.md" in names
        assert "pir-assessor/agents/pir-assessor.md" in names

    with tarfile.open(tar_path, "r:gz") as tf:
        tar_names = set(tf.getnames())
        assert "pir-assessor/plugin.json" in tar_names


def test_install_to_workspace(staged: Path, tmp_path: Path) -> None:
    ws = tmp_path / "target-workspace"
    ws.mkdir()
    code, messages = build.install(staged, build.plugins_root(workspace_root=ws))
    assert code == 0, messages
    installed_dir = ws / ".agents" / "plugins" / "pir-assessor"
    assert (installed_dir / "plugin.json").is_file()
    assert (installed_dir / "skills" / "pir-assessment" / "SKILL.md").is_file()
    assert sorted(p.name for p in installed_dir.parent.iterdir()) == ["pir-assessor"]  # no work dir left


def test_the_default_destination_is_the_users_own_home_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A destination is one directory, never searched for: no install sweeps the Windows profiles
    # visible from WSL.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert build.plugins_root() == tmp_path / "home" / ".gemini" / "config" / "plugins"
    assert build.plugins_root(plugins_dir=tmp_path / "x") == tmp_path / "x"
    with pytest.raises(ValueError, match="one destination"):
        build.plugins_root(workspace_root=tmp_path, plugins_dir=tmp_path)
    assert "/mnt/c" not in Path(build.__file__).read_text(encoding="utf-8").replace(
        "/mnt/c/Users/<you>/.gemini/config/plugins from WSL", ""
    )


def test_a_global_install_writes_only_under_home(
    staged: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    assert build.main(["--stage", str(tmp_path / "stage"), "--no-smoke", "--install"]) == 0
    dest = home / ".gemini" / "config" / "plugins" / "pir-assessor"
    assert (dest / "plugin.json").is_file()
    assert f"install destination: {dest}" in capsys.readouterr().err
    assert sorted(p.name for p in tmp_path.iterdir()) == ["home", "stage"]


def test_an_install_replaces_a_previous_install_and_nothing_else(staged: Path, tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    root.mkdir()
    assert build.install(staged, root)[0] == 0
    (root / "pir-assessor" / "stale.txt").write_text("from an older version\n", encoding="utf-8")
    code, messages = build.install(staged, root)
    assert code == 0 and "replaced the previous install" in messages[0]
    assert not (root / "pir-assessor" / "stale.txt").exists()
    assert sorted(p.name for p in root.iterdir()) == ["pir-assessor"]


def test_an_install_refuses_a_directory_that_is_not_this_plugin(staged: Path, tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    foreign = root / "pir-assessor"
    foreign.mkdir(parents=True)
    (foreign / "mine.txt").write_text("someone's own work\n", encoding="utf-8")
    (foreign / "plugin.json").write_text('{"name": "something-else"}\n', encoding="utf-8")
    code, messages = build.install(staged, root)
    assert code == 1 and "REFUSING TO REPLACE" in messages[0]
    assert (foreign / "mine.txt").read_text(encoding="utf-8") == "someone's own work\n"
    assert sorted(p.name for p in root.iterdir()) == ["pir-assessor"]


def test_an_install_refuses_a_symlinked_destination(staged: Path, tmp_path: Path) -> None:
    elsewhere = build.stage(tmp_path / "elsewhere" / "pir-assessor")  # even a real previous stage
    root = tmp_path / "plugins"
    root.mkdir()
    (root / "pir-assessor").symlink_to(elsewhere, target_is_directory=True)
    code, messages = build.install(staged, root)
    assert code == 1 and "symbolic link" in messages[0]
    assert (root / "pir-assessor").is_symlink() and (elsewhere / "plugin.json").is_file()


def test_a_named_plugins_dir_must_already_exist(staged: Path, tmp_path: Path) -> None:
    code, messages = build.install(staged, tmp_path / "typo", create_root=False)
    assert code == 1 and "no such plugins directory" in messages[0]
    assert not (tmp_path / "typo").exists()


def test_a_failed_copy_leaves_the_previous_install_intact(
    staged: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "plugins"
    root.mkdir()
    assert build.install(staged, root)[0] == 0
    (root / "pir-assessor" / "marker.txt").write_text("previous\n", encoding="utf-8")

    def broken_copy(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(build.shutil, "copytree", broken_copy)
    code, messages = build.install(staged, root)
    assert code == 1 and "nothing was changed" in messages[0]
    assert (root / "pir-assessor" / "marker.txt").read_text(encoding="utf-8") == "previous\n"
    assert sorted(p.name for p in root.iterdir()) == ["pir-assessor"]


def test_a_failed_swap_restores_the_previous_install(
    staged: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "plugins"
    root.mkdir()
    assert build.install(staged, root)[0] == 0
    (root / "pir-assessor" / "marker.txt").write_text("previous\n", encoding="utf-8")
    real_replace = os.replace  # Path.replace, which install swaps with, calls it

    def replace_fails_on_the_swap(src: object, dst: object) -> None:
        if Path(str(src)).name == "pir-assessor" and Path(str(dst)) == root / "pir-assessor":
            raise OSError("file in use")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace_fails_on_the_swap)
    code, messages = build.install(staged, root)
    assert code == 1 and "nothing was changed" in messages[0]
    assert (root / "pir-assessor" / "marker.txt").read_text(encoding="utf-8") == "previous\n"


def test_install_destinations_are_exclusive_and_need_install(tmp_path: Path) -> None:
    for argv in (
        ["--install", "--workspace", str(tmp_path), "--plugins-dir", str(tmp_path)],
        ["--workspace", str(tmp_path)],
        ["--plugins-dir", str(tmp_path)],
        ["--install", "--workspace", str(tmp_path / "missing")],
        ["--check", "--plugins-dir", str(tmp_path)],
    ):
        with pytest.raises(SystemExit):
            build.parse_args(argv)


# ------------------------------------------------------------------------ agent tools


def test_each_agent_gets_the_mapping_of_its_own_canonical_tools(staged: Path) -> None:
    for source in sorted((REPO_ROOT / "assistant" / "agents").glob("*.agent.md")):
        canonical = build.frontmatter_tools(source.read_text(encoding="utf-8"))
        staged_agent = staged / "agents" / source.name.replace(".agent.md", ".md")
        assert build.frontmatter_tools(staged_agent.read_text(encoding="utf-8")) == build.antigravity_tools(
            canonical
        )


def test_the_reviewer_gets_no_write_tool(staged: Path) -> None:
    # Each agent gets the mapping of its own tools; the reviewer, which only reads, gets no write tool.
    tools = build.frontmatter_tools((staged / "agents" / "pir-reviewer.md").read_text(encoding="utf-8"))
    assert "run_command" in tools
    assert not {"write_to_file", "replace_file_content"} & set(tools)


def test_an_unmapped_canonical_tool_stops_the_build() -> None:
    with pytest.raises(ValueError, match="no Antigravity mapping: browse"):
        build.antigravity_tools(["read", "browse"])


def test_the_verifier_reports_a_widened_tool_list(tmp_path: Path) -> None:
    target = build.stage(tmp_path / "s")
    path = target / "agents" / "pir-reviewer.md"
    text = path.read_text(encoding="utf-8")
    widened = build.TOOLS_LINE.sub(
        "tools: [view_file, list_dir, grep_search, run_command, write_to_file]", text
    )
    path.write_text(widened, encoding="utf-8")
    assert any("agents/pir-reviewer.md: tools" in p and "differ" in p for p in build.verify(target))


def test_check_mode_passes_and_takes_no_stage(capsys) -> None:
    assert build.main(["--check"]) == 0
    assert "PASS" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        build.parse_args(["--check", "--package"])


def test_staging_to_a_directory_reports_it(tmp_path: Path, capsys) -> None:
    target = tmp_path / "stage"
    assert build.main(["--stage", str(target), "--no-smoke"]) == 0
    assert f"staged {target}" in capsys.readouterr().err
    assert (target / "plugin.json").is_file()


def test_no_staged_text_runs_python_with_the_working_directory_on_its_path(staged: Path) -> None:
    """What the agents read in the installed extension is what they run: the preamble's check included."""
    import test_documentation_truth as truth

    found = {
        str(p.relative_to(staged)): runs
        for p in sorted(staged.rglob("*.md"))
        if (runs := truth.unsafe_python_runs(p.read_text(encoding="utf-8")))
    }
    assert found == {}
