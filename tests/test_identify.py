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


def test_negated_claim_is_not_collapsed_into_its_assertion():
    pos = _claim("c1", "Ketamine increases synaptic density in the prefrontal cortex.", spans=((0, 60),))
    neg = _claim("c2", "Ketamine does not increase synaptic density in the prefrontal cortex.", spans=((70, 140),))
    kept = dedupe_and_link([pos, neg])
    assert [c.id for c in kept] == ["c1", "c2"]
    assert kept[0].same_as == [] and kept[1].same_as == []


def test_different_numbers_are_not_duplicates():
    a = _claim("c1", "The reserve fund lost 12 percent of its value in 2019.", spans=((0, 50),))
    b = _claim("c2", "The reserve fund lost 20 percent of its value in 2019.", spans=((60, 110),))
    assert len(dedupe_and_link([a, b])) == 2


def test_distinct_claims_on_same_span_keep_distinct_ids_order_free():
    def run(order):
        cid = instance_id("d", [(0, 120)], "assertion")
        a = _claim(cid, "Astrocytes buffer extracellular potassium during seizures.", spans=((0, 120),))
        b = _claim(cid, "Neuronal sodium overload precedes calcium deregulation.", spans=((0, 120),))
        items = [a, b] if order else [b, a]
        return {c.text: c.id for c in dedupe_and_link(items)}
    first, second = run(True), run(False)
    assert len(first) == 2 and len(set(first.values())) == 2
    assert first == second
    base = instance_id("d", [(0, 120)], "assertion")
    assert all(v.startswith(base + "-") for v in first.values())


def test_true_duplicates_on_same_span_still_dedupe_and_keep_base_id():
    cid = instance_id("d", [(0, 50)], "assertion")
    a = _claim(cid, "The reserve fund lost twelve percent of its value in 2019.", spans=((0, 50),))
    b = _claim(cid, "The reserve fund lost twelve percent of its value in 2019.", spans=((0, 50),))
    kept = dedupe_and_link([a, b])
    assert [c.id for c in kept] == [cid]


def test_uncollided_ids_are_unchanged():
    a = _claim("c1", "Soil carbon saturates under long-term nitrogen addition.", spans=((0, 40),))
    assert dedupe_and_link([a])[0].id == "c1"
