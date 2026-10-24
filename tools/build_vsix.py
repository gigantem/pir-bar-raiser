#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""build_vsix.py: the VS Code extension, assembled from the canonical surfaces and verified.

The extension is declarative: no code of its own runs in VS Code. It contributes the three custom
agents, the three prompt files and the `pir-assessment` skill through package.json contribution
points (`chatAgents`, `chatPromptFiles`, `chatSkills`; VS Code 1.109 or later with GitHub Copilot
Chat), and the skill folder carries everything the agents run or read: the runtime tools, the
schemas, the catalogs, the design, the templates and the worked examples, at the same relative
paths they have in this repository.

Nothing in the bundle is maintained twice. The agents, prompts and skill are read from assistant/;
their relative links are rewritten for the bundle's layout, their `python tools/...` commands are
pointed at the bundled tools, and an "installed from the extension" preamble (vsix/installed-preamble.md)
is inserted after each frontmatter. The result is verified before anything is packaged: every
link resolves inside the bundle, every command names a bundled tool, the tools' imports close
over the bundle, the manifest lists exactly the files staged, and the bundle runs the whole
loop (validate, interview, ledger, scaffold, render) from a workspace that holds nothing but a
packet. A verification failure is exit 1; node or npm absent is exit 2, a SKIP. vsce itself is
the one pinned in tools/vsce/package-lock.json, installed with `npm ci --ignore-scripts`.

    python tools/build_vsix.py               # stage under out/vsix/<name>/ and verify it
    python tools/build_vsix.py --check       # stage into a temporary directory, verify, discard
    python tools/build_vsix.py --package     # stage, verify, run the locked vsce: out/<name>-<version>.vsix

The bundled tools resolve the paths they cite (pirs/, interviews/, clarifications/, reviews/)
against the directory they run from, which is why the agents run them from the workspace root.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import extension_bundle as bundle
from extension_bundle import REPO_ROOT, SKILL_DIR

SOURCES = REPO_ROOT / "vsix"
MANIFEST_SRC = SOURCES / "package.json"
README_SRC = SOURCES / "README.md"
PREAMBLE_SRC = SOURCES / "installed-preamble.md"
DEFAULT_STAGE_PARENT = REPO_ROOT / "out" / "vsix"
DEFAULT_PACKAGE_DIR = REPO_ROOT / "out"

VSCE_VERSION = "4.0.0"
#: vsce and every package it pulls in, pinned by integrity hash. Installed with
#: `npm ci --ignore-scripts`, so nothing in the tree runs an install script; only the signing helper
#: has one, and packaging does not sign.
VSCE_LOCK_DIR = REPO_ROOT / "tools" / "vsce"

#: What vsce leaves out of the package: nothing the stage writes on purpose, only what running
#: or importing the bundled tools could leave behind.
VSCODEIGNORE = "**/__pycache__/**\n**/*.py[cod]\n.vscodeignore\n"


# ------------------------------------------------------------------------------ transforms


def load_manifest(path: Path = MANIFEST_SRC) -> dict[str, Any]:
    return bundle.load_manifest(path)


def with_skill_metadata(text: str, manifest: dict[str, Any]) -> str:
    """Add the Agent Skills fields the bundle can state: licence, compatibility, provenance."""
    return bundle.with_skill_metadata(
        text,
        license_id=manifest["license"],
        version=manifest["version"],
        publisher=manifest["publisher"],
        host="GitHub Copilot Chat in VS Code 1.109 or later",
    )


def preamble_for(manifest: dict[str, Any]) -> str:
    return PREAMBLE_SRC.read_text(encoding="utf-8").format(
        publisher=manifest["publisher"], name=manifest["name"], version=manifest["version"]
    )


# --------------------------------------------------------------------------------- staging


def stage(target: Path) -> Path:
    """Assemble the extension under `target` (replaced if it is a previous stage) and return it."""
    manifest = load_manifest()
    bundle.clear_previous_stage(target, "package.json", manifest["name"])
    preamble = preamble_for(manifest)

    for kind, pattern in (("agents", "*.agent.md"), ("prompts", "*.prompt.md")):
        (target / kind).mkdir(parents=True)
        for source in sorted((bundle.SURFACES / kind).glob(pattern)):
            text = bundle.staged_surface(source.read_text(encoding="utf-8"), preamble)
            (target / kind / source.name).write_text(text, encoding="utf-8")

    bundle.stage_skill(target / SKILL_DIR, preamble, lambda text: with_skill_metadata(text, manifest))

    (target / ".vscodeignore").write_text(VSCODEIGNORE, encoding="utf-8")
    shutil.copyfile(MANIFEST_SRC, target / "package.json")
    bundle.stage_documents(target, README_SRC)
    return target


# ---------------------------------------------------------------------------- verification


