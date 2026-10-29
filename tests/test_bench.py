from episteme_fable.bench import (MATCH_FLOOR, THESIS_FLOOR, _judge_pairs,
                                  _match_with_judge)
from episteme_fable.providers import MockProvider


def test_judge_pairs_uses_thesis_instructions_and_parses_matches():
    judge = MockProvider(['[["G0","P1"],["G9","P0"],["bogus"]]'])
    out = _judge_pairs(judge, [(0, "a thesis")], [(0, "x"), (1, "y")],
                       model="m", what="theses")
    assert out == [(0, 1)]            # unknown ids and malformed items dropped
    assert "THESES" in judge.prompts[0]
    assert "G0: a thesis" in judge.prompts[0]


def test_match_with_judge_adds_only_unmatched_pairs():
    gold = ["the model beats prior systems on translation benchmarks",
            "attention alone suffices for sequence transduction"]
    pred = ["the model beats prior systems on translation benchmarks",
            "recurrence and convolution are unnecessary when attention is used"]
    judge = MockProvider(['[["G1","P1"],["G0","P1"]]'])
    pairs, judged = _match_with_judge(gold, pred, THESIS_FLOOR, judge, "m", "theses")
    assert judged == 1
    assert sorted((g, p) for g, p, _ in pairs) == [(0, 0), (1, 1)]
    assert [s for _, _, s in pairs if s == -1.0] == [-1.0]
    # only the leftovers were sent to the judge
    assert "G0: the model" not in judge.prompts[0]
    assert "P0: the model" not in judge.prompts[0]
    assert "G1: attention" in judge.prompts[0]


def test_match_with_judge_without_judge_is_pure_lexical():
    pairs, judged = _match_with_judge(["x y z w"], ["totally different"],
                                      MATCH_FLOOR, None, "m", "claims")
    assert pairs == [] and judged == 0
