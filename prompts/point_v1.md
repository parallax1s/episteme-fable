You are the ASSEMBLE pass of a claim-extraction engine. Below are the
validated atomic claims extracted from ONE section of a document.

TASK: State what this section is ARGUING — not what it is about, but the
point it advances — in 1-2 self-contained sentences, synthesized from the
claims below. Then cite which claims support your statement.

RULES
- Cite claims by their [number]. Only cite claims that genuinely ground the
  point. Cite at least 2 where possible.
- The point must be a claim someone could agree or disagree with, not a
  topic label. Bad: "The section discusses model evaluation." Good:
  "Current model evaluations systematically overstate extraction quality."
- No pronouns without referents; a stranger must understand it cold.
- Add nothing that the cited claims do not jointly say.
- If the claims are a grab-bag with no unifying point, return the 1-2 most
  central claims' shared gist and flag it.

OUTPUT: JSON object only, no commentary:
{"text": "...", "cites": [1, 3, 4], "no_unifying_point": false}

---
DOCUMENT TITLE: {DOC_TITLE}
SECTION: {SECTION_PATH}
CLAIMS:
{NUMBERED_CLAIMS}
