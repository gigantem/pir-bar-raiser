# Templates

- `PIR-Template.docx`: the Post-Incident Review template, **generated** by
  `tools/render_pir_docx.py --output docs/templates/PIR-Template.docx` from the packet layout, the
  section catalog (`template_guidance`, expectation, common mistakes), the worked example packet
  (Appendix A's example) and the principles catalog (Appendix B). The gate regenerates it and
  compares its outline (`examples/rendered/template.outline.txt`); never hand-edit it.
- `PIR-Template-DRAFT.docx`: the reviewed draft of the template, made from the deck "What Good
  Looks Like for Post-Incident Reviews". It is the reference the generated template is held to: a
  test asserts the two have the same Heading 1 and Heading 2 sequence. Its Appendix A still states
  the worked example's time to detect as 15 minutes; the generated template's appendix is rendered
  from the packet and says 9. Read the generated one.
