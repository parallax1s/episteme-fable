"""Typed records for the pyramid: L0 spans, L1 propositions, L2 points, L3 theses.

Plain dataclasses + dict round-trips; no third-party deps. Validation of
enum-ish fields happens by membership in the frozensets below — unknown
values are coerced to a fallback and flagged, never raised on.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

KINDS = frozenset({
    "assertion", "question", "goal", "plan", "inference", "definition",
})

CLAIM_TYPES = frozenset({
    "descriptive", "empirical", "statistical", "causal", "predictive",
    "conditional", "normative", "evaluative", "definitional",
    "interpretive", "historical", "methodological",
})

# Who is committed to this claim in the source text.
STANCES = frozenset({
    "author",        # the document asserts it in its own voice
    "reported",      # the document attributes it to someone else
    "hypothetical",  # entertained, supposed, or part of a thought experiment
    "refuted",       # stated in order to be denied by the source
})

TIERS = frozenset({
    "validated",            # passed all deterministic checks
    "unreviewed_ai_draft",  # synthesized (points/theses) — shape-checked only
    "candidate",            # produced by the no-LLM fallback path
})


@dataclass
class Span:
    """A verbatim licence for a claim: exact quote + offsets in the
    normalized document text + the sentence nodes it overlaps."""
    quote: str
    start: int
    end: int
    sent_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class Proposition:
    """L1 Aussage: an atomic, self-contained, rewritten statement."""
    id: str
    doc_id: str
    text: str                       # the rewrite — NOT a substring of the source
    kind: str                       # KINDS
    claim_type: str | None          # CLAIM_TYPES (assertions/inferences only)
    stance: str                     # STANCES
    stance_source: str | None       # who, when stance != author
    hedge: list[float]              # [lo, hi] credence the SOURCE conveys
    stated_confidence: float | None # explicit number in the text, if any
    spans: list[Span]
    section_path: str
    implicit_premises: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    same_as: list[str] = field(default_factory=list)
    tier: str = "validated"
    prompt_version: str = ""
    engine_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        return d


@dataclass
class Point:
    """L2 Punkt: what a section argues — synthesized, with provenance."""
    id: str
    doc_id: str
    section_path: str
    text: str
    claim_ids: list[str]
    flags: list[str] = field(default_factory=list)
    tier: str = "unreviewed_ai_draft"

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class Thesis:
    """L3 Kernaussage: a statement the document exists to assert."""
    id: str
    doc_id: str
    text: str
    point_ids: list[str]
    claim_ids: list[str]
    flags: list[str] = field(default_factory=list)
    tier: str = "unreviewed_ai_draft"

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class Rejection:
    """A proposal that failed a validator. Kept for the funnel — rejections
    are data about extraction quality, not garbage."""
    doc_id: str
    stage: str            # which validator killed it
    reasons: list[str]
    raw: dict[str, Any]   # the proposal as the model emitted it

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class Node:
    """Document tree node (document / section / paragraph / sentence)."""
    id: str
    type: str
    start: int
    end: int
    parent: str | None = None
    children: list[str] = field(default_factory=list)
    title: str | None = None      # sections only

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def coerce_enum(value: Any, allowed: frozenset[str], fallback: str,
                flags: list[str], flag_name: str) -> str:
    """Total: unknown enum values become the fallback plus a flag."""
    v = str(value).strip().lower() if value is not None else ""
    if v in allowed:
        return v
    flags.append(flag_name)
    return fallback


def coerce_hedge(value: Any, flags: list[str]) -> list[float]:
    """Total: any malformed hedge interval becomes [0.5, 0.9] + flag."""
    try:
        lo, hi = float(value[0]), float(value[1])
        lo = min(max(lo, 0.0), 1.0)
        hi = min(max(hi, 0.0), 1.0)
        if lo > hi:
            lo, hi = hi, lo
        return [round(lo, 3), round(hi, 3)]
    except Exception:
        flags.append("hedge_defaulted")
        return [0.5, 0.9]
