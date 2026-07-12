"""Windows: the unit the PROPOSE pass sees.

A window is 1-N consecutive paragraphs from one section, capped by size,
plus everything the model needs to write self-contained rewrites:
document title, section path, the tail of the previous window (so
antecedents crossing the window boundary stay resolvable), and a rolling
glossary of proper-noun candidates seen so far in the document.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .segment import DocTree

WINDOW_CHAR_CAP = 1600

_CAP_TOKEN = re.compile(r"\b[A-Z][A-Za-z0-9\-]{2,}(?:\s+[A-Z][A-Za-z0-9\-]{2,})*\b")
_STOP_CAPS = frozenset({
    "The", "This", "That", "These", "Those", "But", "And", "However",
    "It", "They", "We", "He", "She", "In", "On", "At", "For", "With",
    "When", "While", "Although", "If", "As", "Our", "Their", "There",
    "First", "Second", "Third", "Finally", "Moreover", "Thus", "Therefore",
})


@dataclass
class Window:
    index: int
    section_path: str
    start: int          # offset of window text in document text
    text: str
    prev_tail: str
    glossary: list[str] = field(default_factory=list)


def _glossary_from(text: str, seen: dict[str, int]) -> None:
    for m in _CAP_TOKEN.finditer(text):
        tok = m.group(0)
        # drop leading sentence-initial stopwords like "The Model" -> "Model"
        parts = [p for p in tok.split() if p not in _STOP_CAPS]
        if not parts:
            continue
        cleaned = " ".join(parts)
        if len(cleaned) < 3:
            continue
        seen[cleaned] = seen.get(cleaned, 0) + 1


def build_windows(tree: DocTree, cap: int = WINDOW_CHAR_CAP) -> list[Window]:
    windows: list[Window] = []
    glossary_counts: dict[str, int] = {}
    prev_tail = ""

    paragraphs = tree.paragraphs()
    i = 0
    w_index = 0
    while i < len(paragraphs):
        sec = tree.section_path(paragraphs[i].id)
        start = paragraphs[i].start
        end = paragraphs[i].end
        j = i + 1
        while (j < len(paragraphs)
               and tree.section_path(paragraphs[j].id) == sec
               and paragraphs[j].end - start <= cap):
            end = paragraphs[j].end
            j += 1

        text = tree.text[start:end]
        top = sorted(glossary_counts.items(), key=lambda kv: -kv[1])[:25]
        windows.append(Window(
            index=w_index, section_path=sec, start=start, text=text,
            prev_tail=prev_tail, glossary=[k for k, _ in top],
        ))
        _glossary_from(text, glossary_counts)
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        prev_tail = " ".join(sentences[-2:]) if sentences else ""
        w_index += 1
        i = j
    return windows