def _contributed_paths(manifest: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for entries in (manifest.get("contributes") or {}).values():
        for entry in entries:
            paths.append(str(entry.get("path", "")).removeprefix("./"))
    return paths


def verify(target: Path) -> list[str]:
    """Every defect the bundle could carry, as one message each; empty when it is sound."""
    problems: list[str] = []
    try:
        manifest = load_manifest(target / "package.json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"package.json: {exc}"]
    for key in ("name", "publisher", "version", "engines", "license", "contributes"):
        if key not in manifest:
            problems.append(f"package.json: missing {key}")
    if not str((manifest.get("engines") or {}).get("vscode", "")).startswith("^1."):
        problems.append("package.json: engines.vscode must pin a 1.x floor")

    contributed = _contributed_paths(manifest)
    for relative in contributed:
        if not (target / relative).is_file():
            problems.append(f"package.json contributes {relative}, which is not in the bundle")
    staged_surfaces = sorted(
        str(p.relative_to(target)).replace("\\", "/")
        for p in [
            *target.glob("agents/*.md"),
            *target.glob("prompts/*.md"),
            *target.glob("skills/*/SKILL.md"),
        ]
    )
    for relative in staged_surfaces:
        if relative not in contributed:
            problems.append(f"{relative} is staged but package.json does not contribute it")
    if not (target / ".vscodeignore").is_file():
        problems.append(".vscodeignore is missing from the bundle")

    problems.extend(bundle.verify_bundle(target))
    return problems


def smoke(target: Path, python: str = sys.executable) -> list[str]:
    """Run the bundled tools through the whole loop from a workspace that holds only a packet."""
    return bundle.smoke(target, python, "pir-vsix-smoke-")


# ------------------------------------------------------------------------------- packaging


def install_vsce(tool_dir: Path, lock_dir: Path = VSCE_LOCK_DIR) -> tuple[Path | None, list[str]]:
    """Install the locked vsce into `tool_dir` with `npm ci --ignore-scripts`; return its entry point.

    The lock is copied beside an empty node_modules so the install is exactly what it records, and
    the installed version is checked against VSCE_VERSION rather than trusted."""
    npm = shutil.which("npm")
    if npm is None:
        return None, [
            "SKIP: npm is not installed, so the .vsix cannot be packaged here (a skip is not a pass)"
        ]
    if tool_dir.exists():
        shutil.rmtree(tool_dir)
    tool_dir.mkdir(parents=True)
    for name in ("package.json", "package-lock.json"):
        shutil.copyfile(lock_dir / name, tool_dir / name)
    result = subprocess.run(
        [npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
        cwd=tool_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-8:]
        return None, [f"npm ci of the locked vsce failed ({result.returncode}): {' | '.join(tail)}"]
    installed = tool_dir / "node_modules" / "@vscode" / "vsce"
    meta = json.loads((installed / "package.json").read_text(encoding="utf-8"))
    if meta.get("version") != VSCE_VERSION:
        return None, [
            f"the lock installs vsce {meta.get('version')}, not {VSCE_VERSION}; regenerate tools/vsce"
        ]
    bin_field = meta.get("bin")
    entry = bin_field.get("vsce") if isinstance(bin_field, dict) else bin_field
    if not isinstance(entry, str):
        return None, ["the installed vsce declares no entry point"]
    return installed / entry, []


def required_node_major(lock_dir: Path = VSCE_LOCK_DIR) -> int | None:
    """The minimum node major the locked vsce declares (`engines.node`, ">= 22"), or None if it declares none."""
    lock = json.loads((lock_dir / "package-lock.json").read_text(encoding="utf-8"))
    spec = (lock["packages"].get("node_modules/@vscode/vsce", {}).get("engines") or {}).get("node", "")
    match = re.match(r"^\s*>=\s*(\d+)", str(spec))
    return int(match.group(1)) if match else None


def node_major(node: str) -> int | None:
    result = subprocess.run([node, "--version"], capture_output=True, text=True, check=False)
    match = re.match(r"^v(\d+)\.", result.stdout.strip())
    return int(match.group(1)) if match else None


#: vsce stores these root files of the stage under its own names, and leaves `.vscodeignore` out;
#: everything else is stored under `extension/` at its staged path (measured on vsce 4.0.0).
VSCE_RENAMES = {"README.md": "readme.md", "CHANGELOG.md": "changelog.md", "LICENSE": "LICENSE.txt"}
VSCE_LEFT_OUT = frozenset({".vscodeignore"})
VSCE_ENVELOPE = frozenset({"extension.vsixmanifest", "[Content_Types].xml"})


def vsix_problems(artifact: Path, target: Path) -> list[str]:
    """The .vsix carries exactly the staged bundle, byte for byte, and nothing else: a check of a few
    names would miss a file vsce dropped or added."""
    expected: dict[str, bytes] = {}
    for path in sorted(p for p in target.rglob("*") if p.is_file()):
        relative = path.relative_to(target).as_posix()
        if relative not in VSCE_LEFT_OUT:
            expected[f"extension/{VSCE_RENAMES.get(relative, relative)}"] = path.read_bytes()
    with zipfile.ZipFile(artifact) as archive:
        names = set(archive.namelist())
        problems = [f"{artifact.name} lacks {name}" for name in sorted(expected.keys() - names)]
        problems += [
            f"{artifact.name} carries {name}, which is not staged"
            for name in sorted(names - expected.keys() - VSCE_ENVELOPE)
        ]
        problems += [
            f"{artifact.name}: {name} differs from the staged file"
            for name in sorted(expected.keys() & names)
            if archive.read(name) != expected[name]
        ]
    problems += [f"{artifact.name} lacks {name}" for name in sorted(VSCE_ENVELOPE - names)]
    return problems


def package(target: Path, out_dir: Path) -> tuple[int, Path | None, list[str]]:
    """Run the locked vsce over the stage. Exit status 2 when node or npm is absent, or node is older
    than vsce declares: a SKIP here, never a pass, and a failure in CI, which pins the node it needs."""
    node = shutil.which("node")
    if node is None:
        return (
            2,
            None,
            ["SKIP: node is not installed, so the .vsix cannot be packaged here (a skip is not a pass)"],
        )
    needed, found = required_node_major(), node_major(node)
    if needed is not None and (found is None or found < needed):
        return (
            2,
            None,
            [
                f"SKIP: the locked vsce needs node >= {needed} and this node is {found or 'unknown'}, "
                "so the .vsix cannot be packaged here (a skip is not a pass)"
            ],
        )
    entry, messages = install_vsce(out_dir / "vsce-tool")
    if entry is None:
        return (2 if messages and messages[0].startswith("SKIP:") else 1), None, messages
    manifest = load_manifest(target / "package.json")
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact = out_dir / f"{manifest['name']}-{manifest['version']}.vsix"
    if artifact.exists():
        artifact.unlink()
    command = [
        node,
        str(entry),
        "package",
        "--no-dependencies",
        "--allow-missing-repository",
        "--no-rewrite-relative-links",
        "--out",
        str(artifact),
    ]
    result = subprocess.run(command, cwd=target, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-8:]
        return 1, None, [f"vsce package failed ({result.returncode}): {' | '.join(tail)}"]
    bundle.normalise_zip(artifact)
    problems = vsix_problems(artifact, target) + bundle.archive_metadata_problems(artifact)
    return (1 if problems else 0), artifact, problems


# ------------------------------------------------------------------------------------- CLI


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble, verify and package the VS Code extension.")
    parser.add_argument(
        "--stage", help="Stage directory (default: out/vsix/<name>). Replaced only if it is a previous stage."
    )
    parser.add_argument(
        "--check", action="store_true", help="Stage into a temporary directory, verify and discard."
    )
    parser.add_argument(
        "--package", action="store_true", help="Also run vsce and write out/<name>-<version>.vsix."
    )
    parser.add_argument("--out-dir", help="Where --package writes the .vsix (default: out/).")
    parser.add_argument(
        "--no-smoke", action="store_true", help="Skip the end-to-end run of the bundled tools."
    )
    args = parser.parse_args(argv)
    if args.check and (args.stage or args.package or args.out_dir):
        parser.error("--check takes no --stage, --package or --out-dir")
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
        with tempfile.TemporaryDirectory(prefix="pir-vsix-check-") as tmp:
            target = Path(tmp) / manifest["name"]
            problems = build_and_verify(target, not args.no_smoke)
            if problems:
                print(f"FAIL: {len(problems)} problem(s) in the extension bundle:", file=sys.stderr)
                for problem in problems:
                    print(f"  - {problem}", file=sys.stderr)
                return 1
            files = sum(1 for p in target.rglob("*") if p.is_file())
        print(f"PASS: the extension bundle verifies ({files} files)", file=sys.stderr)
        return 0

    target = Path(args.stage) if args.stage else DEFAULT_STAGE_PARENT / manifest["name"]
    problems = build_and_verify(target, not args.no_smoke)
    if problems:
        print(f"FAIL: {len(problems)} problem(s) in the extension bundle at {target}:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"staged {target}", file=sys.stderr)
    if not args.package:
        return 0
    code, artifact, messages = package(target, Path(args.out_dir) if args.out_dir else DEFAULT_PACKAGE_DIR)
    for message in messages:
        print(message, file=sys.stderr)
    if code == 0 and artifact is not None:
        print(f"wrote {artifact} ({artifact.stat().st_size} bytes)", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
