#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""extension_bundle.py: what the VS Code and Antigravity builders share.

Both extensions carry the same `pir-assessment` skill folder: the runtime tools, the resources the
agents read, the pinned runtime requirements, and the canonical surfaces from assistant/ with their
links and commands rewritten for the bundle. This module stages that folder, verifies what both
bundles must satisfy, and runs the bundled loop from a foreign workspace. `build_vsix.py` and
`build_antigravity.py` add only what their host needs: a manifest, the host's own surfaces, and
packaging. A tool added to `RUNTIME_TOOLS` therefore reaches both bundles, and a check added to
`verify_bundle` holds both.
"""

from __future__ import annotations

import ast
import gzip
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_NAME = "pir-assessment"
SKILL_DIR = f"skills/{SKILL_NAME}"
TOOLS_TOKEN = "<pir-assessment>"
#: The product's agents, prompts and skill: the one source both extensions are built from.
SURFACES = REPO_ROOT / "assistant"

#: The tools the surfaces invoke, plus the modules they import; `verify` proves the closure.
RUNTIME_TOOLS = (
    "validate_pir.py",
    "json_pointer.py",
    "pir_interview.py",
    "generate_pir_interview.py",
    "render_pir_interview.py",
    "open_pir_ledger.py",
    "validate_pir_ledger.py",
    "validate_pir_review.py",
    "render_pir_review_scaffold.py",
    "render_pir_docx.py",
    "docx_outline.py",
    "check_artifact_conventions.py",
)
#: Repository-relative globs copied into the skill folder at the same relative path.
RESOURCES = (
    "schemas/*.json",
    "catalogs/*.yaml",
    "docs/method.md",
    "docs/templates/*.docx",
    "examples/good/order-capture-pool-exhaustion.yaml",
    "examples/draft/order-capture-draft.yaml",
    "examples/interviews/*",
    "examples/ledgers/good/order-capture-draft-L01-*.yaml",
    "examples/reviews/good/*.json",
    "examples/scaffolds/*.json",
)
#: What a user of the extensions is told changed, release by release.
RELEASE_NOTES = REPO_ROOT / "docs" / "release-notes.md"
#: The packages the runtime tools import; their pins are taken from requirements-dev.txt.
RUNTIME_REQUIREMENTS = ("PyYAML", "jsonschema", "python-docx")

LINK = re.compile(r"\]\((?P<target>[^)\s]+)\)")
COMMAND = re.compile(r"python " + re.escape(TOOLS_TOKEN) + r"/tools/([A-Za-z0-9_]+\.py)")
SKILL_NAME_RE = re.compile(r"^(?!-)(?!.*--)[a-z0-9-]{1,64}(?<!-)$")
FRONTMATTER_END = "\n---\n"
#: A repository file an instruction names in backticks: `catalogs/x.yaml`, `schemas/y.json`, `tools/z.py`,
#: `examples/...`, `docs/...`. Inside a bundle each one must be in the skill folder.
CITED_PATH = re.compile(r"`((?:catalogs|schemas|tools|examples|docs)/[A-Za-z0-9_./-]+\.[a-z]+)`")
#: Interpreters a repository command may name; in a bundle every command runs the bundled tool.
REPO_COMMAND = re.compile(r"(?:\.venv/bin/)?python tools/")


#: Every archive entry is stamped with this instant (the earliest a zip can record) and owned by
#: nobody, so a package says nothing about who built it, where, or when.
ARCHIVE_DATE_TIME = (1980, 1, 1, 0, 0, 0)
ARCHIVE_MTIME = 315532800  # 1980-01-01T00:00:00Z


# ------------------------------------------------------------------------------ transforms


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"{path}: the manifest is not a JSON object")
    return manifest


def rewrite_links(text: str, levels_up: int, replacement: str) -> str:
    """Rewrite link targets that climb exactly `levels_up` directories to `replacement` + rest."""
    prefix = "../" * levels_up

    def substitute(match: re.Match[str]) -> str:
        target = match.group("target")
        if target.startswith(prefix) and not target.startswith(prefix + "../"):
            return "](" + replacement + target[len(prefix) :] + ")"
        return match.group(0)

    return LINK.sub(substitute, text)


def rewrite_commands(text: str) -> str:
    return REPO_COMMAND.sub(f"python {TOOLS_TOKEN}/tools/", text)


def frontmatter_end(text: str) -> int:
    """Index just past the closing `---` line of a frontmatter block; raises if there is none."""
    if not text.startswith("---\n"):
        raise ValueError("surface does not start with a frontmatter block")
    end = text.find(FRONTMATTER_END, 4)
    if end < 0:
        raise ValueError("surface frontmatter is not closed")
    return end + len(FRONTMATTER_END)


def with_preamble(text: str, preamble: str) -> str:
    end = frontmatter_end(text)
    return text[:end] + "\n" + preamble.rstrip("\n") + "\n\n" + text[end:]


def with_skill_metadata(text: str, *, license_id: str, version: str, publisher: str, host: str) -> str:
    """Add the Agent Skills fields the bundle can state: licence, compatibility, version, publisher."""
    end = frontmatter_end(text)
    closing = end - len(FRONTMATTER_END) + 1  # the position of the closing `---` line
    extra = (
        f"license: {license_id}\n"
        "compatibility: 'Requires Python 3.12 or later with PyYAML, jsonschema and python-docx "
        f"(skill folder requirements.txt); {host}.'\n"
        "metadata:\n"
        f'  pir-assessor-version: "{version}"\n'
        f'  publisher: "{publisher}"\n'
    )
    return text[:closing] + extra + text[closing:]


def runtime_requirements(dev_requirements: Path = REPO_ROOT / "requirements-dev.txt") -> str:
    """The runtime subset of requirements-dev.txt, pins included, in that file's order."""
    wanted = {name.lower() for name in RUNTIME_REQUIREMENTS}
    kept: list[str] = []
    for line in dev_requirements.read_text(encoding="utf-8").splitlines():
        name = re.split(r"[<>=!~\[ ;]", line.strip(), maxsplit=1)[0]
        if name.lower() in wanted:
            kept.append(line.strip())
            wanted.discard(name.lower())
    if wanted:
        raise ValueError(f"requirements-dev.txt does not pin: {sorted(wanted)}")
    return (
        "# The packages the PIR Assessor tools import, at the versions they are tested with.\n"
        + "\n".join(kept)
        + "\n"
    )


