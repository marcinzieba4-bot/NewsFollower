from newsfollower.models import Priority
from newsfollower.squawk.calendar import (
    Release, find_indicator, parse_release,
)


def test_release_formats_as_actual_versus_expected():
    r = Release("CPI", "US", "M/M", actual=0.4, expected=0.2, prior=0.3)
    assert r.squawk_body() == "CPI M/M 0.4% VS. EXP. 0.2% (PREV. 0.3%)"


def test_missing_fields_are_omitted_not_faked():
    assert Release("CPI", actual=0.4).squawk_body() == "CPI 0.4%"


def test_surprise_is_scaled_by_indicator_sigma():
    cpi = Release("CPI", actual=0.4, expected=0.2)          # 0.2pp on 0.1 sigma
    claims = Release("jobless claims", actual=235, expected=225, unit="K")
    assert cpi.surprise_sigma == 2.0
    assert claims.surprise_sigma < cpi.surprise_sigma


def test_big_miss_on_a_top_tier_series_is_critical():
    assert Release("CPI", actual=0.4, expected=0.2).priority() is Priority.CRITICAL


def test_small_miss_on_a_minor_series_is_not_important():
    assert Release("jobless claims", actual=221, expected=225,
                   unit="K").priority() < Priority.IMPORTANT


def test_inline_top_tier_print_still_gets_a_line():
    assert Release("CPI", actual=0.2, expected=0.2).priority() is Priority.NORMAL


def test_signed_surprise_keeps_direction():
    assert Release("CPI", actual=0.1, expected=0.3).surprise < 0


def test_unknown_indicator_needs_a_bigger_miss_to_squawk():
    # Default calibration is deliberately unflattering: an unrecognised series
    # has to miss by a lot before it interrupts anything.
    modest = Release("widget shipments index", actual=5.0, expected=4.0)
    assert modest.surprise_sigma == 1.0
    assert modest.priority() is Priority.LOW
    big = Release("widget shipments index", actual=9.0, expected=4.0)
    assert big.priority() >= Priority.IMPORTANT


def test_parse_release_extracts_all_three_numbers():
    r = parse_release("US CPI rose 0.4% m/m vs expectations of 0.2%, prior 0.3%", "cpi")
    assert (r.actual, r.expected, r.prior, r.period) == (0.4, 0.2, 0.3, "M/M")


def test_parse_release_handles_trailing_consensus_form():
    r = parse_release("Payrolls came in at 142 vs 165 expected", "nonfarm payrolls")
    assert (r.actual, r.expected) == (142.0, 165.0)


def test_headline_without_a_number_is_not_a_print():
    assert parse_release("CPI report due Thursday", "cpi") is None


def test_find_indicator_prefers_the_longest_match():
    assert find_indicator("US core cpi rose 0.3%") == "core cpi"
    assert find_indicator("no data here") == ""
