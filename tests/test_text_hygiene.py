# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""Every text file in the repository is LF-terminated UTF-8 with no control bytes and no mojibake.

An edit pass can write a BEL or a TAB where a backtick-a or backtick-t was read as an escape, CRLF
line endings, or UTF-8 read back as cp1252 (U+00A7 becomes U+00C2 U+00A7), and nothing fails unless a
gate looks at the bytes. Each defect class is proved to go red on a file under tmp_path before the
repository is held to it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Text formats this repository authors. The .docx files are binary and compared by outline.
TEXT_SUFFIXES = frozenset({".md", ".py", ".sh", ".yaml", ".yml", ".json", ".toml", ".txt", ".cfg"})
TEXT_NAMES = frozenset({".gitignore", ".gitattributes", ".python-version", "LICENSE", "NOTICE"})

#: Outside a git checkout, the directories that hold nothing a repository authors (as .gitignore says).
SKIP_DIRS = frozenset(
    {".git", ".venv", "out", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
)

#: C0 controls other than LF. TAB is included: no file here uses one, and the one that appeared was damage.
CONTROL = re.compile(rb"[\x00-\x09\x0b-\x1f\x7f]")

#: UTF-8 decoded as cp1252 (or Latin-1) and re-encoded: U+00A7 -> U+00C2 U+00A7, U+2192 -> U+00E2 U+2020 U+2019.
MOJIBAKE = re.compile("[\u00c2\u00c3][\u0080-\u00bf]|\u00e2[\u20ac\u2020\u0080-\u00bf]")


def _candidates(root: Path) -> list[Path]:
    """In a git checkout, what git tracks or would track (so an ignored per-user file is never read);
    elsewhere, every file outside SKIP_DIRS."""
    if (root / ".git").exists():
        listed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            capture_output=True,
            check=True,
        ).stdout
        return sorted(root / name for name in listed.decode("utf-8").split("\0") if name)
    return sorted(
        p for p in root.rglob("*") if not any(part in SKIP_DIRS for part in p.relative_to(root).parts)
    )


def text_files(root: Path) -> list[Path]:
    return [
        path
        for path in _candidates(root)
        if path.is_file() and (path.suffix in TEXT_SUFFIXES or path.name in TEXT_NAMES)
    ]


def problems(path: Path) -> list[str]:
    raw = path.read_bytes()
    found = []
    carriage_returns = raw.count(b"\r")
    if carriage_returns:
        found.append(f"carriage return on {carriage_returns} line(s); use LF")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [*found, f"not UTF-8: {exc}"]
    for number, line in enumerate(raw.split(b"\n"), start=1):
        control = CONTROL.search(line.rstrip(b"\r"))
        if control:
            found.append(f"line {number}: control byte 0x{control.group()[0]:02x}")
    for number, line in enumerate(text.split("\n"), start=1):
        moji = MOJIBAKE.search(line)
        if moji:
            found.append(f"line {number}: mojibake {moji.group()!r} (UTF-8 read back as cp1252)")
    return found


def test_the_walk_sees_the_files_that_were_damaged() -> None:
    seen = {p.relative_to(REPO_ROOT).as_posix() for p in text_files(REPO_ROOT)}
    for expected in (
        "README.md",
        "docs/method.md",
        "antigravity/plugin.json",
        "tools/validate_pir.py",
    ):
        assert expected in seen
    assert not any(part in SKIP_DIRS for p in seen for part in Path(p).parts)


def test_every_text_file_in_this_repository_is_clean() -> None:
    dirty = {p.relative_to(REPO_ROOT).as_posix(): problems(p) for p in text_files(REPO_ROOT)}
    assert {name: found for name, found in dirty.items() if found} == {}


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"| `a` |\r\n", "carriage return"),
        (b"| \x07ntigravity/ |\n", "control byte 0x07"),
        (b"\tools/build_antigravity.py\n", "control byte 0x09"),
        ("see design \u00c2\u00a77\n".encode(), "mojibake"),
        ("gap report \u00e2\u2020\u2019 interview\n".encode(), "mojibake"),
        (b"\xff\xfe not utf-8\n", "not UTF-8"),
    ],
)
def test_each_defect_class_is_reported(tmp_path: Path, content: bytes, expected: str) -> None:
    target = tmp_path / "doc.md"
    target.write_bytes(content)
    assert any(expected in problem for problem in problems(target)), problems(target)


def test_legitimate_unicode_is_not_mojibake(tmp_path: Path) -> None:
    target = tmp_path / "doc.md"
    target.write_text("design §7: gap report → interview, 2–3 days, café, naïve\n", encoding="utf-8")
    assert problems(target) == []


#: The one copyright notice every file carries.
NOTICE = "Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>"
#: A file header: an SPDX comment line, the notice on the next one.
SPDX_HEADER = re.compile(r"^(?:#|//)\s*SPDX-License-Identifier:")
HEADER_COPYRIGHT = re.compile(r"^(?:#|//)\s*Copyright \(C\)")


def test_every_copyright_line_is_the_notice() -> None:
    """A file added before a holder change and committed after it kept the old holder once; every
    header is now held to the one notice: an SPDX line in the first lines, the notice beneath it,
    and no other copyright comment anywhere."""
    wrong = []
    for path in text_files(REPO_ROOT):
        if path.name == "LICENSE":
            continue  # the GPL's own text and its how-to-apply template
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            if SPDX_HEADER.match(line) and number <= 3:
                following = lines[number] if number < len(lines) else ""
                if following.lstrip("#/ ").rstrip() != NOTICE:
                    wrong.append(f"{path.relative_to(REPO_ROOT)}:{number + 1}: {following.strip()}")
            elif HEADER_COPYRIGHT.match(line) and NOTICE not in line:
                wrong.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
    assert not wrong, wrong
