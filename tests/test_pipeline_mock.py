"""E2E over the full pipeline with a MockProvider — no network, no LLM."""
import json

from episteme_fable.pipeline import analyze
from episteme_fable.providers import MockProvider
from episteme_fable.report import render

DOC = """# Fund Review

The reserve fund lost 12% of its value in 2019. According to Dr. Reyes, \
the losses were caused by currency exposure. If the losses continue, the \
fund will be insolvent by 2030.

## Outlook

The committee believes the projection is too pessimistic. It expects \
a partial recovery."""


def _propose_reply_1():
    return json.dumps([
        {"text": "The reserve fund lost 12% of its value in 2019.",
         "quotes": ["The reserve fund lost 12% of its value in 2019."],
         "kind": "assertion", "claim_type": "statistical", "stance": "author",
         "stance_source": None, "hedge": [0.85, 0.98],
         "stated_confidence": None, "implicit_premises": []},
        {"text": "The reserve fund's losses were caused by currency exposure.",
         "quotes": ["According to Dr. Reyes, the losses were caused by currency exposure."],
         "kind": "assertion", "claim_type": "causal", "stance": "reported",
         "stance_source": "Dr. Reyes", "hedge": [0.7, 0.9],
         "stated_confidence": None, "implicit_premises": []},
        # bad one: unresolved pronoun opener -> must be rejected at deixis
        {"text": "It will be insolvent by 2030.",
         "quotes": ["the fund will be insolvent by 2030"],
         "kind": "assertion", "claim_type": "predictive", "stance": "author",
         "stance_source": None, "hedge": [0.6, 0.8],
         "stated_confidence": None, "implicit_premises": []},
        # bad one: number not in source -> must be rejected at support
        {"text": "The reserve fund lost 15% of its value in 2019.",
         "quotes": ["The reserve fund lost 12% of its value in 2019."],
         "kind": "assertion", "claim_type": "statistical", "stance": "author",
         "stance_source": None, "hedge": [0.85, 0.98],
         "stated_confidence": None, "implicit_premises": []},
    ])


def _propose_reply_2():
    return json.dumps([
        {"text": "The committee believes the insolvency projection is too pessimistic.",
         "quotes": ["The committee believes the projection is too pessimistic."],
         "kind": "assertion", "claim_type": "evaluative", "stance": "author",
         "stance_source": None, "hedge": [0.6, 0.85],
         "stated_confidence": None, "implicit_premises": []},
    ])


def _point_reply():
    return json.dumps({"text": "The reserve fund suffered losses that threaten "
                               "its solvency.", "cites": [1, 2]})


def _thesis_reply():
    return json.dumps([{"text": "The reserve fund faces a solvency risk that "
                                "the committee disputes.", "cites": [1]}])


def test_full_pipeline_mock():
    provider = MockProvider([
        _propose_reply_1(),   # window 1
        _propose_reply_2(),   # window 2
        _point_reply(),       # point for section with >=2 claims
        _thesis_reply(),      # theses
    ])
    art = analyze(DOC, doc_id="fund-review", title="Fund Review",
                  provider=provider)

    assert art.stats["proposals"] == 5
    assert art.stats["accepted"] == 3
    assert art.stats["rejected"] == 2
    stages = art.stats["rejected_by_stage"]
    assert stages.get("deixis") == 1
    assert stages.get("support") == 1

    # reported-speech stance survived to the record
    reported = [c for c in art.claims if c.stance == "reported"]
    assert reported and reported[0].stance_source == "Dr. Reyes"

    # spans carry real offsets into the normalized text
    for c in art.claims:
        for sp in c.spans:
            assert art.tree.text[sp.start:sp.end] == sp.quote
            assert sp.sent_ids

    # ids are content-addressed (re-run gives identical ids)
    provider2 = MockProvider([_propose_reply_1(), _propose_reply_2(),
                              _point_reply(), _thesis_reply()])
    art2 = analyze(DOC, doc_id="fund-review", title="Fund Review",
                   provider=provider2)
    assert [c.id for c in art.claims] == [c.id for c in art2.claims]

    assert len(art.points) == 1
    assert art.points[0].claim_ids
    assert len(art.theses) == 1
    assert art.theses[0].point_ids or art.theses[0].claim_ids

    md = render(art)
    assert "Kernaussagen" in md and "Funnel" in md


def test_pipeline_survives_garbage_provider():
    provider = MockProvider(["not json at all", "still not json"] * 10)
    art = analyze("One paragraph. Two sentences here.", doc_id="junk",
                  title="Junk", provider=provider, do_assemble=False)
    assert art.claims == []
    assert art.stats["window_errors"]
