# Clarification ledgers

The audit trail of each interview round for real PIRs, one directory per packet:

```
clarifications/<packet stem>/<YYYYMMDDTHHMMSSZ>-L<nn>.yaml   # schemas/pir-clarification-ledger.schema.json
```

A ledger is opened from its interview with every question open, then filled in as the owner
answers: the answer, its evidence, who gave it (a person or a team, never a role word) and when,
and once the answer has been transcribed into the packet, where it landed (`applied_to`, RFC 6901
JSON pointers into the packet). A question that cannot be answered now is `deferred` to a named
owner with a revisit date, or `waived` with a reason.

```bash
python tools/open_pir_ledger.py interviews/<stem>/<ts>-I01.yaml \
  --output clarifications/<stem>/<ts>-L01.yaml
# ... record answers, apply them to pirs/<stem>.yaml ...
python tools/validate_pir_ledger.py clarifications/<stem>/<ts>-L01.yaml
python tools/validate_pir.py pirs/<stem>.yaml
```

The validator holds the ledger against both files it names: every question must be one the
interview asked (same id, rule, section and blocking flag; none missing), and every `applied_to`
pointer must name something that exists in the packet. A ledger is `RESOLVED` only when no
question is open and every answer has reached the packet. Evidence that deliberately lives
outside this repository (a `source_artifacts` path, an `answer_source`) is prefixed `external:`
and reported rather than resolved. The packet and the interview in `scope` are never external:
the ledger is held against them, so a ledger lives in the repository that holds its packet.

`tools/check_artifact_conventions.py`, run from the root of the repository that holds the PIR,
validates every ledger under this directory.
Worked examples in all three states (open, partially resolved, resolved) are under
`examples/ledgers/good/`.
