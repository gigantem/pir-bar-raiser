#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""docx_outline.py: the text of a .docx in document order, one line per paragraph, with its style.

A .docx is not comparable byte for byte (zip entry times, core-property timestamps), and a
rendering gate that compares bytes would be flaky or vacuous. What can be compared is what a
reader sees in order: every paragraph, including the ones inside table cells, prefixed by its
paragraph style. This module produces that outline, and a rendering is compared with
an expected one as outlines. It reads word/document.xml directly so it works on any .docx,
whichever tool wrote it, including the reviewed draft template the rendered template is held
against.

    python tools/docx_outline.py file.docx            # print the outline
    python tools/docx_outline.py file.docx --headings # only Heading1/Heading2 lines
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

PARAGRAPH = re.compile(r"<w:p[ >].*?</w:p>", re.S)
STYLE = re.compile(r'<w:pStyle w:val="([^"]+)"')
TEXT = re.compile(r"<w:t(?: [^>]*)?>([^<]*)</w:t>")
TAB = re.compile(r"<w:tab/>")
ENTITIES = {"&lt;": "<", "&gt;": ">", "&amp;": "&", "&quot;": '"', "&apos;": "'"}
HEADING_STYLES = ("Heading1", "Heading2", "Heading 1", "Heading 2")


def unescape(text: str) -> str:
    for entity, char in ENTITIES.items():
        text = text.replace(entity, char)
    return text


def outline_lines(docx_path: Path, headings_only: bool = False) -> list[str]:
    """`[style] text` per non-empty paragraph, in document order (body only, not headers or footers)."""
    with zipfile.ZipFile(docx_path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    lines: list[str] = []
    for paragraph in PARAGRAPH.findall(xml):
        style_match = STYLE.search(paragraph)
        style = style_match.group(1) if style_match else "-"
        text = unescape("".join(TEXT.findall(TAB.sub("\t", paragraph)))).strip()
        if not text:
            continue
        if headings_only and style not in HEADING_STYLES:
            continue
        lines.append(f"[{style}] {text}")
    return lines


def outline(docx_path: Path, headings_only: bool = False) -> str:
    return "\n".join(outline_lines(docx_path, headings_only)) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print the paragraph outline of a .docx.")
    parser.add_argument("docx", help="The .docx file.")
    parser.add_argument("--headings", action="store_true", help="Only Heading 1 and Heading 2 lines.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    path = Path(args.docx)
    if not path.is_file():
        print(f"ERROR: not found: {path}", file=sys.stderr)
        return 1
    sys.stdout.write(outline(path, args.headings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
