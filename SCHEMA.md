# Schema

All rows are JSONL, one object per line, written atomically. Enum-ish
fields are validated by membership; unknown values are coerced + flagged,
never raised on (total validation, the ae0 discipline).

## Proposition (claims.jsonl) — L1 Aussage

| field | type | meaning |
|---|---|---|
| id | str | `c` + sha1(doc_id, sorted span offsets, kind)[:10] — stable across re-runs, independent of the rewrite wording |
| doc_id | str | document id |
| text | str | the self-contained rewrite (NOT a source substring) |
| kind | enum | assertion, question, goal, plan, inference, definition |
| claim_type | enum? | descriptive, empirical, statistical, causal, predictive, conditional, normative, evaluative, definitional, interpretive, historical, methodological |
| stance | enum | author, reported, hypothetical, refuted |
| stance_source | str? | who, when stance=reported |
| hedge | [lo, hi] | credence range the SOURCE conveys (from hedging language) |
| stated_confidence | float? | explicit number stated in the text, kept separate from hedge |
| spans | [Span] | verbatim licences: {quote, start, end, sent_ids} — offsets into the normalized document text |
| section_path | str | heading path |
| implicit_premises | [str] | unstated premises, when striking |
| flags | [str] | soft findings (possibly_compound, low_source_overlap, demonstrative_reference, quote_fuzzy_match, ...) |
| same_as | [str] | candidate duplicate ids (judged relation, not asserted) |
| tier | enum | validated, unreviewed_ai_draft, candidate |
| prompt_version / engine_version | str | provenance |

## Point (points.jsonl) — L2 Punkt

`{id, doc_id, section_path, text, claim_ids, flags, tier}` — one synthesized
statement of what a section argues, citing the claims that ground it.
Grounding is checked (token coverage of text vs cited claims ≥ 0.4, else
flagged). Always `tier=unreviewed_ai_draft`.

## Thesis (theses.jsonl) — L3 Kernaussage

`{id, doc_id, text, point_ids, claim_ids, flags, tier}` — 1-4 per document.

## Rejection (rejections.jsonl)

`{doc_id, stage, reasons, raw}` — a proposal that failed a validator, with
the stage that killed it. The funnel (stats.json `rejected_by_stage`) is a
quality metric, not garbage collection.

## Design invariants

1. `text` is never a substring of the source; `spans[].quote` always is.
2. No row enters claims.jsonl without passing every hard validator.
3. Identity never depends on LLM wording.
4. Synthesized rows (points/theses) always cite their inputs by id and
   always carry a non-validated tier.
5. Validators are pure functions of the row + source text: re-runnable
   retroactively over any stored corpus when tightened.
