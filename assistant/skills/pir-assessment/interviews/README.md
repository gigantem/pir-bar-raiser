# Interviews

Generated owner interviews for real PIRs, one directory per packet:

```
interviews/<packet stem>/<YYYYMMDDTHHMMSSZ>-I<nn>.yaml   # the interview (schemas/pir-interview.schema.json)
interviews/<packet stem>/<YYYYMMDDTHHMMSSZ>-I<nn>.md     # its rendering, for the room
```

`<nn>` is the round: the first interview for a packet is `I01`; after the answers are applied
and the validator still reports gaps, the next is `I02`, and so on.

```bash
python tools/generate_pir_interview.py --packet pirs/<stem>.yaml --round 1 \
  --output interviews/<stem>/$(date -u +%Y%m%dT%H%M%SZ)-I01.yaml
python tools/render_pir_interview.py interviews/<stem>/<ts>-I01.yaml \
  --output interviews/<stem>/<ts>-I01.md
```

Replace the `HUMAN_CONFIRM` placeholders (the facilitator, and the owner when the packet does
not name one) before the interview is used; `render_pir_interview.py --no-placeholders` refuses
to render while any remain. A worked example of all three files is under `examples/interviews/`
and `examples/ledgers/good/`, generated from `examples/draft/order-capture-draft.yaml`.

This directory is empty until the first real assessment. `tools/check_artifact_conventions.py`
enforces the naming convention above: it fails on any file here that does not match it, and
routes each interview to its validator and each rendering to a comparison with its YAML.
