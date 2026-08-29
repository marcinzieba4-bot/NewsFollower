import time

from newsfollower import NewsConfig, NewsItem, Priority, score_news
from newsfollower.criticality import magnitude_bonus, source_weight


def item(headline, source="reuters", **kw):
    return NewsItem(id="t", headline=headline, source=source, ts=time.time(), **kw)


def test_central_bank_headline_is_critical():
    s = score_news(item("Fed Chair Warsh says central bank has work to do; "
                        "2-year yield jumps 11 basis points"))
    assert s.priority >= Priority.IMPORTANT
    assert "central_bank" in s.categories


def test_preview_commentary_is_dropped():
    s = score_news(item("Will Nvidia stock soar after Aug. 26? Here's what history shows",
                        source="fool.com blog"))
    assert s.priority < Priority.IMPORTANT


def test_analyst_chatter_scores_below_the_wire():
    wire = score_news(item("OPEC+ announces surprise production cut of 1 million bpd"))
    chatter = score_news(item("Analysts say OPEC+ could cut production", source="seekingalpha"))
    assert wire.score > chatter.score
    assert chatter.priority < Priority.IMPORTANT


def test_no_category_scores_zero():
    s = score_news(item("Local bakery wins award for sourdough"))
    assert s.score == 0.0
    assert s.priority is Priority.DROP


def test_stale_news_is_dropped():
    now = time.time()
    old = NewsItem(id="t", headline="Fed announces emergency rate cut of 50 basis points",
                   source="reuters", ts=now - 60 * 60)
    assert score_news(old, NewsConfig(), now=now).priority is Priority.DROP


def test_source_tier_scales_score():
    text = "OPEC+ announces surprise production cut of 1 million barrels per day"
    assert score_news(item(text, "reuters")).score > score_news(item(text, "reddit")).score


def test_source_weight_matches_longest_key():
    assert source_weight("Reuters Business") == 1.0
    assert source_weight("some-unknown-feed") < 0.5


def test_magnitude_bonus_scales_with_size():
    small, _ = magnitude_bonus("cpi rises 0.2%")
    large, _ = magnitude_bonus("cpi rises 1.4%")
    assert large > small


def test_word_boundary_prevents_false_category_hit():
    # "cpi" inside "recipient" must not trigger the macro_data category.
    s = score_news(item("Award recipient named at industry dinner"))
    assert "macro_data" not in s.categories


def test_watchlist_boosts_score():
    it = item("Nvidia (NVDA) cuts guidance on gross margin pressure")
    plain = score_news(it, NewsConfig())
    boosted = score_news(it, NewsConfig(watchlist=frozenset({"NVDA"})))
    assert boosted.score > plain.score
