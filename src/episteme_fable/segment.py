"""Document tree: document -> sections -> paragraphs -> sentences.

Offsets index into the normalized text (the same string every Span in the
claim layer points at). Sections come from markdown headings only — no
guessing. Sentence splitting is regex + abbreviation guard; a redesign
principle is that sentence boundaries no longer determine claim boundaries,
so this splitter only has to be good enough for span bookkeeping.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .schemas import Node

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

_ABBREVIATIONS = (
    "dr.", "mr.", "mrs.", "ms.", "prof.", "sr.", "jr.", "st.",
    "fig.", "figs.", "eq.", "eqs.", "sec.", "ch.", "vol.", "no.", "pp.",
    "e.g.", "i.e.", "et al.", "etc.", "vs.", "cf.", "ca.", "approx.",
    "u.s.", "u.k.", "a.m.", "p.m.",
    "z.b.", "d.h.", "bzw.", "usw.", "nr.", "vgl.", "u.a.",
)

_SENT_END = re.compile(r"([.!?][\"')\]]*)\s+(?=[\"'(\[]*[A-Z0-9])")


@dataclass
class DocTree:
    text: str
    nodes: dict[str, Node] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)

    def add(self, node: Node) -> None:
        self.nodes[node.id] = node
        self.order.append(node.id)
        if node.parent and node.parent in self.nodes:
            self.nodes[node.parent].children.append(node.id)

    def sentences(self) -> list[Node]:
        return [self.nodes[i] for i in self.order if self.nodes[i].type == "sentence"]

    def paragraphs(self) -> list[Node]:
        return [self.nodes[i] for i in self.order if self.nodes[i].type == "paragraph"]

    def section_path(self, node_id: str) -> str:
        titles: list[str] = []
        cur = self.nodes.get(node_id)
        while cur is not None:
            if cur.type == "section" and cur.title:
                titles.append(cur.title)
            cur = self.nodes.get(cur.parent) if cur.parent else None
        return " > ".join(reversed(titles))

    def sentences_overlapping(self, start: int, end: int) -> list[str]:
        return [n.id for n in self.sentences() if n.start < end and n.end > start]


def _ends_with_abbreviation(chunk: str) -> bool:
    tail = chunk.rstrip().lower()
    for abbr in _ABBREVIATIONS:
        if tail.endswith(abbr):
            return True
    # single initial like "J." or "A."
    if re.search(r"\b[a-z]\.$", tail):
        return True
    return False


def split_sentences(text: str, offset: int = 0) -> list[tuple[int, int]]:
    """Return (start, end) offsets of sentences within text, shifted by offset."""
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _SENT_END.finditer(text):
        end = m.end(1)
        if _ends_with_abbreviation(text[start:end]):
            continue
        seg = text[start:end].strip()
        if seg:
            s = start + (len(text[start:end]) - len(text[start:end].lstrip()))
            spans.append((offset + s, offset + end))
        start = m.end()
    tail = text[start:].strip()
    if tail:
        s = start + (len(text[start:]) - len(text[start:].lstrip()))
        spans.append((offset + s, offset + s + len(tail)))
    return spans


def segment(text: str, title: str | None = None) -> DocTree:
    """Build the tree over normalized text."""
    tree = DocTree(text=text)
    doc = Node(id="d0", type="document", start=0, end=len(text), title=title)
    tree.add(doc)

    # implicit root section so every paragraph has a section parent
    root_sec = Node(id="s0", type="section", start=0, end=len(text),
                    parent="d0", title=title or "")
    tree.add(root_sec)

    sec_count, par_count, sent_count = 1, 0, 0
    current_sec = root_sec

    pos = 0
    for block in text.split("\n\n"):
        b_start = text.index(block, pos) if block else pos
        pos = b_start + len(block)
        stripped = block.strip()
        if not stripped:
            continue

        hm = _HEADING.match(stripped.split("\n")[0])
        if hm and len(stripped.split("\n")) == 1:
            current_sec = Node(id=f"s{sec_count}", type="section",
                               start=b_start, end=len(text), parent="d0",
                               title=hm.group(2).strip())
            tree.add(current_sec)
            sec_count += 1
            continue

        par = Node(id=f"p{par_count}", type="paragraph",
                   start=b_start, end=b_start + len(block),
                   parent=current_sec.id)
        tree.add(par)
        par_count += 1

        for s, e in split_sentences(text[b_start:b_start + len(block)], b_start):
            sent = Node(id=f"t{sent_count}", type="sentence",
                        start=s, end=e, parent=par.id)
            tree.add(sent)
            sent_count += 1

    # close section extents
    secs = [tree.nodes[i] for i in tree.order if tree.nodes[i].type == "section"]
    for i, s in enumerate(secs):
        if i + 1 < len(secs):
            s.end = secs[i + 1].start
    return tree
