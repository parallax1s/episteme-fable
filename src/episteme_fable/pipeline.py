"""The orchestrator: SEGMENT -> PROPOSE -> DISPOSE -> IDENTIFY -> ASSEMBLE.

analyze() returns an Artifact holding everything, including the rejection
funnel — the funnel is a first-class output, because rejected proposals
measure extraction quality run over run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import ENGINE_VERSION
from .assemble import synthesize_points, synthesize_theses
from .context import build_windows
from .identify import dedupe_and_link, instance_id
from .ingest import normalize
from .propose import PROMPT_VERSION, RawProposal, load_prompt_template, propose_window
from .schemas import Point, Proposition, Rejection, Span, Thesis
from .segment import DocTree, segment
from .validate import (align_quotes, check_atomicity, check_deixis,
                       check_fragment, check_support, normalize_claim_text)


@dataclass
class Artifact:
    doc_id: str
    title: str
    tree: DocTree
    claims: list[Proposition] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    points: list[Point] = field(default_factory=list)
    theses: list[Thesis] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def dispose(p: RawProposal, doc_id: str, tree: DocTree,
            prompt_version: str) -> Proposition | Rejection:
    """Run one proposal through every validator. Total."""
    text = normalize_claim_text(p.text)
    raw_dict = {"text": p.text, "quotes": p.quotes, "kind": p.kind,
                "stance": p.stance, "window": p.window.index}

    for stage, check in (("fragment", check_fragment),
                         ("deixis", check_deixis),
                         ("atomicity", check_atomicity)):
        res = check(text)
        if not res.ok:
            return Rejection(doc_id=doc_id, stage=stage,
                             reasons=res.reasons, raw=raw_dict)
        p.coerce_flags.extend(res.flags)

    aligned, ares = align_quotes(p.quotes, p.window.text, p.window.start)
    if not ares.ok:
        return Rejection(doc_id=doc_id, stage="alignment",
                         reasons=ares.reasons, raw=raw_dict)
    p.coerce_flags.extend(ares.flags)

    quotes_text = "\n".join(q for q, _, _ in aligned)
    context_text = f"{p.window.prev_tail}\n{' '.join(p.window.glossary)}\n" \
                   f"{tree.nodes['d0'].title or ''}"
    sres = check_support(text, quotes_text, p.window.text, context_text)
    if not sres.ok:
        return Rejection(doc_id=doc_id, stage="support",
                         reasons=sres.reasons, raw=raw_dict)
    p.coerce_flags.extend(sres.flags)

    spans = [Span(quote=q, start=s, end=e,
                  sent_ids=tree.sentences_overlapping(s, e))
             for q, s, e in aligned]
    cid = instance_id(doc_id, [(sp.start, sp.end) for sp in spans], p.kind)
    return Proposition(
        id=cid, doc_id=doc_id, text=text, kind=p.kind,
        claim_type=p.claim_type, stance=p.stance,
        stance_source=p.stance_source, hedge=p.hedge,
        stated_confidence=p.stated_confidence, spans=spans,
        section_path=p.window.section_path,
        implicit_premises=p.implicit_premises,
        flags=sorted(set(p.coerce_flags)),
        tier="validated", prompt_version=prompt_version,
        engine_version=ENGINE_VERSION,
    )


def analyze(raw_text: str, doc_id: str, title: str, provider,
            model: str | None = None, assemble_model: str | None = None,
            do_assemble: bool = True, on_progress=None) -> Artifact:
    text = normalize(raw_text)
    tree = segment(text, title=title)
    windows = build_windows(tree)
    template = load_prompt_template()

    art = Artifact(doc_id=doc_id, title=title, tree=tree)
    window_errors: list[str] = []
    n_proposals = 0

    for w in windows:
        if on_progress:
            on_progress(f"window {w.index + 1}/{len(windows)}")
        proposals, err = propose_window(provider, template, w, title, model=model)
        if err:
            window_errors.append(err)
            continue
        n_proposals += len(proposals)
        for p in proposals:
            result = dispose(p, doc_id, tree, PROMPT_VERSION)
            if isinstance(result, Proposition):
                art.claims.append(result)
            else:
                art.rejections.append(result)

    art.claims = dedupe_and_link(art.claims)

    if do_assemble and art.claims:
        if on_progress:
            on_progress("assembling points")
        art.points = synthesize_points(provider, doc_id, title, art.claims,
                                       model=assemble_model)
        if on_progress:
            on_progress("assembling theses")
        art.theses = synthesize_theses(provider, doc_id, title, art.points,
                                       art.claims, model=assemble_model)

    reject_reasons: dict[str, int] = {}
    for r in art.rejections:
        reject_reasons[r.stage] = reject_reasons.get(r.stage, 0) + 1
    art.stats = {
        "windows": len(windows),
        "window_errors": window_errors,
        "proposals": n_proposals,
        "accepted": len(art.claims),
        "rejected": len(art.rejections),
        "rejected_by_stage": reject_reasons,
        "points": len(art.points),
        "theses": len(art.theses),
        "engine_version": ENGINE_VERSION,
        "prompt_version": PROMPT_VERSION,
    }
    return art
