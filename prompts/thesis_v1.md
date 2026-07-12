You are the ASSEMBLE pass of a claim-extraction engine. Below are the
section-level points (and, where a section had no point, its claims)
extracted from ONE document.

TASK: State the document's THESES — the 1 to 4 Kernaussagen the document
exists to assert. These are the statements the author would defend if
challenged; everything else in the document works for them.

RULES
- Each thesis: one self-contained sentence a stranger understands cold.
- Cite the supporting points/claims by [number]. Every thesis needs
  at least one citation.
- Theses are claims, not topics. They must be assertible and deniable.
- Do not restate two points as two theses if they serve one larger
  conclusion — synthesize upward.
- Order by importance: the single most load-bearing thesis first.
- Add nothing the cited material does not jointly say.

OUTPUT: JSON array only, no commentary:
[{"text": "...", "cites": [2, 5]}, ...]

---
DOCUMENT TITLE: {DOC_TITLE}
MATERIAL:
{NUMBERED_ITEMS}
