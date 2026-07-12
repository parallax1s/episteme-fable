"""Render the pyramid as human-readable markdown."""
from __future__ import annotations

from .pipeline import Artifact

_STANCE_MARK = {"author": "", "reported": " (reported: {src})",
                "hypothetical": " (hypothetical)", "refuted": " (REFUTED by source)"}


def render(art: Artifact) -> str:
    lines: list[str] = []
    lines.append(f"# {art.title or art.doc_id}")
    lines.append("")
    lines.append(f"`{art.doc_id}` · engine {art.stats.get('engine_version')} · "
                 f"prompt {art.stats.get('prompt_version')}")
    lines.append("")

    if art.theses:
        lines.append("## Theses // Kernaussagen")
        lines.append("")
        for t in art.theses:
            flag = f"  ⚑ {', '.join(t.flags)}" if t.flags else ""
            lines.append(f"- **{t.text}**{flag}")
            refs = t.point_ids + t.claim_ids
            lines.append(f"  - support: {', '.join(refs)}")
        lines.append("")

    if art.points:
        lines.append("## Points // per section")
        lines.append("")
        for p in art.points:
            sec = p.section_path or "(root)"
            flag = f"  ⚑ {', '.join(p.flags)}" if p.flags else ""
            lines.append(f"- `{p.id}` [{sec}] {p.text}{flag}")
            lines.append(f"  - claims: {', '.join(p.claim_ids)}")
        lines.append("")

    lines.append(f"## Claims // Aussagen ({len(art.claims)})")
    lines.append("")
    for c in art.claims:
        stance = _STANCE_MARK.get(c.stance, "")
        if "{src}" in stance:
            stance = stance.format(src=c.stance_source or "?")
        hedge = f"[{c.hedge[0]:.2f}-{c.hedge[1]:.2f}]"
        ct = c.claim_type or c.kind
        flags = f" ⚑{','.join(c.flags)}" if c.flags else ""
        lines.append(f"- `{c.id}` **{ct}** {hedge}{stance}{flags}")
        lines.append(f"  {c.text}")
        for sp in c.spans:
            q = sp.quote if len(sp.quote) <= 140 else sp.quote[:137] + "..."
            lines.append(f"  > {q}")
    lines.append("")

    s = art.stats
    lines.append("## Funnel")
    lines.append("")
    lines.append(f"- windows: {s.get('windows')} · proposals: {s.get('proposals')} · "
                 f"accepted: {s.get('accepted')} · rejected: {s.get('rejected')}")
    if s.get("rejected_by_stage"):
        parts = [f"{k}: {v}" for k, v in sorted(s["rejected_by_stage"].items())]
        lines.append(f"- rejections by stage: {', '.join(parts)}")
    if s.get("window_errors"):
        lines.append(f"- window errors: {len(s['window_errors'])}")
    lines.append("")
    return "\n".join(lines)
