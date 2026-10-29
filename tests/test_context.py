from episteme_fable.context import build_windows
from episteme_fable.segment import segment


def test_build_windows_hard_caps_oversized_paragraphs() -> None:
    sentence = "A deliberately long sentence contains many repeated words " * 8 + "."
    text = sentence + " " + sentence + " " + sentence
    tree = segment(text, title="Long")

    windows = build_windows(tree, cap=120)

    assert len(windows) > 3
    assert all(len(window.text) <= 120 for window in windows)
    assert all(tree.text[w.start:w.start + len(w.text)] == w.text for w in windows)
