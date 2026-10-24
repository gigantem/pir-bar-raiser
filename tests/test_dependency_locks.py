# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""What the gate installs is pinned and hashed, and the pins agree with the ranges.

`requirements-dev.txt` keeps the ranges the bundles also carry; `requirements-dev.lock` is what CI
installs, with `--require-hashes`. `tools/vsce/` pins the VS Code packaging tool and everything it
pulls in by integrity hash; `tools/build_vsix.py` installs it with `npm ci --ignore-scripts`.
Neither lock can be regenerated here without a network, so these tests hold each lock to its
source instead: a range moved without the lock, or a lock edited by hand, fails.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import build_vsix
import pytest
from packaging.requirements import Requirement

REPO_ROOT = Path(__file__).resolve().parent.parent
DEV = REPO_ROOT / "requirements-dev.txt"
LOCK = REPO_ROOT / "requirements-dev.lock"
VSCE = REPO_ROOT / "tools" / "vsce"
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _locked() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        match = PIN.match(line)
        if match:
            pins[_norm(match.group(1))] = match.group(2)
    return pins


def _requirements() -> list[Requirement]:
    return [
        Requirement(line)
        for line in DEV.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_every_dev_requirement_is_locked_within_its_range() -> None:
    pins = _locked()
    for requirement in _requirements():
        version = pins.get(_norm(requirement.name))
        assert version, f"{requirement.name} is not in requirements-dev.lock"
        assert requirement.specifier.contains(version, prereleases=True), (
            f"requirements-dev.lock pins {requirement.name}=={version}, outside {requirement.specifier}; "
            "regenerate the lock (its header has the command)"
        )


def test_every_locked_package_carries_a_hash() -> None:
    blocks = re.split(r"\n(?=[A-Za-z0-9])", LOCK.read_text(encoding="utf-8"))
    entries = [b for b in blocks if PIN.match(b)]
    assert len(entries) == len(_locked()) >= len(_requirements())
    for entry in entries:
        assert "--hash=sha256:" in entry, entry.splitlines()[0]


def test_the_lock_says_how_it_was_made() -> None:
    head = LOCK.read_text(encoding="utf-8").splitlines()[:4]
    assert any("uv pip compile requirements-dev.txt --generate-hashes" in line for line in head)
    assert any("--require-hashes" in line for line in head)


def test_the_vsce_lock_pins_the_version_the_builder_expects() -> None:
    manifest = json.loads((VSCE / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((VSCE / "package-lock.json").read_text(encoding="utf-8"))
    assert manifest["private"] is True
    assert manifest["devDependencies"] == {"@vscode/vsce": build_vsix.VSCE_VERSION}
    assert lock["packages"][""]["devDependencies"] == manifest["devDependencies"]
    assert lock["packages"]["node_modules/@vscode/vsce"]["version"] == build_vsix.VSCE_VERSION


def test_every_package_in_the_vsce_lock_is_pinned_by_integrity_from_the_registry() -> None:
    lock = json.loads((VSCE / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["lockfileVersion"] >= 3
    packages = {name: meta for name, meta in lock["packages"].items() if name}
    assert packages
    for name, meta in packages.items():
        assert meta.get("integrity", "").startswith("sha512-"), name
        assert meta.get("resolved", "").startswith("https://registry.npmjs.org/"), name


def test_only_the_signing_helper_has_an_install_script() -> None:
    """`npm ci --ignore-scripts` skips it; packaging does not sign. A new one is a decision to make."""
    lock = json.loads((VSCE / "package-lock.json").read_text(encoding="utf-8"))
    scripted = sorted(name for name, meta in lock["packages"].items() if meta.get("hasInstallScript"))
    assert scripted == ["node_modules/@vscode/vsce-sign"]


@pytest.mark.parametrize("missing", ["node", "npm"])
def test_packaging_without_node_or_npm_is_a_skip_not_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    real_which = build_vsix.shutil.which
    monkeypatch.setattr(
        build_vsix.shutil,
        "which",
        lambda name: None if name == missing else real_which(name) or f"/usr/bin/{name}",
    )
    monkeypatch.setattr(build_vsix, "node_major", lambda node: 22)
    monkeypatch.setattr(
        build_vsix.subprocess,
        "run",
        lambda *a, **k: pytest.fail("nothing may run when a tool is missing"),
    )
    code, artifact, messages = build_vsix.package(tmp_path / "stage", tmp_path / "out")
    assert (code, artifact) == (2, None)
    assert messages and messages[0].startswith("SKIP:") and missing in messages[0]


def test_the_locked_install_ignores_scripts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    class Done:
        returncode = 1
        stdout = ""
        stderr = "network unavailable"

    def fake_run(command, **kwargs):
        seen.append(command)
        return Done()

    monkeypatch.setattr(build_vsix.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(build_vsix.subprocess, "run", fake_run)
    entry, messages = build_vsix.install_vsce(tmp_path / "tool")
    assert entry is None and "npm ci of the locked vsce failed" in messages[0]
    assert seen == [["/usr/bin/npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"]]
    assert (tmp_path / "tool" / "package-lock.json").read_bytes() == (VSCE / "package-lock.json").read_bytes()


def test_the_node_floor_is_read_from_the_lock_and_ci_pins_it() -> None:
    """vsce 4.0.0 declares node >= 22; a container rehearsal under node 18 crashed in vsce's loader."""
    assert build_vsix.required_node_major() == 22
    workflow = (REPO_ROOT / ".github" / "workflows" / "pir-gate.yml").read_text(encoding="utf-8")
    assert re.search(r"actions/setup-node@[0-9a-f]{40} # v\d", workflow)
    assert re.search(r"node-version: '(\d+)'", workflow).group(1) == str(build_vsix.required_node_major())


def test_a_node_older_than_vsce_needs_is_a_skip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_vsix.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(build_vsix, "node_major", lambda node: 18)
    monkeypatch.setattr(
        build_vsix, "install_vsce", lambda *a, **k: pytest.fail("no install for a node too old")
    )
    code, artifact, messages = build_vsix.package(tmp_path / "stage", tmp_path / "out")
    assert (code, artifact) == (2, None)
    assert messages[0].startswith("SKIP:") and "node >= 22" in messages[0] and "18" in messages[0]


def test_ruff_toml_requires_the_ruff_the_lock_installs() -> None:
    """ruff is pinned exactly, so a local ruff and CI's cannot lint differently."""
    config = (REPO_ROOT / "ruff.toml").read_text(encoding="utf-8")
    required = re.search(r'^required-version = "==([^"]+)"$', config, re.MULTILINE)
    assert required, "ruff.toml must pin the exact ruff version"
    assert required.group(1) == _locked()["ruff"]