# --------------------------------------------------------------------------------- staging


def is_a_previous_stage(path: Path, manifest_name: str, expected_name: str) -> bool:
    """True when `path` holds a manifest called `manifest_name` that names this extension."""
    manifest = path / manifest_name
    if not manifest.is_file():
        return False
    try:
        return load_manifest(manifest).get("name") == expected_name
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def clear_previous_stage(target: Path, manifest_name: str, expected_name: str) -> None:
    """Remove `target` if it is a previous stage of this extension; refuse anything else."""
    if target.exists():
        if not is_a_previous_stage(target, manifest_name, expected_name):
            raise SystemExit(f"REFUSING TO REPLACE {target}: it is not a previous stage of this extension")
        shutil.rmtree(target)


def staged_surface(text: str, preamble: str, link_target: str = f"../{SKILL_DIR}/") -> str:
    """A canonical agent or prompt as the bundle carries it: links and commands rewritten, preamble in."""
    return with_preamble(rewrite_commands(rewrite_links(text, 2, link_target)), preamble)


def stage_skill(skill: Path, preamble: str, metadata: Callable[[str], str]) -> None:
    """Write the `pir-assessment` skill folder: the canonical skill, the runtime tools, the resources
    and the pinned runtime requirements. `metadata` adds the host's Agent Skills fields to SKILL.md."""
    skill_src = SURFACES / "skills" / SKILL_NAME
    for source in sorted(p for p in skill_src.rglob("*") if p.is_file()):
        destination = skill / source.relative_to(skill_src)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.name == "SKILL.md":
            text = rewrite_commands(rewrite_links(source.read_text(encoding="utf-8"), 3, ""))
            destination.write_text(metadata(with_preamble(text, preamble)), encoding="utf-8")
        elif source.name == "README.md":
            # A directory README tells the agent what to run, so it runs the bundled tools.
            destination.write_text(rewrite_commands(source.read_text(encoding="utf-8")), encoding="utf-8")
        else:
            shutil.copyfile(source, destination)

    (skill / "tools").mkdir()
    for name in RUNTIME_TOOLS:
        shutil.copyfile(REPO_ROOT / "tools" / name, skill / "tools" / name)
    for pattern in RESOURCES:
        matches = sorted(REPO_ROOT.glob(pattern))
        if not matches:
            raise SystemExit(f"RESOURCES names nothing: {pattern}")
        for source in matches:
            if source.is_file():
                destination = skill / source.relative_to(REPO_ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source.name == "README.md":
                    # A directory README tells the agent what to run, so it runs the bundled tools.
                    destination.write_text(
                        rewrite_commands(source.read_text(encoding="utf-8")), encoding="utf-8"
                    )
                else:
                    shutil.copyfile(source, destination)
    (skill / "requirements.txt").write_text(runtime_requirements(), encoding="utf-8")


def stage_documents(target: Path, readme: Path) -> None:
    """The user README, the release notes and the licence every bundle carries at its root. The
    release notes ship as CHANGELOG.md, the name both hosts show; the repository's own changelog
    is its development history and never ships."""
    shutil.copyfile(readme, target / "README.md")
    shutil.copyfile(RELEASE_NOTES, target / "CHANGELOG.md")
    shutil.copyfile(REPO_ROOT / "LICENSE", target / "LICENSE")


# ---------------------------------------------------------------------------- verification


def instruction_files(target: Path) -> list[Path]:
    """The files an agent acts on. A path they cite in backticks is one the agent will try to open,
    so it must be in the bundled skill, as a link's target must."""
    patterns = (
        "rules/*.md",
        "agents/*.md",
        "prompts/*.md",
        "skills/*/SKILL.md",
        "skills/*/references/*.md",
        "skills/*/*/README.md",
    )
    return sorted({p for pattern in patterns for p in target.glob(pattern) if p.is_file()})


def unresolved_citations(target: Path, skill: Path) -> list[str]:
    problems = []
    for path in instruction_files(target):
        for cited in CITED_PATH.findall(path.read_text(encoding="utf-8")):
            if not (skill / cited).is_file():
                problems.append(
                    f"{path.relative_to(target).as_posix()}: names `{cited}`, which is not in the bundled skill"
                )
    return problems


def _markdown_links(text: str) -> list[str]:
    return [m.group("target") for m in LINK.finditer(text)]


def _is_relative_link(target: str) -> bool:
    return not (target.startswith(("http://", "https://", "mailto:", "#")) or "://" in target)


def _skill_problems(skill_md: Path, target: Path) -> list[str]:
    relative = skill_md.relative_to(target).as_posix()
    text = skill_md.read_text(encoding="utf-8")
    problems = []
    name_match = re.search(r"^name:\s*(.+)$", text, re.M)
    name = name_match.group(1).strip().strip("'\"") if name_match else ""
    if name != skill_md.parent.name:
        problems.append(f"{relative} name {name!r} does not match its directory {skill_md.parent.name!r}")
    if not SKILL_NAME_RE.match(name):
        problems.append(f"{relative} name {name!r} is not a valid Agent Skills name")
    description = re.search(r"^description:\s*(.+)$", text, re.M)
    if not description or not (1 <= len(description.group(1)) <= 1024):
        problems.append(f"{relative} description is missing or longer than 1024 characters")
    return problems


def _import_problems(target: Path, skill: Path) -> list[str]:
    problems = []
    bundled_modules = {p.stem for p in (skill / "tools").glob("*.py")}
    repo_modules = {p.stem for p in (REPO_ROOT / "tools").glob("*.py")}
    for tool in sorted((skill / "tools").glob("*.py")):
        try:
            tree = ast.parse(tool.read_text(encoding="utf-8"), filename=str(tool))
        except SyntaxError as exc:
            problems.append(f"{tool.relative_to(target)} does not compile: {exc.msg} (line {exc.lineno})")
            continue
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for module in sorted(imported & repo_modules - bundled_modules):
            problems.append(f"{tool.relative_to(target)} imports {module}, which is not bundled")
    return problems


def document_stamp_problems(target: Path) -> list[str]:
    """A bundled document's own zip entries carry the fixed stamp: a rendered .docx otherwise records
    when it was written, in the local time of the machine that wrote it."""
    problems: list[str] = []
    for path in sorted(target.rglob("*.docx")):
        with zipfile.ZipFile(path) as archive:
            stamped = sorted(i.filename for i in archive.infolist() if i.date_time != ARCHIVE_DATE_TIME)
        relative = path.relative_to(target).as_posix()
        problems.extend(f"{relative}!{name}: records the time it was written" for name in stamped)
    return problems


def verify_bundle(target: Path) -> list[str]:
    """What every bundle must satisfy, whatever its host; one message per defect."""
    problems: list[str] = []
    skill = target / SKILL_DIR

    problems.extend(unresolved_citations(target, skill))
    for path in instruction_files(target):
        for command in sorted(set(REPO_COMMAND.findall(path.read_text(encoding="utf-8")))):
            problems.append(f"{path.relative_to(target).as_posix()}: a command still says `{command}`")
    for path in sorted(target.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for link in _markdown_links(text):
            if not _is_relative_link(link):
                continue
            resolved = (path.parent / link.split("#", 1)[0]).resolve()
            if not resolved.is_relative_to(target.resolve()):
                problems.append(f"{path.relative_to(target)}: link {link} leaves the bundle")
            elif not resolved.exists():
                problems.append(f"{path.relative_to(target)}: link {link} does not resolve")
        if path.parent.name in ("agents", "prompts") or path.name == "SKILL.md":
            if TOOLS_TOKEN not in text:
                problems.append(
                    f"{path.relative_to(target)}: carries no installed-from-the-extension preamble"
                )
            for tool in COMMAND.findall(text):
                if not (skill / "tools" / tool).is_file():
                    problems.append(f"{path.relative_to(target)}: command names {tool}, which is not bundled")

    if not (skill / "SKILL.md").is_file():
        problems.append(f"{SKILL_DIR}/SKILL.md is missing")
    for skill_md in sorted(target.glob("skills/*/SKILL.md")):
        problems.extend(_skill_problems(skill_md, target))

    problems.extend(_import_problems(target, skill))

    requirements = skill / "requirements.txt"
    if not requirements.is_file():
        problems.append(f"{SKILL_DIR}/requirements.txt is missing")
    elif requirements.read_text(encoding="utf-8") != runtime_requirements():
        problems.append(f"{SKILL_DIR}/requirements.txt does not carry the pins of requirements-dev.txt")

    for required in ("README.md", "LICENSE", "CHANGELOG.md"):
        if not (target / required).is_file():
            problems.append(f"{required} is missing from the bundle")
    for stray in sorted(
        p for p in target.rglob("*") if p.suffix in (".pyc", ".pyo") or p.name == "__pycache__"
    ):
        problems.append(f"{stray.relative_to(target)}: byte-code cache in the bundle")
    problems.extend(document_stamp_problems(target))
    return problems


# ------------------------------------------------------------------------------- archives


def _bundle_files(target: Path) -> list[Path]:
    return sorted(p for p in target.rglob("*") if p.is_file())


def write_tar_gz(target: Path, artifact: Path) -> None:
    """`target` as `<name>/...` in a .tar.gz whose entries and gzip header carry no owner, no
    build time and no source path: every entry is root-less, nameless and stamped `ARCHIVE_MTIME`."""
    with (
        artifact.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=ARCHIVE_MTIME) as gz,
        tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar,
    ):
        for path in _bundle_files(target):
            info = tarfile.TarInfo(archive_name(path, target.parent))
            data = path.read_bytes()
            info.size, info.mtime, info.mode = len(data), ARCHIVE_MTIME, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))


