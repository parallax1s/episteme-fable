"""ASSEMBLE: the top of the pyramid — L2 points and L3 theses.

Synthesis with index-provenance: the model must cite the numbered inputs it
used, and deterministic checks verify the citations exist and the synthesized
text is grounded in the cited material (token coverage). Synthesized rows are
tier=unreviewed_ai_draft — they are proposals about structure, not validated
extractions, and the tier says so.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .providers import extract_json
from .schemas import Point, Proposition, Thesis
from .validate import check_deixis, content_tokens, normalize_claim_text, _tok_match

_PROMPTS = Path(__file__).resolve().parent.parent.parent / "prompts"
POINT_PROMPT_VERSION = "point_v1"
THESIS_PROMPT_VERSION = "thesis_v1"

POINT_GROUNDING_FLOOR = 0.4
MIN_CLAIMS_FOR_POINT = 2
MAX_THESES = 4


def _load(name: str) -> str:
    return (_PROMPTS / name).read_text(encoding="utf-8")


def _numbered(texts: list[str]) -> str:
    return "\n".join(f"[{i + 1}] {t}" for i, t in enumerate(texts))


def _grounding(text: str, cited_texts: list[str]) -> float:
    toks = content_tokens(text)
    if not toks:
        return 0.0
    pool = set()
    for t in cited_texts:
        pool.update(content_tokens(t))
    return sum(1 for t in toks if _tok_match(t, pool)) / len(toks)


def _valid_cites(cites, upper: int) -> list[int]:
    out = []
    if isinstance(cites, list):
        for c in cites:
            try:
                i = int(c)
            except (TypeError, ValueError):
                continue
            if 1 <= i <= upper and i not in out:
                out.append(i)
    return out


def synthesize_points(provider, doc_id: str, doc_title: str,
                      claims: list[Proposition], model: str | None = None
                      ) -> list[Point]:
    """One point per section that has enough claims."""
    by_section: dict[str, list[Proposition]] = {}
    for c in claims:
        by_section.setdefault(c.section_path, []).append(c)

    template = _load("point_v1.md")
    points: list[Point] = []
    for sec, sec_claims in by_section.items():
        if len(sec_claims) < MIN_CLAIMS_FOR_POINT:
            continue
        prompt = (template
                  .replace("{DOC_TITLE}", doc_title or "(untitled)")
                  .replace("{SECTION_PATH}", sec or "(document root)")
                  .replace("{NUMBERED_CLAIMS}",
                           _numbered([c.text for c in sec_claims])))
        try:
            reply = provider.complete(prompt, model=model)
        except Exception:
            continue
        data, err = extract_json(reply)
        if err or not isinstance(data, dict):
            continue
        text = normalize_claim_text(str(data.get("text") or ""))
        cites = _valid_cites(data.get("cites"), len(sec_claims))
        if not text or not cites:
            continue
        flags = []
        if data.get("no_unifying_point"):
            flags.append("no_unifying_point")
        cited = [sec_claims[i - 1] for i in cites]
        if _grounding(text, [c.text for c in cited]) < POINT_GROUNDING_FLOOR:
            flags.append("point_low_grounding")
        dx = check_deixis(text)
        if not dx.ok:
            flags.append("point_deixis")
        flags.extend(dx.flags)
        pid = "pt" + hashlib.sha1(
            f"{doc_id}|{sec}|{sorted(c.id for c in cited)}".encode()).hexdigest()[:8]
        points.append(Point(id=pid, doc_id=doc_id, section_path=sec,
                            text=text, claim_ids=[c.id for c in cited],
                            flags=flags))
    return points


def synthesize_theses(provider, doc_id: str, doc_title: str,
                      points: list[Point], claims: list[Proposition],
                      model: str | None = None) -> list[Thesis]:
    """Theses cite points where they exist, top claims otherwise."""
    # material = points, plus claims from sections without a point
    covered = {p.section_path for p in points}
    loose = [c for c in claims if c.section_path not in covered]
    material: list[tuple[str, str, str]] = []  # (ref_type, ref_id, text)
    for p in points:
        material.append(("point", p.id, p.text))
    for c in loose[:20]:
        material.append(("claim", c.id, c.text))
    if not material:
        return []

    template = _load("thesis_v1.md")
    prompt = (template
              .replace("{DOC_TITLE}", doc_title or "(untitled)")
              .replace("{NUMBERED_ITEMS}",
                       _numbered([m[2] for m in material])))
    try:
        reply = provider.complete(prompt, model=model)
    except Exception:
        return []
    data, err = extract_json(reply)
    if err:
        return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []

    theses: list[Thesis] = []
    for item in data[:MAX_THESES]:
        if not isinstance(item, dict):
            continue
        text = normalize_claim_text(str(item.get("text") or ""))
        cites = _valid_cites(item.get("cites"), len(material))
        if not text or not cites:
            continue
        cited = [material[i - 1] for i in cites]
        flags = []
        if _grounding(text, [m[2] for m in cited]) < POINT_GROUNDING_FLOOR:
            flags.append("thesis_low_grounding")
        dx = check_deixis(text)
        if not dx.ok:
            flags.append("thesis_deixis")
        flags.extend(dx.flags)
        tid = "th" + hashlib.sha1(
            f"{doc_id}|{text}".encode()).hexdigest()[:8]
        theses.append(Thesis(
            id=tid, doc_id=doc_id, text=text,
            point_ids=[r for t, r, _ in cited if t == "point"],
            claim_ids=[r for t, r, _ in cited if t == "claim"],
            flags=flags))
    return theses
