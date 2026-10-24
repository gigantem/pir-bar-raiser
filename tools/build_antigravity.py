#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""build_antigravity.py: the Antigravity extension bundle, assembled from canonical surfaces and verified.

The extension packages the repository's personas, skill and runtime tools for Google Antigravity:
  * Manifest: plugin.json;
  * Agents: pir-assessor.md, pir-interviewer.md, pir-reviewer.md, each with the Antigravity mapping of
    its own canonical tools;
  * Rules: pir-invariants.md, always on;
  * Skills: pir-assessment, the skill folder `extension_bundle.py` stages for both extensions (runtime
    tools, schemas, catalogs, templates, worked examples and requirements.txt), plus the assess-pir,
    interview-pir and review-pir companion skills, one per prompt, meant as slash commands.

Nothing in the bundle is maintained twice. The agents, prompts and skill are read from assistant/;
their relative links are rewritten for the bundle layout, their `python tools/...` commands are
pointed at the bundled tools, and an installed preamble (antigravity/installed-preamble.md) is
inserted after each frontmatter. The result is verified before anything is packaged or installed:
what `extension_bundle.verify_bundle` checks of every bundle (links, commands, citations, the
import closure, the pins, no byte-code), the manifest's metadata and each agent's tools, and the
bundle runs the whole loop (validate, interview, ledger, scaffold, review, render) from a workspace
that holds nothing but a packet.

    python tools/build_antigravity.py            # stage under out/antigravity/<name>/ and verify it
    python tools/build_antigravity.py --check    # stage into a temporary directory, verify, discard
    python tools/build_antigravity.py --package  # stage, verify, write .tar.gz and .zip packages
    python tools/build_antigravity.py --install  # stage, verify, install into ~/.gemini/config/plugins/
    python tools/build_antigravity.py --install --workspace <dir>     # ... into <dir>/.agents/plugins/
    python tools/build_antigravity.py --install --plugins-dir <dir>   # ... into an existing plugins dir

An install has exactly one destination and replaces only a previous install of this plugin.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import extension_bundle as bundle
import yaml
from extension_bundle import REPO_ROOT, SKILL_DIR, SKILL_NAME, frontmatter_end

SOURCES = REPO_ROOT / "antigravity"
MANIFEST_SRC = SOURCES / "plugin.json"
README_SRC = SOURCES / "README.md"
PREAMBLE_SRC = SOURCES / "installed-preamble.md"
RULES_SRC = SOURCES / "rules"
#: The version, licence and publisher both extensions state are the VS Code manifest's: Antigravity's
#: plugin.json has no field for them.
RELEASE_SRC = REPO_ROOT / "vsix" / "package.json"
#: Antigravity's published plugin.json schema: `name` required, `description` optional, nothing else.
MANIFEST_KEYS = ("name", "description")
#: The skill frontmatter the bundle may carry: Antigravity documents `name` and `description`; the
#: Agent Skills specification adds `license`, `compatibility` and `metadata`. Copilot's `agent` and
#: `argument-hint` are not among them.
SKILL_KEYS = frozenset({"name", "description", "license", "compatibility", "metadata"})
MANIFEST_NAME = re.compile(r"^[a-zA-Z0-9-_]+$")
DEFAULT_STAGE_PARENT = REPO_ROOT / "out" / "antigravity"
DEFAULT_PACKAGE_DIR = REPO_ROOT / "out"

COMPANION_SKILLS = (
    ("assess-pir", "assess-pir"),
    ("interview-pir", "interview-pir"),
    ("review-pir", "review-pir"),
)

#: Each canonical tool (the `tools:` line of an assistant/agents file) in Antigravity's vocabulary. An agent
#: gets exactly the mapping of its own canonical list, so a restriction there holds here too: pir-reviewer
#: has no `edit`, so it gets no write tool. Antigravity's subagent documentation names view_file,
#: replace_file_content, grep_search and run_command; write_to_file and list_dir are not yet confirmed by
#: a live session, and an unknown name can hang a subagent.
ANTIGRAVITY_TOOLS: dict[str, tuple[str, ...]] = {
    "read": ("view_file", "list_dir"),
    "search": ("grep_search",),
    "execute": ("run_command",),
    "edit": ("write_to_file", "replace_file_content"),
}
TOOLS_LINE = re.compile(r"^tools:[ \t]*\[(?P<tools>[^\]\n]*)\]", re.M)


