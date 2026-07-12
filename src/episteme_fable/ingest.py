"""Normalization: markdown/plain text -> clean prose with paragraph breaks.

Keeps: paragraph structure (blank lines), markdown headings (as `# ...` lines),
citation markers like [1]. Strips: code fences, inline code, emphasis, links
(keeping link text), images, HTML tags. Deterministic, no deps.
"""
from __future__ import annotations

import re

_CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_REF_LINK = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_EMPHASIS = re.compile(r"(\*\*\*|\*\*|\*|___|__|_)(?=\S)(.+?)(?<=\S)\1")
_BLOCKQUOTE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_LIST_MARKER = re.compile(r"^\s{0,6}(?:[-*+]|\d{1,3}[.)])\s+", re.MULTILINE)
_MULTISPACE = re.compile(r"[ \t]+")
_MANY_BLANKS = re.compile(r"\n{3,}")


def normalize(text: str) -> str:
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = _CODE_FENCE.sub(" ", t)
    t = _IMAGE.sub(" ", t)
    t = _LINK.sub(r"\1", t)
    t = _REF_LINK.sub(r"\1", t)
    t = _INLINE_CODE.sub(r"\1", t)
    t = _HTML_TAG.sub(" ", t)
    # emphasis markers can nest; two passes cover ***bold italic***
    t = _EMPHASIS.sub(r"\2", t)
    t = _EMPHASIS.sub(r"\2", t)
    t = _BLOCKQUOTE.sub("", t)
    t = _LIST_MARKER.sub("", t)
    t = _MULTISPACE.sub(" ", t)
    t = "\n".join(line.strip() for line in t.split("\n"))
    # give headings their own blocks so soft-wrap unwrapping can't swallow them
    t = re.sub(r"\n(#{1,6} [^\n]*)", r"\n\n\1\n\n", "\n" + t)
    t = _MANY_BLANKS.sub("\n\n", t)
    # unwrap soft line breaks: a single newline inside a block is a space
    t = re.sub(r"(?<!\n)\n(?!\n)", " ", t)
    t = _MULTISPACE.sub(" ", t)
    return t.strip()
