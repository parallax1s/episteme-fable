"""IDENTIFY: stable instance identity + same_as candidates.

Instance identity is anchored in WHAT THE CLAIM POINTS AT — (doc_id, span
offsets, kind) — never in the rewritten text, because rewrites vary run to
run. Cross-run stability therefore holds as long as the source text and the
licensed spans hold.

Proposition identity across documents is a judged relation (same_as), for
which this pass only generates candidates (token Jaccard).
"""
from __future__ import annotations

import hashlib

from .schemas import Proposition
from .validate import content_tokens

SAME_AS_FLOOR = 0.6
DUP_FLOOR = 0.8


def instance_id(doc_id: str, spans: list[tuple[int, int]], kind: str) -> str:
    key = f"{doc_id}|{sorted(spans)}|{kind}"
    return "c" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedupe_and_link(claims: list[Proposition]) -> list[Proposition]:
    """Drop exact duplicates (same id, or near-identical text over the same
    spans); record same_as candidates for close-but-distinct pairs."""
    kept: list[Proposition] = []
    toks: list[set[str]] = []
    seen_ids: set[str] = set()

    for c in claims:
        ct = set(content_tokens(c.text))
        duplicate = False
        if c.id in seen_ids:
            duplicate = True
        else:
            for k, kt in zip(kept, toks):
                j = _jaccard(ct, kt)
                if j >= DUP_FLOOR:
                    duplicate = True
                    for f in c.flags:
                        if f not in k.flags:
                            k.flags.append(f)
                    break
                if j >= SAME_AS_FLOOR:
                    if c.id not in k.same_as:
                        k.same_as.append(c.id)
                    if k.id not in c.same_as:
                        c.same_as.append(k.id)
        if not duplicate:
            kept.append(c)
            toks.append(ct)
            seen_ids.add(c.id)
    return kept
