"""PROPOSE: one LLM call per window -> raw proposals.

The model's output is treated as untrusted: extract_json is total, every
field goes through a coercer, and a single repair round re-asks when the
response wasn't parseable JSON at all. Nothing here decides whether a
proposal is a good claim — that is DISPOSE's job (validate.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .context import Window
from .providers import extract_json
from .schemas import CLAIM_TYPES, KINDS, STANCES, coerce_enum, coerce_hedge

PROMPT_VERSION = "propose_v2"
_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "propose_v2.md"

REPAIR_SUFFIX = (
    "\n\nYour previous reply was not parseable JSON. Reply again with ONLY "
    "the JSON array described above — no prose, no markdown fences."
)


@dataclass
class RawProposal:
    window: Window
    text: str
    quotes: list[str]
    kind: str
    claim_type: str | None
    stance: str
    stance_source: str | None
    hedge: list[float]
    stated_confidence: float | None
    implicit_premises: list[str]
    coerce_flags: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


def load_prompt_template(path: Path | None = None) -> str:
    return (path or _PROMPT_PATH).read_text(encoding="utf-8")


def render_prompt(template: str, window: Window, doc_title: str) -> str:
    return (template
            .replace("{DOC_TITLE}", doc_title or "(untitled)")
            .replace("{SECTION_PATH}", window.section_path or "(document root)")
            .replace("{GLOSSARY}", ", ".join(window.glossary) or "(none yet)")
            .replace("{PREV_TAIL}", window.prev_tail or "(document start)")
            .replace("{WINDOW_TEXT}", window.text))


def coerce_proposal(item: Any, window: Window) -> RawProposal | None:
    """Total: any dict becomes a RawProposal; non-dicts return None."""
    if not isinstance(item, dict):
        return None
    flags: list[str] = []
    text = str(item.get("text") or "").strip()
    quotes_raw = item.get("quotes")
    quotes = [str(q) for q in quotes_raw if str(q).strip()] \
        if isinstance(quotes_raw, list) else []

    kind = coerce_enum(item.get("kind"), KINDS, "assertion", flags, "kind_defaulted")
    ct_raw = item.get("claim_type")
    claim_type: str | None
    if kind in ("assertion", "inference"):
        claim_type = coerce_enum(ct_raw, CLAIM_TYPES, "descriptive",
                                 flags, "claim_type_defaulted")
    else:
        claim_type = str(ct_raw).lower() if ct_raw in CLAIM_TYPES else None

    stance = coerce_enum(item.get("stance"), STANCES, "author",
                         flags, "stance_defaulted")
    src = item.get("stance_source")
    stance_source = str(src).strip() if src else None
    if stance == "reported" and not stance_source:
        flags.append("reported_without_source")

    hedge = coerce_hedge(item.get("hedge"), flags)
    sc = item.get("stated_confidence")
    try:
        stated_confidence = None if sc is None else min(max(float(sc), 0.0), 1.0)
    except (TypeError, ValueError):
        stated_confidence = None
        flags.append("stated_confidence_dropped")

    prem = item.get("implicit_premises")
    implicit = [str(p) for p in prem][:5] if isinstance(prem, list) else []

    return RawProposal(
        window=window, text=text, quotes=quotes, kind=kind,
        claim_type=claim_type, stance=stance, stance_source=stance_source,
        hedge=hedge, stated_confidence=stated_confidence,
        implicit_premises=implicit, coerce_flags=flags, raw=item,
    )


def propose_window(provider, template: str, window: Window,
                   doc_title: str, model: str | None = None
                   ) -> tuple[list[RawProposal], str | None]:
    """Returns (proposals, error). error is set when even the repair round
    produced no JSON — the window is then skipped, not fatal."""
    prompt = render_prompt(template, window, doc_title)
    reply = provider.complete(prompt, model=model)
    data, err = extract_json(reply)
    if err is not None:
        reply = provider.complete(prompt + REPAIR_SUFFIX, model=model)
        data, err = extract_json(reply)
        if err is not None:
            return [], f"window {window.index}: {err}"
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return [], f"window {window.index}: JSON was not a list"
    proposals = []
    for item in data:
        p = coerce_proposal(item, window)
        if p is not None:
            proposals.append(p)
    return proposals, None
