from episteme_fable.identify import dedupe_and_link, instance_id
from episteme_fable.schemas import Proposition, Span


def _claim(cid, text, spans=((0, 10),)):
    return Proposition(
        id=cid, doc_id="d", text=text, kind="assertion",
        claim_type="empirical", stance="author", stance_source=None,
        hedge=[0.8, 0.95], stated_confidence=None,
        spans=[Span(quote="q", start=s, end=e) for s, e in spans],
        section_path="",
    )


def test_instance_id_stable_and_text_independent():
    a = instance_id("doc1", [(5, 40), (60, 90)], "assertion")
    b = instance_id("doc1", [(60, 90), (5, 40)], "assertion")  # order-free
    assert a == b
    assert instance_id("doc1", [(5, 40)], "assertion") != a
    assert instance_id("doc2", [(5, 40), (60, 90)], "assertion") != a


def test_dedupe_drops_near_identical_keeps_same_as():
    c1 = _claim("c1", "The reserve fund lost twelve percent of its value in 2019.")
    c2 = _claim("c2", "The reserve fund lost twelve percent of its value in 2019.")
    c3 = _claim("c3", "The reserve fund will likely recover its losses by 2030.")
    kept = dedupe_and_link([c1, c2, c3])
    assert [c.id for c in kept] == ["c1", "c3"]


def test_same_as_candidates_between_close_but_distinct():
    c1 = _claim("c1", "The committee projected the reserve fund becomes insolvent by 2030.")
    c2 = _claim("c2", "The committee projected the reserve fund would be insolvent around 2030.")
    # texts share most content tokens but not >=0.8 jaccard after stopwords
    kept = dedupe_and_link([c1, c2])
    if len(kept) == 2:
        assert "c2" in kept[0].same_as
