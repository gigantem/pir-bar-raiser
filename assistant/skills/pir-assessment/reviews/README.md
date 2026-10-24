# Reviews

Reviewer-findings artifacts for real PIRs, one directory per packet:

```
reviews/<packet stem>/<YYYYMMDDTHHMMSSZ>-<reviewer>.json   # schemas/pir-review.schema.json
```

`<reviewer>` is the persona or person who formed the judgements (`pir-reviewer`, or a lowercase
name for a human review). Keep every run; the newest artifact is current and the earlier ones are
the review history.

```bash
# Render the envelope; never type it. Refused in any directory called reviews/, through a symbolic
# link, and under the review naming convention.
python tools/render_pir_review_scaffold.py pirs/<stem>.yaml --review-stage go \
  --output /tmp/<stem>.scaffold.json
# ... replace every ASSESSOR_JUDGEMENT_REQUIRED with a judgement, delete the _scaffold block,
#     save as reviews/<stem>/<ts>-pir-reviewer.json ...
python tools/validate_pir_review.py reviews/<stem>/<ts>-pir-reviewer.json
```

What the validator holds the artifact to: the counts equal the findings; the status follows from
them (`FAIL` exactly when an unwaived blocker exists, `PASS_WITH_WAIVERS` when a finding carries a
waiver); no sentinel remains; `subject.path` resolves and `subject.id` is what the packet declares;
while `subject.revision` equals the packet's current digest, `gate_evidence` must equal a fresh run
of the validator; a review cannot `PASS` a packet the gate rejects; `coverage` has one judgement
per template section saying what was checked and found (never a stock "OK" or "Looks good"); the
reviewer's prose (summary, coverage, notes, findings, waivers) is blameless; and an artifact
under `reviews/` is filed as `reviews/<stem>/<YYYYMMDDTHHMMSSZ>-<reviewer>.json` and reviews
`pirs/<stem>.yaml`. A review's stage may not be ahead of the packet's status: a `team` review
needs the packet at `in_team_review` or later, a `go` or `exec_go` review at `in_go_review` or later
(REVIEW-STAGE-AHEAD); a `readiness` review fits any status, so a published PIR can still be audited.

A passing review (`PASS` or `PASS_WITH_WAIVERS`) must be verifiable here: its revision is the
packet's current digest and its subject is not `external:`. Otherwise nothing shows the gate passes
the bytes it names, so the pass is an error (REVIEW-PASS-UNVERIFIED): render a new scaffold against
the packet as it is now and review that. A `FAIL` review whose revision no longer matches is
reported as stale, a warning: it is history, not a verdict on the current packet. Record `null`
when you did not observe a digest; never guess one. A `null` revision can only carry a `FAIL`.

Every artifact under this directory is checked by `tools/check_artifact_conventions.py`, run
from the root of the repository that holds the PIR.
Worked examples, a go-stage `PASS` and a readiness `FAIL`, are under `examples/reviews/good/`; the
scaffold the reviewer starts from, rendered from the draft packet, is under
`examples/scaffolds/`.
