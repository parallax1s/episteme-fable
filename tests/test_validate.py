from episteme_fable.validate import (align_quotes, check_atomicity,
                                     check_deixis, check_fragment,
                                     check_support, normalize_claim_text)


def test_fragment_rejects_shards():
    r = check_fragment("reduced energy landscape.")
    assert not r.ok  # 3 words
    assert check_fragment("The fund lost twelve percent.").ok


def test_deixis_rejects_bare_openers():
    for bad in ("It caused emissions to rise.",
                "This shows the method works.",
                "They agreed to the terms.",
                "There they built the lab."):
        assert not check_deixis(bad).ok, bad


def test_deixis_allows_pleonastic_and_existential():
    assert check_deixis("It is unlikely that the fund recovers by 2030.").ok
    assert check_deixis("It is unfair to blame the committee for the loss.").ok
    assert check_deixis("There are three stages in the Dep-LLM pipeline.").ok


def test_atomicity():
    assert not check_atomicity("The fund lost value; the committee resigned.").ok
    r = check_atomicity("The fund lost value, and the committee resigned in May.")
    assert r.ok and "possibly_compound" in r.flags
    assert check_atomicity("The fund lost 12% of its value.").flags == []


def test_normalize_claim_text():
    assert normalize_claim_text("the fund lost value") == "The fund lost value."
    assert normalize_claim_text("  A  b   c? ") == "A b c?"


def test_align_exact_normalized_fuzzy():
    window = ("The reserve fund lost 12% of its value.  According to Dr. Reyes, "
              "losses will continue. The committee disagreed strongly.")
    # exact
    aligned, res = align_quotes(["The reserve fund lost 12% of its value."],
                                window, 100)
    assert res.ok and aligned[0][1] == 100
    # normalized (double space collapsed in quote)
    aligned, res = align_quotes(["According to Dr. Reyes, losses will continue."],
                                window, 0)
    assert res.ok
    # fuzzy (small paraphrase of one sentence)
    aligned, res = align_quotes(["The committee disagreed very strongly."],
                                window, 0)
    assert res.ok and "quote_fuzzy_match" in res.flags
    # miss
    _, res = align_quotes(["Nothing like this appears anywhere."], window, 0)
    assert not res.ok


def test_support_numbers_and_names():
    window = "According to Dr. Reyes, the reserve fund lost 12% of its value."
    ok = check_support("The reserve fund lost 12% of its value.",
                       window, window, "")
    assert ok.ok
    bad_num = check_support("The reserve fund lost 15% of its value.",
                            window, window, "")
    assert not bad_num.ok and bad_num.reasons[0].startswith("unsupported_number")
    bad_name = check_support("The Vanguard fund lost 12% of its value.",
                             window, window, "")
    assert not bad_name.ok and bad_name.reasons[0].startswith("unsupported_name")


def test_support_name_resolvable_from_context():
    window = "He argued the merger would fail within a year."
    ctx = "Context: Karl Steiner spoke at the hearing."
    ok = check_support("Karl Steiner argued the merger would fail within a year.",
                       window, window, ctx)
    assert ok.ok


def test_support_coverage_floor():
    window = "The fund lost value."
    r = check_support("Quantum decoherence explains consciousness and free will.",
                      window, window, "")
    assert not r.ok
