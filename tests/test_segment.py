from episteme_fable.ingest import normalize
from episteme_fable.segment import segment, split_sentences


def test_sentence_offsets_index_into_text():
    text = "Dr. Smith arrived. He sat down. The meeting began at 3 p.m. sharp."
    spans = split_sentences(text)
    assert [text[s:e] for s, e in spans] == [
        "Dr. Smith arrived.", "He sat down.",
        "The meeting began at 3 p.m. sharp.",
    ]


def test_abbreviations_do_not_split():
    text = "See Fig. 2 for details. The effect (e.g. drift) is small."
    spans = split_sentences(text)
    assert len(spans) == 2


def test_tree_sections_and_paragraphs():
    raw = "# Title\n\nFirst para. Two sentences here.\n\n## Part A\n\nSecond para."
    text = normalize(raw)
    tree = segment(text, title="Doc")
    secs = [n for i in tree.order if (n := tree.nodes[i]).type == "section"]
    paras = tree.paragraphs()
    assert len(paras) == 2
    # root section + two heading sections
    assert len(secs) == 3
    assert tree.section_path(paras[1].id).endswith("Part A")
    # every sentence's offsets slice cleanly out of the text
    for s in tree.sentences():
        assert tree.text[s.start:s.end].strip() == tree.text[s.start:s.end]


def test_normalize_strips_markdown():
    raw = "Some **bold** and a [link](http://x.y) and `code`.\n\n```\nskip me\n```\n\nEnd."
    t = normalize(raw)
    assert "**" not in t and "](" not in t and "`" not in t
    assert "skip me" not in t
    assert "link" in t
