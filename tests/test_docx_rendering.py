# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""One layout renders the template and a finished PIR, and the template matches the reviewed draft.

The rendered template matches the reviewed draft section for section: the regenerated template's
Heading 1 and Heading 2 sequence is asserted equal to the draft's, by reading both files' XML the
same way. The committed outlines and
markdown under examples/rendered/ are regenerated and compared, so the renderer, the catalogs and
the example packet cannot drift apart. A rendered packet carries no placeholder and no invented
value; an incomplete packet says "not yet provided" rather than filling the gap.
"""

from __future__ import annotations

import copy
from pathlib import Path

import docx_outline
import pytest
import render_pir_docx as renderer
import validate_pir
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
REVIEWED_DRAFT = REPO_ROOT / "docs" / "templates" / "PIR-Template-DRAFT.docx"
TEMPLATE = REPO_ROOT / "docs" / "templates" / "PIR-Template.docx"
FINISHED = REPO_ROOT / "examples" / "good" / "order-capture-pool-exhaustion.yaml"
DRAFT_PACKET = REPO_ROOT / "examples" / "draft" / "order-capture-draft.yaml"
RENDERED = REPO_ROOT / "examples" / "rendered"


def _docx_outline(packet: Path | None, tmp_path: Path, appendix: bool | None = None) -> str:
    writer = renderer.build(packet, "docx", packet is None if appendix is None else appendix)
    out = tmp_path / "out.docx"
    out.parent.mkdir(parents=True, exist_ok=True)
    writer.save(out)
    return docx_outline.outline(out)


def _markdown(packet: Path | None, appendix: bool | None = None) -> str:
    writer = renderer.build(packet, "md", packet is None if appendix is None else appendix)
    assert isinstance(writer, renderer.MarkdownWriter)
    return writer.text()


# ------------------------------------------------------------------ the template and the draft


def test_regenerated_template_has_the_reviewed_drafts_headings_section_for_section() -> None:
    reviewed = docx_outline.outline_lines(REVIEWED_DRAFT, headings_only=True)
    regenerated = docx_outline.outline_lines(TEMPLATE, headings_only=True)
    assert reviewed == regenerated
    assert len(reviewed) >= 40, "the heading list is the whole document structure, not a sample"


def test_the_committed_template_docx_is_what_the_renderer_produces_today(tmp_path: Path) -> None:
    assert docx_outline.outline(TEMPLATE) == _docx_outline(None, tmp_path)
    assert docx_outline.outline(TEMPLATE) == (RENDERED / "template.outline.txt").read_text(encoding="utf-8")


def test_the_committed_markdown_goldens_are_current() -> None:
    assert _markdown(None) == (RENDERED / "template.md").read_text(encoding="utf-8")
    assert _markdown(FINISHED) == (RENDERED / "order-capture.md").read_text(encoding="utf-8")


def test_the_committed_packet_outline_is_current(tmp_path: Path) -> None:
    assert _docx_outline(FINISHED, tmp_path) == (RENDERED / "order-capture.outline.txt").read_text(
        encoding="utf-8"
    )


def test_check_mode_passes_the_goldens_and_fails_a_stale_one(tmp_path: Path, capsys) -> None:
    assert renderer.main(["--check", str(RENDERED / "template.outline.txt")]) == 0
    assert renderer.main(["--format", "md", "--check", str(RENDERED / "template.md")]) == 0
    assert (
        renderer.main(
            ["--packet", str(FINISHED), "--format", "md", "--check", str(RENDERED / "order-capture.md")]
        )
        == 0
    )
    stale = tmp_path / "stale.md"
    stale.write_text(
        (RENDERED / "order-capture.md").read_text(encoding="utf-8").replace("9 min", "15 min", 1),
        encoding="utf-8",
    )
    assert renderer.main(["--packet", str(FINISHED), "--format", "md", "--check", str(stale)]) == 1
    err = capsys.readouterr().err
    assert "-| Time to detect (TTD) | Impact start to detected at | 15 min |" in err and "stale" in err


def test_appendix_a_is_the_catalog_and_the_example_packet(tmp_path: Path) -> None:
    outline = _docx_outline(None, tmp_path)
    sections = renderer.pir_interview.load_section_catalog()
    packet = validate_pir.load_document(FINISHED)
    for key in renderer.BODY_ORDER:
        assert str(sections[key]["expectation"]).strip()[:60] in outline, key
    # The worked example's key timings come from the packet, not from prose: TTD 9, not the draft's 15.
    assert "Time to detect (TTD) 9 min" in outline
    assert "TTD 15 min" not in outline
    assert packet["five_whys"][0]["root_cause"] in outline
    assert packet["action_items"][-1]["statement"] in outline


def test_appendix_b_is_the_principles_catalog(tmp_path: Path) -> None:
    outline = _docx_outline(None, tmp_path)
    principles = renderer.load_principles()
    for number, section in enumerate(principles["sections"], start=1):
        assert f"[Heading2] B.{number} {section['title']}" in outline
        for point in section["points"]:
            assert point in outline


def test_template_guidance_appears_under_every_body_heading_and_only_in_the_template(tmp_path: Path) -> None:
    sections = renderer.pir_interview.load_section_catalog()
    template = _docx_outline(None, tmp_path)
    finished = _docx_outline(FINISHED, tmp_path)
    for key in renderer.BODY_ORDER:
        guidance = str(sections[key]["template_guidance"])[:50]
        assert guidance in template, key
        assert guidance not in finished, key


# ------------------------------------------------------------------------ rendering a packet


def test_a_finished_packet_renders_with_no_placeholder_and_no_gap(tmp_path: Path) -> None:
    outline = _docx_outline(FINISHED, tmp_path)
    body = "\n".join(line.split("] ", 1)[1] for line in outline.splitlines())
    assert "[" not in body, "a finished packet has no yellow fields"
    assert renderer.NOT_PROVIDED not in body
    packet = validate_pir.load_document(FINISHED)
    for row in packet["timeline"]:
        assert row["event"] in body
    for item in packet["action_items"]:
        assert item["id"] in body and item["statement"] in body
    assert "6.1 Chain A: the failure (CH-1)" in outline
    assert "6.3 Chain C: the slow resolution (CH-3)" in outline
    assert "6.4 Chain D" not in outline, "a non-repeat incident has three chains, not a template's four"


def test_markdown_and_docx_carry_the_same_headings(tmp_path: Path) -> None:
    md_headings = [line.lstrip("# ") for line in _markdown(FINISHED).splitlines() if line.startswith("#")]
    writer = renderer.build(FINISHED, "docx", False)
    writer.save(tmp_path / "x.docx")
    docx_headings = [
        line.split("] ", 1)[1] for line in docx_outline.outline_lines(tmp_path / "x.docx", headings_only=True)
    ]
    assert md_headings == docx_headings


def test_an_incomplete_packet_says_so_instead_of_inventing(tmp_path: Path) -> None:
    packet = validate_pir.load_document(DRAFT_PACKET)
    del packet["lessons"]
    del packet["review"]
    packet["customer_impact"]["business_metrics"] = ""
    model = renderer.packet_model(packet)
    assert model["lessons"] == []
    assert model["review_stages"] == [] and model["open_questions"] == []
    assert any(answer == renderer.NOT_PROVIDED for _, answer in model["impact"])
    packet_path = tmp_path / "incomplete.yaml"
    packet_path.write_text(yaml.safe_dump(packet, sort_keys=False), encoding="utf-8")
    outline = _docx_outline(packet_path, tmp_path)
    assert renderer.NOT_PROVIDED in outline
    assert "[" not in "\n".join(line.split("] ", 1)[1] for line in outline.splitlines())


def test_key_timings_are_derived_when_not_declared() -> None:
    packet = copy.deepcopy(validate_pir.load_document(FINISHED))
    del packet["key_timings"]
    model = renderer.packet_model(packet)
    assert [value for _, _, value in model["key_timings"]] == [
        "9 min",
        "44 min",
        "21 min",
        "74 min",
        "95 min",
    ]


def test_traceability_columns_are_computed_not_typed() -> None:
    model = renderer.packet_model(validate_pir.load_document(FINISHED))
    lessons = {row[0]: row[3] for row in model["lessons"]}
    assert lessons == {"LL-1": "CA-1, CA-4", "LL-2": "CA-2", "LL-3": "CA-3"}
    cas = {row[0]: row[4] for row in model["corrective_actions"]}
    assert cas["CA-2"] == "AI-3, AI-4" and cas["CA-4"] == "AI-7"


def test_rendering_is_deterministic(tmp_path: Path) -> None:
    assert _docx_outline(FINISHED, tmp_path) == _docx_outline(FINISHED, tmp_path / "again")
    first = renderer.build(FINISHED, "docx", False)
    first.save(tmp_path / "a.docx")
    second = renderer.build(FINISHED, "docx", False)
    second.save(tmp_path / "b.docx")
    assert first.doc.core_properties.created == second.doc.core_properties.created == renderer.FIXED_TIMESTAMP


def test_the_docx_carries_a_table_of_contents_field_and_update_fields(tmp_path: Path) -> None:
    import zipfile

    writer = renderer.build(None, "docx", True)
    writer.save(tmp_path / "t.docx")
    with zipfile.ZipFile(tmp_path / "t.docx") as archive:
        document = archive.read("word/document.xml").decode("utf-8")
        settings = archive.read("word/settings.xml").decode("utf-8")
        footer = archive.read("word/footer1.xml").decode("utf-8")
    assert 'TOC \\o "1-2"' in document
    assert "w:updateFields" in settings
    assert "PAGE" in footer and "NUMPAGES" in footer


@pytest.mark.parametrize("argv", [["--format", "docx"], ["--output", "x.docx", "--check", "y.txt"]])
def test_cli_rejects_incoherent_arguments(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        renderer.parse_args(argv)


def test_cli_writes_a_packet_docx(tmp_path: Path, capsys) -> None:
    out = tmp_path / "pir.docx"
    assert renderer.main(["--packet", str(FINISHED), "--output", str(out)]) == 0
    assert out.stat().st_size > 10_000
    assert renderer.main(["--packet", str(tmp_path / "nope.yaml"), "--output", str(out)]) == 1
    assert "not found" in capsys.readouterr().err


def test_check_writes_its_scratch_docx_outside_the_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--check` writes its scratch .docx in a private temporary directory, never beside the expected
    file, so two concurrent checks cannot race."""
    seen: list[Path] = []
    real = renderer.comparable_text

    def recording(writer, scratch: Path) -> str:
        seen.append(scratch)
        return real(writer, scratch)

    monkeypatch.setattr(renderer, "comparable_text", recording)
    golden = REPO_ROOT / "examples" / "rendered" / "template.outline.txt"
    before = sorted(p.name for p in golden.parent.iterdir())
    assert renderer.main(["--check", str(golden)]) == 0
    assert seen and not seen[0].resolve().is_relative_to(REPO_ROOT)
    assert sorted(p.name for p in golden.parent.iterdir()) == before
