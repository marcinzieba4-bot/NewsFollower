import time

from newsfollower import NewsFollower, NewsItem, Priority, Tick
from newsfollower.dedup import Deduper, similarity
from newsfollower.pipeline import PipelineConfig
from tests.test_price_action import calm


def test_only_important_news_is_emitted():
    f = NewsFollower()
    now = time.time()
    critical = f.on_news(NewsItem("1", "Fed announces emergency rate cut of 50 basis points",
                                  "reuters", ts=now))
    noise = f.on_news(NewsItem("2", "Week ahead: what to watch in markets",
                               "investing.com", ts=now))
    assert critical is not None and critical.priority >= Priority.IMPORTANT
    assert noise is None
    assert f.dropped


def test_duplicate_story_alerts_once():
    f = NewsFollower()
    now = time.time()
    a = f.on_news(NewsItem("1", "Fed Chair Warsh says the central bank still has work "
                                "to do on inflation", "reuters", ts=now))
    b = f.on_news(NewsItem("2", "Fed Chair Warsh says the central bank still has work "
                                "to do on inflation", "cnbc", ts=now + 30))
    assert a is not None
    assert b is None


def test_unexplained_move_is_emitted():
    f = NewsFollower()
    ticks = calm("XYZ", start=time.time() - 1000)
    ticks.append(Tick("XYZ", ticks[-1].price * 0.965, ticks[-1].ts + 5.0, volume=30000.0))
    alerts = [a for a in (f.on_tick(t) for t in ticks) if a]
    assert len(alerts) == 1
    assert alerts[0].kind == "unexplained_move"


def test_news_then_move_collapses_into_one_confirmed_alert():
    f = NewsFollower(PipelineConfig(correlate_s=600.0))
    start = time.time() - 1000
    ticks = calm("TSN", start=start)
    f.on_news(NewsItem("1", "Trump authorizes legal documents to let farmers process "
                            "their own food", "truthsocial", ts=ticks[-1].ts,
                       symbols=("TSN",)))
    ticks.append(Tick("TSN", ticks[-1].price * 0.97, ticks[-1].ts + 20.0, volume=30000.0))
    alerts = [a for a in (f.on_tick(t) for t in ticks) if a]
    assert len(alerts) == 1
    assert alerts[0].kind == "confirmed"
    assert alerts[0].priority is Priority.CRITICAL


def test_move_then_news_also_confirms():
    f = NewsFollower(PipelineConfig(correlate_s=600.0))
    ticks = calm("TSN", start=time.time() - 1000)
    ticks.append(Tick("TSN", ticks[-1].price * 0.97, ticks[-1].ts + 5.0, volume=30000.0))
    for t in ticks:
        f.on_tick(t)
    alert = f.on_news(NewsItem("1", "Trump authorizes documents letting ranchers process "
                                    "their own meat", "truthsocial", ts=ticks[-1].ts + 30,
                               symbols=("TSN",)))
    assert alert is not None and alert.kind == "confirmed"


def test_dedup_similarity_separates_distinct_stories():
    a = "Fed Chair Warsh says central bank has work to do on inflation"
    b = "Fed chair Warsh: central bank still has work to do on inflation"
    c = "Nvidia guides third quarter revenue above estimates"
    assert similarity(a, b) > 0.4
    assert similarity(a, c) < 0.1


def test_deduper_entries_expire():
    d = Deduper(ttl_s=60)
    d.add("Fed announces emergency rate cut", 0.0)
    assert d.check("Fed announces emergency rate cut", 30.0) is not None
    assert d.check("Fed announces emergency rate cut", 500.0) is None


def test_deduper_catches_same_story_with_extra_detail():
    d = Deduper()
    long = ("Fed Chair Warsh says central bank still has work to do on inflation; "
            "2-year yield jumps 11 basis points")
    short = "Fed Chair Warsh says the central bank still has work to do on inflation"
    d.add(long, 0.0)
    assert d.check(short, 10.0) is not None


def test_deduper_does_not_merge_unrelated_stories():
    d = Deduper()
    d.add("Fed Chair Warsh says central bank has work to do on inflation", 0.0)
    assert d.check("OPEC+ announces surprise production cut", 10.0) is None
    assert d.check("Nvidia guides third quarter revenue above estimates", 10.0) is None
