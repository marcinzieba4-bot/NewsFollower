import time

from newsfollower.models import Priority
from newsfollower.squawk.format import (
    compress, detect_region, split_speaker, strip_cruft, to_squawk,
)


def squawk(headline, *, priority=Priority.CRITICAL, source="", symbols=(), region=""):
    return to_squawk(headline, priority=priority, ts=0.0, source=source,
                     symbols=symbols, default_region=region)


def test_central_bank_speaker_is_attributed():
    line = squawk("Fed Chair Warsh says central bank still has work to do on inflation")
    assert line.body == "FED'S WARSH: CENTRAL BANK STILL HAS WORK TO DO ON INFLATION"
    assert line.region == "US"
    assert line.render(with_time=False) == f"*(US) {line.body}"


def test_possessive_and_colon_attribution():
    org, name, rest = split_speaker("ECB's Lagarde: we are not pre-committing")
    assert (org, name) == ("ECB", "LAGARDE")
    assert rest == "we are not pre-committing"


def test_unattributed_headline_is_left_alone():
    assert split_speaker("Wheat futures surge on Black Sea disruption")[0] == ""


def test_bare_name_without_institution_is_not_attributed():
    # The speaker regex is loose; a name with no recognisable org must not
    # cause the line to be restructured.
    assert split_speaker("Smith says the harvest looks strong")[0] == ""


def test_region_uses_earliest_subject_not_list_order():
    # "russia" appears too, but the story is about Ukrainian strikes.
    assert detect_region("Ukrainian strikes halt shipments from Russian ports") == "UA"


def test_region_matching_is_word_bounded():
    # "versus" must not read as "us".
    assert detect_region("Shipments rose versus prior month") == ""


def test_region_falls_back_to_source_hint():
    assert detect_region("Quarterly report published", source="federalreserve.gov") == "US"


def test_org_mention_sets_region_without_attribution():
    assert squawk("OPEC+ announces surprise production cut").region == "OPEC"


def test_opec_plus_survives_region_stripping():
    assert "OPEC+ ANNOUNCES" in squawk("OPEC+ announces surprise production cut").body


def test_duplicate_region_prefix_is_stripped_from_body():
    line = squawk("US CPI rose 0.4 percent month-on-month", source="bls.gov")
    assert line.region == "US"
    assert line.body.startswith("CPI ROSE")


def test_units_are_compressed():
    out = compress("Nvidia guides revenue to $108 billion, up 50 basis points year-on-year")
    assert "USD 108BLN" in out
    assert "BPS" in out
    assert "Y/Y" in out


def test_percent_spacing_is_closed_up():
    assert "0.4%" in compress("CPI rose 0.4 percent")


def test_publication_trailers_and_leaders_are_removed():
    assert strip_cruft("BREAKING: OPEC cuts output - Reuters") == "OPEC cuts output"
    assert strip_cruft("Fed holds rates | CNBC").endswith("rates")


def test_ticker_leads_the_line_when_known():
    assert squawk("Nvidia guides revenue higher", symbols=("NVDA",)).body.startswith("NVDA:")


def test_long_headlines_are_truncated_on_a_word_boundary():
    line = to_squawk("word " * 60, priority=Priority.LOW, ts=0.0, width=40)
    assert len(line.body) <= 43
    assert line.body.endswith("...")


def test_marker_reflects_priority():
    assert squawk("Fed cuts rates", priority=Priority.CRITICAL).marker == "*"
    assert squawk("Fed cuts rates", priority=Priority.IMPORTANT).marker == "-"


def test_spoken_expands_abbreviations_for_tts():
    line = squawk("Fed raises rates by 50 basis points")
    spoken = line.spoken()
    assert "basis points" in spoken
    assert "BPS" not in spoken
