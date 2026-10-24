# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""A package says nothing about who built it, where or when.

`extension_bundle` writes the Antigravity archives with no owner, no gzip name or time, and every
entry stamped 1980-01-01T00:00Z; it rewrites vsce's .vsix the same way and in a fixed entry order;
and `verify_bundle` refuses a bundled .docx whose entries record when it was written. So the same
source always builds the same bytes.
"""

from __future__ import annotations

import gzip
import io
import tarfile
import zipfile
from pathlib import Path

import build_antigravity
import build_vsix
import extension_bundle as bundle
import pytest

BUILDERS = {"vsix": build_vsix, "antigravity": build_antigravity}


def _tree(tmp_path: Path) -> Path:
    target = tmp_path / "pir-assessor"
    (target / "skills" / "s").mkdir(parents=True)
    (target / "plugin.json").write_text('{"name": "pir-assessor"}\n', encoding="utf-8")
    (target / "skills" / "s" / "SKILL.md").write_text("---\nname: s\n---\n", encoding="utf-8")
    return target


def test_the_written_archives_say_nothing_about_their_builder(tmp_path: Path) -> None:
    target = _tree(tmp_path)
    tar_artifact, zip_artifact = tmp_path / "p.tar.gz", tmp_path / "p.zip"
    bundle.write_tar_gz(target, tar_artifact)
    bundle.write_zip(target, zip_artifact)
    assert bundle.archive_metadata_problems(tar_artifact) == []
    assert bundle.archive_metadata_problems(zip_artifact) == []
    with tarfile.open(tar_artifact, "r:gz") as tar:
        assert sorted(tar.getnames()) == ["pir-assessor/plugin.json", "pir-assessor/skills/s/SKILL.md"]
        member = tar.extractfile("pir-assessor/plugin.json")
        assert member is not None
        assert member.read() == b'{"name": "pir-assessor"}\n'
    with zipfile.ZipFile(zip_artifact) as archive:
        assert archive.read("pir-assessor/skills/s/SKILL.md") == b"---\nname: s\n---\n"


def test_writing_twice_gives_the_same_bytes(tmp_path: Path) -> None:
    target = _tree(tmp_path)
    for name in ("a", "b"):
        bundle.write_tar_gz(target, tmp_path / f"{name}.tar.gz")
        bundle.write_zip(target, tmp_path / f"{name}.zip")
    assert (tmp_path / "a.tar.gz").read_bytes() == (tmp_path / "b.tar.gz").read_bytes()
    assert (tmp_path / "a.zip").read_bytes() == (tmp_path / "b.zip").read_bytes()


def test_a_tar_with_the_default_metadata_is_caught(tmp_path: Path) -> None:
    """What `tarfile.add` wrote before: the builder's user and group names, and the build time."""
    target = _tree(tmp_path)
    artifact = tmp_path / "p.tar.gz"
    with tarfile.open(artifact, "w:gz") as tar:
        tar.add(target / "plugin.json", arcname="pir-assessor/plugin.json")
    problems = bundle.archive_metadata_problems(artifact)
    assert any("records a build time" in p for p in problems), problems
    assert any("the gzip header records" in p for p in problems), problems


def test_a_tar_that_names_its_owner_is_caught(tmp_path: Path) -> None:
    artifact = tmp_path / "p.tar.gz"
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        info = tarfile.TarInfo("pir-assessor/x")
        info.mtime, info.uname, info.gname = bundle.ARCHIVE_MTIME, "someone", "someone"
        tar.addfile(info, io.BytesIO(b""))
    artifact.write_bytes(gzip.compress(raw.getvalue(), mtime=bundle.ARCHIVE_MTIME))
    assert any("records an owner" in p for p in bundle.archive_metadata_problems(artifact))


def test_a_zip_stamped_with_the_build_time_is_caught_and_normalised(tmp_path: Path) -> None:
    """What vsce writes: every entry stamped with the build machine's local time, in the order its
    directory walk happened to return, which differs between two runs over the same stage."""
    envelope = [("extension.vsixmanifest", b"<m/>"), ("[Content_Types].xml", b"<t/>")]
    files = [("extension/b/z.md", b"z"), ("extension/a.md", b"a"), ("extension/b/c.md", b"c")]
    runs = []
    for order in (files, list(reversed(files))):
        artifact = tmp_path / f"run{len(runs)}.vsix"
        with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in envelope + order:
                archive.writestr(zipfile.ZipInfo(name, date_time=(2026, 10, 22, 18, 18, 54)), data)
        assert any("records a build time" in p for p in bundle.archive_metadata_problems(artifact))
        bundle.normalise_zip(artifact)
        assert bundle.archive_metadata_problems(artifact) == []
        assert not artifact.with_name(artifact.name + ".normalising").exists()
        runs.append(artifact)
    with zipfile.ZipFile(runs[0]) as archive:
        assert [(i.filename, archive.read(i)) for i in archive.infolist()] == envelope + sorted(files), (
            "the same entries, byte for byte: the envelope first as written, then the rest by name"
        )
    assert runs[0].read_bytes() == runs[1].read_bytes(), "two walk orders, one package"


def test_the_antigravity_packages_say_nothing_about_their_builder(tmp_path: Path) -> None:
    target = build_antigravity.stage(tmp_path / "s" / "pir-assessor")
    _, artifacts, problems = build_antigravity.package(target, tmp_path / "out")
    assert not [p for p in problems if "records" in p or "carries" in p], problems
    for artifact in artifacts:
        assert bundle.archive_metadata_problems(artifact) == []


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_a_bundled_document_that_records_when_it_was_written_is_caught(tmp_path: Path, name: str) -> None:
    target = BUILDERS[name].stage(tmp_path / "pir-assessor")
    assert bundle.document_stamp_problems(target) == []
    template = next(target.rglob("PIR-Template.docx"))
    with zipfile.ZipFile(template) as source:
        entries = [(i.filename, source.read(i)) for i in source.infolist()]
    with zipfile.ZipFile(template, "w") as rewritten:
        for entry, data in entries:
            rewritten.writestr(zipfile.ZipInfo(entry, date_time=(2026, 10, 16, 17, 0, 12)), data)
    assert any("records the time it was written" in p for p in BUILDERS[name].verify(target))