def _zip_entry(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=ARCHIVE_DATE_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3  # Unix, so the mode below is read as one
    info.external_attr = 0o644 << 16
    return info


def write_zip(target: Path, artifact: Path) -> None:
    """`target` as `<name>/...` in a .zip with every entry stamped `ARCHIVE_DATE_TIME`."""
    with zipfile.ZipFile(artifact, "w") as archive:
        for path in _bundle_files(target):
            archive.writestr(_zip_entry(archive_name(path, target.parent)), path.read_bytes())


def normalise_zip(artifact: Path) -> None:
    """Rewrite a zip someone else wrote (vsce's .vsix) with the same entries, byte for byte, each
    stamped `ARCHIVE_DATE_TIME`, in an order that does not depend on the run. vsce stamps the build
    machine's local time, and orders the files as its directory walk returns them, which differs from
    run to run. The entries at the archive's root (vsce's manifest and content types) keep their
    order and come first; every other entry follows sorted by name."""
    with zipfile.ZipFile(artifact) as source:
        written = [(info.filename, source.read(info)) for info in source.infolist()]
    entries = [e for e in written if "/" not in e[0]] + sorted(e for e in written if "/" in e[0])
    rewritten = artifact.with_name(artifact.name + ".normalising")
    with zipfile.ZipFile(rewritten, "w") as archive:
        for name, data in entries:
            archive.writestr(_zip_entry(name), data)
    rewritten.replace(artifact)


def archive_name(path: PurePath, root: PurePath) -> str:
    """`path` as an archive entry under `root`: always `/`-separated, whatever the building OS uses,
    because a `\\` in a zip or tar entry is part of the file name, not a directory separator."""
    return path.relative_to(root).as_posix()


def archive_metadata_problems(artifact: Path) -> list[str]:
    """What a package's own metadata says about its builder: an owner, a time, a source path."""
    problems: list[str] = []
    if artifact.name.endswith(".tar.gz"):
        header = artifact.read_bytes()[:10]
        if int.from_bytes(header[4:8], "little") != ARCHIVE_MTIME:
            problems.append(f"{artifact.name}: the gzip header records a build time")
        if header[3] & 0x08:
            problems.append(f"{artifact.name}: the gzip header records a file name")
        with tarfile.open(artifact, "r:gz") as tar:
            for member in tar.getmembers():
                if member.uname or member.gname or member.uid or member.gid:
                    problems.append(f"{artifact.name}: {member.name} records an owner")
                if member.mtime != ARCHIVE_MTIME:
                    problems.append(f"{artifact.name}: {member.name} records a build time")
                if member.pax_headers:
                    problems.append(f"{artifact.name}: {member.name} carries extended headers")
        return problems
    with zipfile.ZipFile(artifact) as archive:
        for info in archive.infolist():
            if info.date_time != ARCHIVE_DATE_TIME:
                problems.append(f"{artifact.name}: {info.filename} records a build time")
            if info.extra:
                problems.append(f"{artifact.name}: {info.filename} carries an extra field")
            if info.comment:
                problems.append(f"{artifact.name}: {info.filename} carries a comment")
        if archive.comment:
            problems.append(f"{artifact.name}: the archive carries a comment")
    return problems


# ----------------------------------------------------------------------------------- smoke


def smoke(target: Path, python: str, prefix: str) -> list[str]:
    """Run the bundled tools through the whole loop from a workspace that holds only a packet."""
    problems: list[str] = []
    skill = target / SKILL_DIR
    tools = skill / "tools"
    stamp = "20260101T000000Z"

    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        workspace = Path(tmp) / "workspace"
        (workspace / "pirs").mkdir(parents=True)
        shutil.copyfile(
            skill / "examples" / "good" / "order-capture-pool-exhaustion.yaml",
            workspace / "pirs" / "order-capture.yaml",
        )
        shutil.copyfile(
            skill / "examples" / "draft" / "order-capture-draft.yaml",
            workspace / "pirs" / "order-capture-draft.yaml",
        )
        (workspace / "interviews" / "order-capture-draft").mkdir(parents=True)
        (workspace / "clarifications" / "order-capture-draft").mkdir(parents=True)
        (workspace / "reviews" / "order-capture").mkdir(parents=True)

        # The bundled tools must import only each other: a PYTHONPATH pointing at this repository's
        # tools/ would let a tool missing from the bundle import its repository copy and pass.
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        def run(tool: str, *args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [python, str(tools / tool), *args],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

        def expect(label: str, result: subprocess.CompletedProcess[str], code: int) -> bool:
            if result.returncode != code:
                tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
                problems.append(
                    f"smoke: {label} exited {result.returncode}, expected {code}: {' | '.join(tail)}"
                )
                return False
            return True

        expect("validate the finished packet", run("validate_pir.py", "pirs/order-capture.yaml"), 0)
        expect(
            "validate the draft with a gap report",
            run("validate_pir.py", "pirs/order-capture-draft.yaml", "--gap-report", "gap.json"),
            1,
        )
        interview = f"interviews/order-capture-draft/{stamp}-I01.yaml"
        if expect(
            "generate the interview",
            run(
                "generate_pir_interview.py",
                "--packet",
                "pirs/order-capture-draft.yaml",
                "--gap-report",
                "gap.json",
                "--round",
                "1",
                "--output",
                interview,
            ),
            0,
        ):
            recorded = (workspace / interview).read_text(encoding="utf-8")
            if "packet: pirs/order-capture-draft.yaml" not in recorded:
                problems.append("smoke: the interview does not record the packet relative to the workspace")
        expect(
            "render the interview",
            run("render_pir_interview.py", interview, "--output", interview.removesuffix(".yaml") + ".md"),
            0,
        )
        ledger = f"clarifications/order-capture-draft/{stamp}-L01.yaml"
        expect("open the ledger", run("open_pir_ledger.py", interview, "--output", ledger), 0)
        expect("validate the ledger from the workspace", run("validate_pir_ledger.py", ledger), 0)
        expect("artifact conventions over the workspace", run("check_artifact_conventions.py"), 0)
        if expect(
            "scaffold the review",
            run(
                "render_pir_review_scaffold.py",
                "pirs/order-capture.yaml",
                "--review-stage",
                "go",
                "--output",
                "order-capture.scaffold.json",
            ),
            0,
        ):
            document = json.loads((workspace / "order-capture.scaffold.json").read_text(encoding="utf-8"))
            if document.get("subject", {}).get("path") != "pirs/order-capture.yaml":
                problems.append("smoke: the scaffold does not cite the packet relative to the workspace")
        if expect(
            "scaffold the draft's review",
            run(
                "render_pir_review_scaffold.py",
                "pirs/order-capture-draft.yaml",
                "--output",
                "draft.scaffold.json",
            ),
            0,
        ):
            document = json.loads((workspace / "draft.scaffold.json").read_text(encoding="utf-8"))
            if document.get("clarification_ledgers") != [ledger]:
                problems.append("smoke: the scaffold did not discover the workspace's ledger for the packet")
        refused = run(
            "render_pir_review_scaffold.py",
            "pirs/order-capture.yaml",
            "--output",
            "reviews/order-capture/x.scaffold.json",
        )
        if refused.returncode == 0 or "REFUSING TO WRITE" not in refused.stderr:
            problems.append("smoke: the scaffold did not refuse the workspace's reviews/ directory")
        review = json.loads(
            (skill / "examples" / "reviews" / "good" / "order-capture-go-review.json").read_text(
                encoding="utf-8"
            )
        )
        review["subject"]["path"] = "pirs/order-capture.yaml"
        review["clarification_ledgers"] = []
        filed = f"reviews/order-capture/{stamp}-pir-reviewer.json"
        (workspace / filed).write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
        expect("validate the review from the workspace", run("validate_pir_review.py", filed), 0)
        rendered = expect("render the template", run("render_pir_docx.py", "--output", "template.docx"), 0)
        if rendered and (workspace / "template.docx").stat().st_size < 10_000:
            problems.append("smoke: the rendered template is implausibly small")
        expect(
            "render the packet",
            run(
                "render_pir_docx.py", "--packet", "pirs/order-capture.yaml", "--output", "order-capture.docx"
            ),
            0,
        )
    return problems
