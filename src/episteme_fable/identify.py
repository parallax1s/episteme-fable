"""IDENTIFY: stable instance identity + same_as candidates.

Instance identity is anchored in WHAT THE CLAIM POINTS AT — (doc_id, span
offsets, kind) — never in the rewritten text, because rewrites vary run to
run. Cross-run stability therefore holds as long as the source text and the
licensed spans hold.

Proposition identity across documents is a judged relation (same_as), for
which this pass only generates candidates (token Jaccard).

Two guards keep distinct claims apart (both were reproduced as bugs):

* Polarity and numbers. Content tokens drop stopwords, which include "not"
  and "no", so "X causes Y" and "X does not cause Y" used to reach Jaccard
  1.0 and collapse. Claims now merge (or become same_as candidates) only when
  their negation parity and their numeric tokens agree.
* Span collisions. Two distinct propositions licensed by the same spans got
  the same instance id, and the second was dropped as an "exact duplicate".
  When a (doc, spans, kind) key is shared by claims that are not
  near-duplicates, every claim in that group gets a content suffix, so the
  result does not depend on input order. Ids of uncollided claims are
  unchanged, so cross-run stability holds for them exactly as before.
"""
from __future__ import annotations

import hashlib

from .schemas import Proposition
from .validate import content_tokens

import re

_NEGATOR = re.compile(
    r"\b(?:not|no|never|nor|neither|none|cannot|without|lacks?|lacking|"
    r"absent|fails?\s+to|failed\s+to)\b|n't\b", re.IGNORECASE)
_NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)*%?")

SAME_AS_FLOOR = 0.6
DUP_FLOOR = 0.8


def instance_id(doc_id: str, spans: list[tuple[int, int]], kind: str) -> str:
    key = f"{doc_id}|{sorted(spans)}|{kind}"
    return "c" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def polarity(text: str) -> bool:
    """True for an affirmative claim, False when an odd number of negators."""
    return len(_NEGATOR.findall(text or "")) % 2 == 0


def numbers(text: str) -> tuple[str, ...]:
    return tuple(sorted(n.rstrip(".,") for n in _NUMBER.findall(text or "")))


def _signature(text: str) -> tuple[bool, tuple[str, ...]]:
    return polarity(text), numbers(text)


def _near_duplicate(a: Proposition, b: Proposition) -> bool:
    if _signature(a.text) != _signature(b.text):
        return False
    return _jaccard(set(content_tokens(a.text)),
                    set(content_tokens(b.text))) >= DUP_FLOOR


def _content_suffix(text: str) -> str:
    pol, nums = _signature(text)
    key = f"{int(pol)}|{','.join(nums)}|{' '.join(sorted(set(content_tokens(text))))}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:6]


def disambiguate_ids(claims: list[Proposition]) -> list[Proposition]:
    """Give distinct claims that share a span-anchored id distinct ids.

    Order-independent: if a group sharing one id holds two or more claims
    that are not near-duplicates of each other, every member is suffixed.
    """
    groups: dict[str, list[Proposition]] = {}
    for c in claims:
        groups.setdefault(c.id, []).append(c)
    for cid, members in groups.items():
        if len(members) < 2:
            continue
        distinct = any(not _near_duplicate(a, b)
                       for i, a in enumerate(members) for b in members[i + 1:])
        if distinct:
            for c in members:
                c.id = f"{cid}-{_content_suffix(c.text)}"
    return claims


def dedupe_and_link(claims: list[Proposition]) -> list[Proposition]:
    """Drop exact duplicates (same id, or near-identical text with the same
    polarity and numbers); record same_as candidates for close-but-distinct
    pairs of the same polarity and numbers."""
    claims = disambiguate_ids(claims)
    kept: list[Proposition] = []
    toks: list[set[str]] = []
    seen_ids: set[str] = set()

    for c in claims:
        ct = set(content_tokens(c.text))
        sig = _signature(c.text)
        duplicate = False
        if c.id in seen_ids:
            duplicate = True
        else:
            for k, kt in zip(kept, toks):
                if _signature(k.text) != sig:
                    continue
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
