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


def _paragraph_pieces(tree: DocTree, paragraph, cap: int) -> list[tuple[int, int, str]]:
    """Split a paragraph into source-aligned pieces no longer than ``cap``.

    Prefer sentence ends. A single sentence longer than the cap falls back to
    whitespace (and finally an exact character boundary), so the cap remains
    hard even for unusually long unbroken paragraphs.
    """
    section = tree.section_path(paragraph.id)
    sentence_ends = [n.end for n in tree.sentences() if n.parent == paragraph.id]
    pieces: list[tuple[int, int, str]] = []
    start = paragraph.start
    while start < paragraph.end:
        while start < paragraph.end and tree.text[start].isspace():
            start += 1
        if start >= paragraph.end:
            break
        limit = min(start + cap, paragraph.end)
        end = limit
        if limit < paragraph.end:
            candidates = [e for e in sentence_ends if start < e <= limit]
            if candidates:
                end = max(candidates)
            else:
                floor = min(limit, start + max(1, cap // 2))
                whitespace = tree.text.rfind(" ", floor, limit + 1)
                if whitespace > start:
                    end = whitespace
        while end > start and tree.text[end - 1].isspace():
            end -= 1
        if end <= start:
            end = min(start + cap, paragraph.end)
        pieces.append((start, end, section))
        start = end
    return pieces


def build_windows(tree: DocTree, cap: int = WINDOW_CHAR_CAP) -> list[Window]:
    if cap <= 0:
        raise ValueError("window cap must be positive")
    windows: list[Window] = []
    glossary_counts: dict[str, int] = {}
    prev_tail = ""

    pieces = [piece for paragraph in tree.paragraphs()
              for piece in _paragraph_pieces(tree, paragraph, cap)]
    i = 0
    w_index = 0
    while i < len(pieces):
        start, end, sec = pieces[i]
        j = i + 1
        while (j < len(pieces)
               and pieces[j][2] == sec
               and pieces[j][1] - start <= cap):
            end = pieces[j][1]
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
