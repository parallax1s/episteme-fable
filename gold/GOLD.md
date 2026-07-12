# Gold labeling guidelines (v1)

A gold label set for a document is the list of Kernaussagen a careful,
well-calibrated reader would extract, plus the document's theses. Labels are
what the ENGINE SHOULD OUTPUT — so they follow the same contract the engine
is held to.

## Claims (L1 Aussagen)

Include every substantive claim the document commits to or reports. Each
gold claim must be:

1. **Atomic** — one predication. Split compounds. NEVER split a conditional
   ("If X, then Y" is one claim, kind/claim_type conditional) and never split
   a claim from its own qualification.
2. **Self-contained** — a stranger reading only the claim understands it.
   No unresolved pronouns or demonstratives. Use the document's own names
   and numbers verbatim.
3. **Faithful** — nothing added. Preserve modality ("may cause" stays
   "may cause"). Preserve quantifiers.
4. **Substantive** — skip navigation boilerplate, section announcements,
   greetings, and pure illustrations of an already-listed claim.

Also record:
- `kind`: assertion | question | goal | plan | inference | definition.
  Real open questions the text poses ARE claims — include them.
- `stance`: author | reported | hypothetical | refuted. Reported claims are
  stated as their underlying proposition (not "X says that...") with
  `stance_source` naming who.

Typical density: 2-6 claims per paragraph of argumentative prose; abstracts
are denser. When genuinely unsure whether something is substantive, include
it — the benchmark treats gold as the recall ceiling.

## Theses (L3 Kernaussagen)

The 1-4 statements the document exists to assert — what the author would
defend if challenged. Theses are claims, not topics: assertible, deniable,
self-contained. Order by importance.

## File format

`gold/labels/<doc>.json`:
```json
{
  "claims": [
    {"text": "...", "kind": "assertion", "stance": "author", "stance_source": null}
  ],
  "theses": [
    {"text": "..."}
  ]
}
```
