"""DISPOSE: deterministic, total validators over LLM proposals.

Every function returns (verdict, flags, reasons) and NEVER raises on any
input. Hard failures reject the proposal (it becomes a Rejection row —
funnel data, not silent loss). Soft findings become flags on the claim.

The checks, in order:
  1. shape/normalize    — text exists, capitalized, terminated
  2. fragment           — >= MIN_WORDS words
  3. deixis             — no unresolved anaphor opener (with pleonastic
                          "It is ... that/to" and existential "There is"
                          exceptions); soft-flag mid-text demonstratives
  4. atomicity          — no semicolon compounds; soft-flag ", and/but"
                          joins with two finite verbs
  5. quote alignment    — every quote must anchor in the window text
                          (exact -> normalized -> fuzzy sentence match)
  6. support            — numbers and proper names in the rewrite must
                          appear in source; content-token coverage floor

ONE deixis definition lives here. The old engine had two inconsistent ones.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

MIN_WORDS = 4
LONG_WORDS = 60
COVERAGE_REJECT = 0.50
COVERAGE_FLAG = 0.70
FUZZY_RATIO = 0.72

DEIXIS_OPENERS = frozenset({
    "it", "this", "that", "these", "those", "they", "he", "she",
    "there", "such", "their", "its", "which", "them", "his", "her",
    "here", "so",
})

_PLEONASTIC_IT = re.compile(
    r"^it\s+(is|was|seems|appears|remains|may\s+be|might\s+be|could\s+be|"
    r"becomes|would\s+be)\b.*\b(that|to|whether|how|why)\b", re.IGNORECASE)
_EXISTENTIAL_THERE = re.compile(
    r"^there\s+(is|are|was|were|exists?|remain|remains)\b", re.IGNORECASE)

_DEMONSTRATIVE_MID = re.compile(
    r"\b(this|these|those)\s+(approach|method|result|effect|process|idea|"
    r"view|claim|finding|work|paper|study|section|point|problem|projection|"
    r"argument|strategy|model)\b", re.IGNORECASE)

_FINITE = re.compile(
    r"\b(is|are|was|were|has|have|had|will|would|can|could|should|must|"
    r"may|might|does|do|did|shows|showed|found|argues|argued|suggests|"
    r"suggested|remains|causes|caused|leads|led|makes|made)\b", re.IGNORECASE)

_COORD_JOIN = re.compile(r",\s+(and|but)\s+", re.IGNORECASE)

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-']*")
_NUMBERISH = re.compile(r"\d[\d,.–\-%]*")

STOPWORDS = frozenset("""
a an the and or but if then than that this these those of in on at to for
with by from as is are was were be been being has have had will would can
could should must may might do does did not no nor it its they them their
he she his her we our you your i me my which who whom whose what when where
why how all any both each few more most other some such only own same so
too very just also into over under between about against during before
after above below up down out off again further once here there because
while although though since until unless
""".split())


@dataclass
class CheckResult:
    ok: bool
    flags: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def normalize_claim_text(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if not t:
        return t
    if t[0].islower():
        t = t[0].upper() + t[1:]
    if t[-1] not in ".!?":
        t += "."
    return t


def content_tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text or "")
            if w.lower() not in STOPWORDS and len(w) > 2]


def _tok_match(tok: str, source_toks: set[str]) -> bool:
    if tok in source_toks:
        return True
    if len(tok) >= 5:
        prefix = tok[:5]
        return any(s.startswith(prefix) or tok.startswith(s[:5])
                   for s in source_toks if len(s) >= 5)
    return False


def check_fragment(text: str) -> CheckResult:
    n = len(text.split())
    if n < MIN_WORDS:
        return CheckResult(False, reasons=[f"fragment_too_short:{n}_words"])
    flags = ["long_claim"] if n > LONG_WORDS else []
    return CheckResult(True, flags=flags)


def check_deixis(text: str) -> CheckResult:
    words = text.split()
    if not words:
        return CheckResult(False, reasons=["empty_text"])
    first = words[0].strip("\"'").lower().rstrip(",")
    if first in DEIXIS_OPENERS:
        if first == "it" and _PLEONASTIC_IT.match(text):
            pass
        elif first == "there" and _EXISTENTIAL_THERE.match(text):
            pass
        else:
            return CheckResult(False, reasons=[f"unresolved_deixis_opener:{first}"])
    flags = []
    if _DEMONSTRATIVE_MID.search(text):
        flags.append("demonstrative_reference")
    if re.search(r"\b(he|she)\b", text, re.IGNORECASE):
        flags.append("pronoun_present")
    return CheckResult(True, flags=flags)


def check_atomicity(text: str) -> CheckResult:
    if "; " in text:
        return CheckResult(False, reasons=["compound_semicolon"])
    flags = []
    m = _COORD_JOIN.search(text)
    if m:
        # a verb-ish token soon after ", and/but" suggests a second clause,
        # not a serial list ("A, B, and C")
        tail_words = text[m.end():].split()[:7]
        if any(_FINITE.match(w) or re.match(r"[a-z]+ed[.,;:]?$", w, re.IGNORECASE)
               for w in tail_words):
            flags.append("possibly_compound")
    return CheckResult(True, flags=flags)


def _norm_for_find(s: str) -> str:
    return re.sub(r"\s+", " ", s).casefold().strip(" \"'“”‘’")


def align_quotes(quotes: list[str], window_text: str,
                 window_offset: int) -> tuple[list[tuple[str, int, int]], CheckResult]:
    """Anchor each quote in the window. Returns (aligned, verdict) where
    aligned holds (quote, abs_start, abs_end) in document offsets."""
    aligned: list[tuple[str, int, int]] = []
    flags: list[str] = []
    if not quotes or not any(str(q).strip() for q in quotes):
        return [], CheckResult(False, reasons=["no_quotes"])

    norm_window = _norm_for_find(window_text)
    # map from normalized offsets back to raw offsets
    raw_positions: list[int] = []
    norm_chars: list[str] = []
    prev_space = False
    for i, ch in enumerate(window_text):
        c = ch.casefold()
        if c.isspace():
            if prev_space:
                continue
            c = " "
            prev_space = True
        else:
            prev_space = False
        norm_chars.append(c)
        raw_positions.append(i)
    norm_join = "".join(norm_chars)

    sentences = [s for s in re.split(r"(?<=[.!?])\s+", window_text) if s.strip()]

    for q in quotes:
        q = str(q).strip()
        if not q:
            continue
        idx = window_text.find(q)
        if idx != -1:
            aligned.append((q, window_offset + idx, window_offset + idx + len(q)))
            continue
        nq = _norm_for_find(q)
        nidx = norm_join.find(nq)
        if nq and nidx != -1:
            raw_start = raw_positions[nidx]
            raw_end = raw_positions[min(nidx + len(nq) - 1, len(raw_positions) - 1)] + 1
            aligned.append((window_text[raw_start:raw_end],
                            window_offset + raw_start, window_offset + raw_end))
            flags.append("quote_normalized_match")
            continue
        # fuzzy: closest sentence
        best, best_ratio = None, 0.0
        for s in sentences:
            r = difflib.SequenceMatcher(None, _norm_for_find(s), nq).ratio()
            if r > best_ratio:
                best, best_ratio = s, r
        if best is not None and best_ratio >= FUZZY_RATIO:
            idx = window_text.find(best)
            aligned.append((best, window_offset + idx, window_offset + idx + len(best)))
            flags.append("quote_fuzzy_match")
            continue
        return aligned, CheckResult(False, flags=flags,
                                    reasons=[f"quote_not_found:{q[:60]}"])
    if not aligned:
        return aligned, CheckResult(False, reasons=["no_quotes"])
    return aligned, CheckResult(True, flags=flags)


def check_support(claim_text: str, quotes_text: str, window_text: str,
                  context_text: str) -> CheckResult:
    """Numbers must appear in quotes+window; proper names in quotes+window+
    context; content coverage over the same pool."""
    flags: list[str] = []
    source = f"{quotes_text}\n{window_text}"
    source_plus = f"{source}\n{context_text}"
    src_norm = re.sub(r"[,\s]", "", source)

    for num in _NUMBERISH.findall(claim_text):
        clean = num.strip(".,%-–").replace(",", "")
        if not clean:
            continue
        if clean not in src_norm:
            return CheckResult(False, reasons=[f"unsupported_number:{num}"])

    words = claim_text.split()
    src_fold = source_plus.casefold()
    for i, w in enumerate(words):
        bare = w.strip("\"'().,;:!?")
        if i == 0 or not bare or not bare[0].isupper() or len(bare) < 3:
            continue
        if bare.lower() in STOPWORDS:
            continue
        if bare.casefold() not in src_fold:
            return CheckResult(False, reasons=[f"unsupported_name:{bare}"])

    ctoks = content_tokens(claim_text)
    if ctoks:
        pool = set(content_tokens(source_plus))
        covered = sum(1 for t in ctoks if _tok_match(t, pool))
        ratio = covered / len(ctoks)
        if ratio < COVERAGE_REJECT:
            return CheckResult(False, flags=flags,
                               reasons=[f"content_not_in_source:{ratio:.2f}"])
        if ratio < COVERAGE_FLAG:
            flags.append("low_source_overlap")
    return CheckResult(True, flags=flags)