# ------------------------------------------------------------------------------ transforms


def load_manifest(path: Path = MANIFEST_SRC) -> dict[str, Any]:
    return bundle.load_manifest(path)


def frontmatter_tools(text: str) -> list[str]:
    """The names on the `tools: [...]` line of a surface's frontmatter; raises if there is none."""
    match = TOOLS_LINE.search(text[: frontmatter_end(text)])
    if match is None:
        raise ValueError("frontmatter has no `tools: [...]` line")
    return [name.strip().strip("'\"") for name in match.group("tools").split(",") if name.strip()]


def antigravity_tools(canonical: list[str]) -> list[str]:
    """The Antigravity tool list for a canonical one, in order, without repeats; raises on an unmapped name."""
    unknown = [name for name in canonical if name not in ANTIGRAVITY_TOOLS]
    if unknown:
        raise ValueError(f"canonical tool(s) with no Antigravity mapping: {', '.join(unknown)}")
    mapped: list[str] = []
    for name in canonical:
        mapped.extend(tool for tool in ANTIGRAVITY_TOOLS[name] if tool not in mapped)
    return mapped


def with_antigravity_tools(text: str) -> str:
    """`text` with its frontmatter's canonical `tools:` line replaced by the Antigravity mapping of it."""
    end = frontmatter_end(text)
    tools = antigravity_tools(frontmatter_tools(text))
    head = TOOLS_LINE.sub(f"tools: [{', '.join(tools)}]", text[:end], count=1)
    return head + text[end:]


def release(path: Path = RELEASE_SRC) -> dict[str, str]:
    """The version, licence and publisher the extension states, from the VS Code manifest."""
    manifest = bundle.load_manifest(path)
    return {key: str(manifest[key]) for key in ("version", "license", "publisher")}


def frontmatter(text: str) -> dict[str, Any]:
    """A surface's frontmatter as a mapping; raises when it is not one."""
    end = frontmatter_end(text)
    parsed = yaml.safe_load(text[4 : end - len(bundle.FRONTMATTER_END)])
    if not isinstance(parsed, dict):
        raise ValueError("frontmatter is not a mapping")
    return parsed


def with_frontmatter(text: str, fields: dict[str, str]) -> str:
    """`text` with its frontmatter replaced by `fields`. A plain Agent Skills name is written bare, as
    every other surface writes it; any other value as a double-quoted YAML string."""
    body = text[frontmatter_end(text) :]

    def scalar(value: str) -> str:
        return value if bundle.SKILL_NAME_RE.match(value) else json.dumps(value, ensure_ascii=False)

    head = "".join(f"{key}: {scalar(value)}\n" for key, value in fields.items())
    return f"---\n{head}---\n{body}"


def companion_skill(prompt: str) -> str:
    """A prompt as an Antigravity skill: `name` and `description` only, and the delegation that the
    prompt's Copilot `agent:` key carried, said in the body, where Antigravity will read it."""
    fields = frontmatter(prompt)
    body = prompt[frontmatter_end(prompt) :]
    head = with_frontmatter(
        prompt[: frontmatter_end(prompt)], {k: fields[k] for k in ("name", "description")}
    )
    return head + f"\nDelegate this to the `{fields['agent']}` subagent.\n" + body


def with_skill_metadata(text: str, info: dict[str, str]) -> str:
    """The skill's own `name` and `description`, then the Agent Skills fields the bundle can state."""
    fields = frontmatter(text)
    text = with_frontmatter(text, {k: fields[k] for k in ("name", "description")})
    return bundle.with_skill_metadata(
        text,
        license_id=info["license"],
        version=info["version"],
        publisher=info["publisher"],
        host="Google Antigravity",
    )


def preamble_for(manifest: dict[str, Any], info: dict[str, str]) -> str:
    return PREAMBLE_SRC.read_text(encoding="utf-8").format(name=manifest["name"], version=info["version"])


# --------------------------------------------------------------------------------- staging


def _is_a_previous_stage(path: Path) -> bool:
    expected = load_manifest().get("name")
    return isinstance(expected, str) and bundle.is_a_previous_stage(path, "plugin.json", expected)


