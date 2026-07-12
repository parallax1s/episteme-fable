# Episteme (Fable)

Text → **Aussagen** (atomic, self-contained propositions) → **Punkte**
(what each section argues) → **Thesen** (the Kernaussagen the document
exists to assert). A ground-up redesign of the Episteme claim engine.

## The two design inversions

**1. Claims are translations, not quotations.** The old engine extracted
claims as regex-cut substrings of sentences, which made fragments
("reduced energy landscape distortion.") structural and capped every claim
at one sentence. Here, a claim's `text` is a *rewrite* — self-contained,
pronouns resolved, one predication — and its `spans` carry the verbatim
source snippets (with offsets) that license it. A claim may draw on several
sentences; an unresolved pronoun is a validation failure, not a repair
ticket.

**2. The LLM proposes, the calculus disposes.** Extraction is an LLM job
(regexes cannot do coreference, scope, or discourse). Verification is a
deterministic job. Every proposal passes through total validators — they
never raise, they return verdicts:

| stage | rejects when |
|---|---|
| fragment | fewer than 4 words |
| deixis | opener is an unresolved anaphor (`It/This/They/...`), with pleonastic-it and existential-there exceptions |
| atomicity | semicolon compound; flags `, and/but` + second verb |
| alignment | a quote can't be anchored in the source (exact → normalized → fuzzy) |
| support | a number/name in the rewrite is absent from the source; content-token coverage below floor |

Rejected proposals land in `rejections.jsonl` — the funnel is a
first-class output, because rejections measure extraction quality.

## Pipeline

```
ingest -> segment -> windows(+rolling glossary)
  -> PROPOSE   one haiku call per window, JSON contract (prompts/propose_v1.md)
  -> DISPOSE   total validators (src/episteme_fable/validate.py)
  -> IDENTIFY  instance id = hash(doc, span offsets, kind)  [rewrite-independent]
               same_as candidates by token overlap
  -> ASSEMBLE  points per section + document theses, LLM synthesis with
               index provenance, grounding-checked, tier=unreviewed_ai_draft
  -> report.md pyramid + claims/points/theses/rejections JSONL
```

## Usage

```bash
pip install -e '.[dev]'          # stdlib-only runtime; pytest for dev
epf analyze examples/peer-review.md --title "The Case Against Prestige Peer Review"
epf report out/peer-review
epf bench --judge                # score against gold/ (see below)
```

Transport is the `claude` CLI (`claude -p`, prompt on stdin). Models:
`--model` / `EPF_MODEL` for PROPOSE (default haiku),
`--assemble-model` / `EPF_MODEL_ASSEMBLE` for ASSEMBLE (default sonnet).

## Benchmark

`gold/` holds 12 labeled documents across genres (real arXiv abstracts,
argumentative essays, news-with-attribution, forum arguments, a blog post),
labeled to `gold/GOLD.md` by an opus draft → adversarial-verify fleet.
`epf bench` scores claim precision/recall/F1 (greedy token matching;
`--judge` lets an LLM adjudicate paraphrase matches), compression
(predicted/gold — the old engine ran ~4x), thesis recall, and the
rejection funnel. Results land in `bench/runs/<ts>/report.md`.

## Provenance & trust

Every claim carries `tier` (validated / unreviewed_ai_draft / candidate),
`prompt_version`, `engine_version`, `stance` + `stance_source` (author /
reported / hypothetical / refuted — reported speech never silently becomes
the author's assertion), and `hedge` `[lo, hi]` kept separate from any
`stated_confidence` in the text.

Instance identity hashes `(doc, span offsets, kind)` — never the rewrite —
so re-runs converge on the same ids while wording varies. Cross-document
proposition identity is a *judged* relation; the engine only emits
`same_as` candidates.
