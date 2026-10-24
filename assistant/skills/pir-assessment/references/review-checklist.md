# Review checklist

The deck's reviewer guidance, in the order to apply it. The validator has already proven presence, shape,
consistency and vocabulary; everything here is a judgement it cannot make.

As you walk it, write the review's `coverage` entry for each template section the item names: one line saying what
you checked and what you found, citing finding ids. The validator requires every section and rejects a stock "OK".
Give each finding an item raises the `category` that item names (the review contract's `category` values), and the
`section` its coverage entry names.

1. **Blameless, first and throughout.** Does any sentence make the incident about a person, a team or a vendor
   rather than a process, design or tooling gap? The lexicon catches the obvious words; you catch the tone.
   (coverage: `cross_cutting`; category: `blameless`)
2. **Would a reader with no context understand the summary in a minute?** Service, metric, when, what happened,
   impact in numbers. Written last, consistent with the body, no new facts. (coverage: `summary`; category: `summary`)
3. **Does the timeline show where the time went?** Impact start before detection; rejected hypotheses present;
   each row evidenced. Can you reconstruct time to detect, know and remediate from the rows alone?
   (coverage: `timeline`, `document_control`; category: `timeline`, `timing`)
4. **Do the graphs show the shape of the failure?** Customer-facing and diagnostic metrics, same window,
   annotated, against a baseline, at the finest resolution available. (coverage: `metrics`; category: `metrics`)
5. **Is the customer impact in the customer's terms and counted honestly?** Who, what they saw, how many, how
   counted, for how long, what was not affected, data integrity stated. (coverage: `customer_impact`; category: `customer_impact`)
6. **Does each Five Whys chain reach a cause that would hold regardless of who was on shift?** A chain that
   stops at "the change was made" or "the alert was de-tuned" has not asked why that was possible. A chain that
   reached the answer at why two and padded to five is also a finding. (coverage: `response_analysis`,
   `five_whys`; category: `response_analysis`, `root_cause_depth`)
7. **Is the root cause true?** Does the evidence cited actually support each answer, or is the chain a story that
   fits? Ask for the artifact when an answer is asserted. (coverage: `five_whys`; category: `root_cause_truth`, `evidence`)
8. **Are the lessons honest and ours?** First person plural, about processes and tools, no softened language,
   each tied to a root cause. (coverage: `lessons`; category: `lesson`, `traceability`)
9. **Would the corrective actions halve time to detect, time to know or time to remediate, or prevent
   recurrence?** Something for detection and recovery, not only prevention. Actions scoped to the gap, which may
   be another team's system. (coverage: `corrective_actions`; category: `corrective_action`)
10. **Would each action item actually stop the next occurrence?** Concrete, verifiable, owned by someone who
    agreed, due on a date reasonable for the work. "Investigate" is not an action. Five good items beat twenty.
    (coverage: `action_items`; category: `action_item`)
11. **Is the review record honest?** Stages in order, open questions with an owner and a date, nothing answered
    from memory after the meeting. (coverage: `review`; category: `review_process`)
12. **Do not nitpick grammar.** A finding is about whether the PIR says what happened, why, and what will change.