def stage(target: Path) -> Path:
    """Assemble the extension under `target` (replaced if it is a previous stage) and return it."""
    manifest, info = load_manifest(), release()
    bundle.clear_previous_stage(target, "plugin.json", manifest["name"])
    preamble = preamble_for(manifest, info)

    (target / "agents").mkdir(parents=True)
    for source in sorted((bundle.SURFACES / "agents").glob("*.agent.md")):
        try:
            adapted = with_antigravity_tools(source.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise SystemExit(f"{source.relative_to(REPO_ROOT)}: {exc}") from exc
        dest_name = source.name.replace(".agent.md", ".md")
        (target / "agents" / dest_name).write_text(bundle.staged_surface(adapted, preamble), encoding="utf-8")

    (target / "rules").mkdir(parents=True)
    for rule in sorted(RULES_SRC.glob("*.md")):
        shutil.copyfile(rule, target / "rules" / rule.name)

    bundle.stage_skill(target / SKILL_DIR, preamble, lambda text: with_skill_metadata(text, info))

    for prompt_stem, cmd_name in COMPANION_SKILLS:
        cmd_dir = target / "skills" / cmd_name
        cmd_dir.mkdir(parents=True, exist_ok=True)
        raw_prompt = (bundle.SURFACES / "prompts" / f"{prompt_stem}.prompt.md").read_text(encoding="utf-8")
        normalized = companion_skill(raw_prompt.replace("../skills/pir-assessment/", f"../{SKILL_NAME}/"))
        text = bundle.staged_surface(normalized, preamble, f"../{SKILL_NAME}/")
        (cmd_dir / "SKILL.md").write_text(text, encoding="utf-8")

    shutil.copyfile(MANIFEST_SRC, target / "plugin.json")
    bundle.stage_documents(target, README_SRC)
    return target


# ---------------------------------------------------------------------------- verification


def _tool_parity(agent_name: str, staged_text: str) -> list[str]:
    """A staged agent's tools must be exactly the mapping of its canonical source's tools."""
    source = bundle.SURFACES / "agents" / agent_name.replace(".md", ".agent.md")
    try:
        expected = antigravity_tools(frontmatter_tools(source.read_text(encoding="utf-8")))
        actual = frontmatter_tools(staged_text)
    except (OSError, ValueError) as exc:
        return [f"agents/{agent_name}: tools cannot be compared with {source.name}: {exc}"]
    if actual != expected:
        return [f"agents/{agent_name}: tools {actual} differ from the mapping of {source.name}'s, {expected}"]
    return []


def verify(target: Path) -> list[str]:
    """Every defect the bundle could carry, as one message each; empty when it is sound."""
    problems: list[str] = []
    try:
        manifest = load_manifest(target / "plugin.json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"plugin.json: {exc}"]
    for key in sorted(set(manifest) - set(MANIFEST_KEYS)):
        problems.append(
            f"plugin.json: {key} is not in Antigravity's plugin schema ({', '.join(MANIFEST_KEYS)})"
        )
    for key in MANIFEST_KEYS:
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            problems.append(f"plugin.json: missing {key}")
    name = manifest.get("name", "")
    if not MANIFEST_NAME.match(str(name)):
        problems.append(f"plugin.json: invalid plugin name {name!r}")

    for agent_name in ("pir-assessor.md", "pir-interviewer.md", "pir-reviewer.md"):
        agent_path = target / "agents" / agent_name
        if not agent_path.is_file():
            problems.append(f"missing agent {agent_name}")
        else:
            text = agent_path.read_text(encoding="utf-8")
            if not text.startswith("---\n"):
                problems.append(f"{agent_name}: missing frontmatter")
            else:
                problems.extend(_tool_parity(agent_name, text))

    rules_path = target / "rules" / "pir-invariants.md"
    if not rules_path.is_file():
        problems.append("missing rules/pir-invariants.md")
    elif "trigger:" not in rules_path.read_text(encoding="utf-8"):
        problems.append("rules/pir-invariants.md: missing trigger in frontmatter")

    for skill_name in (SKILL_NAME, *(c[1] for c in COMPANION_SKILLS)):
        if not (target / "skills" / skill_name / "SKILL.md").is_file():
            problems.append(f"missing skills/{skill_name}/SKILL.md")
    for skill_md in sorted(target.glob("skills/*/SKILL.md")):
        relative = skill_md.relative_to(target).as_posix()
        try:
            keys = set(frontmatter(skill_md.read_text(encoding="utf-8")))
        except (ValueError, yaml.YAMLError) as exc:
            problems.append(f"{relative}: frontmatter does not parse: {exc}")
            continue
        for key in sorted(keys - SKILL_KEYS):
            problems.append(f"{relative}: frontmatter key {key} is not an Antigravity or Agent Skills field")

    problems.extend(bundle.verify_bundle(target))
    return problems


# ---------------------------------------------------------------------------------- smoke


def smoke(target: Path, python: str = sys.executable) -> list[str]:
    """Run the bundled tools through the whole loop from a workspace that holds only a packet."""
    return bundle.smoke(target, python, "pir-antigravity-smoke-")


# ------------------------------------------------------------------------------- packaging


def package(target: Path, out_dir: Path) -> tuple[int, list[Path], list[str]]:
    """Package the staged Antigravity extension into self-contained .tar.gz and .zip archives."""
    manifest = load_manifest(target / "plugin.json")
    out_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"{manifest['name']}-{release()['version']}-antigravity"
    tar_artifact = out_dir / f"{base_name}.tar.gz"
    zip_artifact = out_dir / f"{base_name}.zip"

    for artifact in (tar_artifact, zip_artifact):
        if artifact.exists():
            artifact.unlink()

    bundle.write_tar_gz(target, tar_artifact)
    bundle.write_zip(target, zip_artifact)

    problems: list[str] = []
    with zipfile.ZipFile(zip_artifact) as archive:
        names = set(archive.namelist())
    for name in sorted(names):
        if "__pycache__" in name or name.endswith((".pyc", ".pyo")):
            problems.append(f"{zip_artifact.name} contains {name}")
    for required in (
        f"{manifest['name']}/plugin.json",
        f"{manifest['name']}/README.md",
        f"{manifest['name']}/rules/pir-invariants.md",
        f"{manifest['name']}/agents/pir-assessor.md",
        f"{manifest['name']}/{SKILL_DIR}/SKILL.md",
        f"{manifest['name']}/{SKILL_DIR}/tools/validate_pir.py",
        f"{manifest['name']}/skills/assess-pir/SKILL.md",
    ):
        if required not in names:
            problems.append(f"{zip_artifact.name} does not contain {required}")

    for artifact in (tar_artifact, zip_artifact):
        problems.extend(bundle.archive_metadata_problems(artifact))
    return (1 if problems else 0), [tar_artifact, zip_artifact], problems


# ---------------------------------------------------------------------------- installation


def plugins_root(workspace_root: Path | None = None, plugins_dir: Path | None = None) -> Path:
    """The one plugins directory an install writes into.

    The default is the global location of the user running the command; a workspace install writes into
    that workspace's `.agents/plugins/`; `plugins_dir` names any other plugins directory explicitly (for
    example a Windows profile seen from WSL). There is no search: a destination is never inferred.
    """
    if workspace_root is not None and plugins_dir is not None:
        raise ValueError("an install has one destination: give a workspace or a plugins directory, not both")
    if plugins_dir is not None:
        return plugins_dir
    if workspace_root is not None:
        return workspace_root / ".agents" / "plugins"
    return Path.home() / ".gemini" / "config" / "plugins"


def install(target: Path, root: Path, *, create_root: bool = True) -> tuple[int, list[str]]:
    """Install the staged plugin at `target` as `root/<name>`; return an exit code and messages.

    Defensive by construction: an existing destination is replaced only when it is a previous install of
    this plugin (its plugin.json names it), never when it is a symlink or anything else; the new copy is
    built beside the old one and swapped in by rename, so a failed copy leaves the previous install intact.
    """
    name = load_manifest(target / "plugin.json")["name"]
    dest = root / name
    if dest.is_symlink():
        return 1, [f"REFUSING TO REPLACE {dest}: it is a symbolic link; remove it yourself if it is yours"]
    if dest.exists() and not (dest.is_dir() and _is_a_previous_stage(dest)):
        return 1, [f"REFUSING TO REPLACE {dest}: it is not a previous install of {name}; nothing was changed"]
    if not root.is_dir():
        if not create_root:
            return 1, [f"REFUSING TO INSTALL into {root}: no such plugins directory; nothing was changed"]
        root.mkdir(parents=True)

    replaced = dest.exists()
    work = Path(tempfile.mkdtemp(prefix=f".{name}-installing-", dir=root))
    fresh, previous = work / name, work / "previous"
    keep_work = False
    try:
        shutil.copytree(target, fresh)
        if replaced:
            dest.replace(previous)
        try:
            fresh.replace(dest)
        except OSError:
            if replaced:
                try:
                    previous.replace(dest)
                except OSError:
                    keep_work = True
                    raise
            raise
    except OSError as exc:
        if keep_work:
            return 1, [f"INSTALL FAILED at {dest}: {exc}; the previous install is preserved at {previous}"]
        return 1, [f"INSTALL FAILED at {dest}: {exc}; nothing was changed"]
    finally:
        if not keep_work:
            shutil.rmtree(work, ignore_errors=True)
    verb = "replaced the previous install at" if replaced else "installed Antigravity plugin to:"
    return 0, [f"{verb} {dest}"]


# ------------------------------------------------------------------------------------- CLI


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assemble, verify, package and install the Antigravity extension."
    )
    parser.add_argument(
        "--stage",
        help="Stage directory (default: out/antigravity/<name>). Replaced only if it is a previous stage.",
    )
    parser.add_argument(
        "--check", action="store_true", help="Stage into a temporary directory, verify and discard."
    )
    parser.add_argument("--package", action="store_true", help="Also package .tar.gz and .zip into out/.")
    parser.add_argument(
        "--install",
        action="store_true",
        help="Install into one plugins directory: ~/.gemini/config/plugins/ unless --workspace or --plugins-dir "
        "names another. Replaces only a previous install of this plugin.",
    )
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument(
        "--workspace", help="Install into <workspace>/.agents/plugins/ instead (the workspace must exist)."
    )
    destination.add_argument(
        "--plugins-dir",
        help="Install into this existing plugins directory instead, e.g. a Windows profile's "
        "/mnt/c/Users/<you>/.gemini/config/plugins from WSL.",
    )
    parser.add_argument("--out-dir", help="Where --package writes archives (default: out/).")
    parser.add_argument(
        "--no-smoke", action="store_true", help="Skip the end-to-end run of the bundled tools."
    )
    args = parser.parse_args(argv)
    if args.check and (
        args.stage or args.package or args.install or args.workspace or args.plugins_dir or args.out_dir
    ):
        parser.error(
            "--check takes no --stage, --package, --install, --workspace, --plugins-dir or --out-dir"
        )
    if (args.workspace or args.plugins_dir) and not args.install:
        parser.error("--workspace and --plugins-dir name an install destination; they need --install")
    if args.workspace and not Path(args.workspace).is_dir():
        parser.error(f"--workspace {args.workspace}: no such directory")
    return args


def build_and_verify(target: Path, run_smoke: bool) -> list[str]:
    stage(target)
    problems = verify(target)
    if not problems and run_smoke:
        problems = smoke(target)
    return problems


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    manifest = load_manifest()
    if args.check:
        with tempfile.TemporaryDirectory(prefix="pir-antigravity-check-") as tmp:
            target = Path(tmp) / manifest["name"]
            problems = build_and_verify(target, not args.no_smoke)
            if problems:
                print(
                    f"FAIL: {len(problems)} problem(s) in the Antigravity extension bundle:", file=sys.stderr
                )
                for problem in problems:
                    print(f"  - {problem}", file=sys.stderr)
                return 1
            files = sum(1 for p in target.rglob("*") if p.is_file())
        print(f"PASS: the Antigravity extension bundle verifies ({files} files)", file=sys.stderr)
        return 0

    target = Path(args.stage) if args.stage else DEFAULT_STAGE_PARENT / manifest["name"]
    problems = build_and_verify(target, not args.no_smoke)
    if problems:
        print(
            f"FAIL: {len(problems)} problem(s) in the Antigravity extension bundle at {target}:",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"staged {target}", file=sys.stderr)

    if args.package:
        code, artifacts, messages = package(
            target, Path(args.out_dir) if args.out_dir else DEFAULT_PACKAGE_DIR
        )
        for message in messages:
            print(message, file=sys.stderr)
        if code != 0:
            return code
        for art in artifacts:
            print(f"wrote {art} ({art.stat().st_size} bytes)", file=sys.stderr)

    if args.install:
        root = plugins_root(
            Path(args.workspace) if args.workspace else None,
            Path(args.plugins_dir) if args.plugins_dir else None,
        )
        print(f"install destination: {root / manifest['name']}", file=sys.stderr)
        code, messages = install(target, root, create_root=not args.plugins_dir)
        for message in messages:
            print(message, file=sys.stderr)
        if code != 0:
            return code

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
