import json

from newsfollower.feeds.http import ConditionalClient, Response, user_agent
from newsfollower.feeds.prices import YahooBarFeed
from newsfollower.feeds.rss import clean, parse_date, parse_feed
from newsfollower.feeds.sources import LIVE_SOURCES, SOURCES

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Fed &amp; Treasury issue joint statement</title>
    <link>https://example.org/a</link>
    <guid>tag:a</guid>
    <description>&lt;p&gt;Body &lt;b&gt;text&lt;/b&gt;&lt;/p&gt;</description>
    <pubDate>Fri, 28 Aug 2026 14:30:00 GMT</pubDate>
  </item>
  <item>
    <title>Second headline</title>
    <pubDate>Fri, 28 Aug 2026 15:00:00 GMT</pubDate>
  </item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>EDGAR filing posted</title>
    <link href="https://example.org/f"/>
    <id>urn:x</id>
    <updated>2026-08-28T14:30:00Z</updated>
    <summary>Filing summary</summary>
  </entry>
</feed>"""


def test_rss_items_are_parsed_and_ordered_oldest_first():
    items = parse_feed(RSS, "cnbc")
    assert [i.headline for i in items] == ["Fed & Treasury issue joint statement",
                                           "Second headline"]
    assert items[0].ts < items[1].ts


def test_html_and_entities_are_stripped_from_body():
    assert parse_feed(RSS, "cnbc")[0].body == "Body text"


def test_atom_entries_and_href_links_are_parsed():
    items = parse_feed(ATOM, "sec.gov")
    assert items[0].headline == "EDGAR filing posted"
    assert items[0].url == "https://example.org/f"


def test_ids_are_stable_across_parses_but_differ_by_source():
    a = parse_feed(RSS, "cnbc")[0].id
    b = parse_feed(RSS, "cnbc")[0].id
    c = parse_feed(RSS, "yahoo")[0].id
    assert a == b != c


def test_malformed_xml_yields_no_items_rather_than_raising():
    assert parse_feed(b"<rss><channel><item>", "cnbc") == []
    assert parse_feed(b"not xml at all", "cnbc") == []


def test_items_without_a_title_are_skipped():
    feed = b'<?xml version="1.0"?><rss><channel><item><link>x</link></item></channel></rss>'
    assert parse_feed(feed, "cnbc") == []


def test_undated_items_fall_back_to_now():
    feed = b'<?xml version="1.0"?><rss><channel><item><title>T</title></item></channel></rss>'
    assert parse_feed(feed, "cnbc", now=1234.0)[0].ts == 1234.0


def test_parse_date_handles_rfc822_and_iso8601():
    assert parse_date("Fri, 28 Aug 2026 14:30:00 GMT") == parse_date("2026-08-28T14:30:00Z")
    assert parse_date("garbage") is None
    assert parse_date(None) is None


def test_clean_collapses_whitespace():
    assert clean(" a\n  b ") == "a b"
    assert clean(None) == ""


def test_user_agent_carries_contact_without_a_url():
    # BLS and SEC 403 on a UA containing a URL, and on one with no contact.
    import newsfollower.feeds.http as http
    original = http.CONTACT
    try:
        http.CONTACT = "me@example.org"
        agent = user_agent()
        assert "me@example.org" in agent
        assert "http" not in agent
    finally:
        http.CONTACT = original


def test_backoff_blocks_repeat_requests_and_widens():
    client = ConditionalClient()
    entry = client._entry("https://x")
    client._backoff(entry, now=1000.0)
    first = entry.next_allowed_ts
    assert not client.ready("https://x", now=1000.0)
    assert client.ready("https://x", now=first + 1)
    client._backoff(entry, now=1000.0)
    assert entry.next_allowed_ts > first


def test_backoff_respects_retry_after():
    client = ConditionalClient()
    entry = client._entry("https://x")
    client._backoff(entry, now=0.0, retry_after=600.0)
    assert entry.next_allowed_ts >= 480.0


class _FakeClient:
    def __init__(self, payload):
        self.payload = payload

    def get(self, url, now=None):
        return Response(200, json.dumps(self.payload).encode())


def _chart(stamps, closes, volumes):
    return {"chart": {"result": [{"timestamp": stamps,
                                  "indicators": {"quote": [{"close": closes,
                                                            "volume": volumes}]}}]}}


def test_forming_last_bar_is_withheld():
    feed = YahooBarFeed(_FakeClient(_chart([1, 2, 3], [10.0, 11.0, 12.0], [1, 1, 1])))
    ticks = feed.poll("AAA")
    assert [t.ts for t in ticks] == [1.0, 2.0]      # bar 3 still forming


def test_bars_are_not_re_emitted():
    feed = YahooBarFeed(_FakeClient(_chart([1, 2, 3], [10.0, 11.0, 12.0], [1, 1, 1])))
    assert len(feed.poll("AAA")) == 2
    assert feed.poll("AAA") == []


def test_null_closes_are_skipped():
    feed = YahooBarFeed(_FakeClient(_chart([1, 2, 3], [10.0, None, 12.0], [1, 1, 1])))
    assert [t.ts for t in feed.poll("AAA")] == [1.0]


def test_malformed_chart_payload_returns_nothing():
    assert YahooBarFeed(_FakeClient({"chart": {"result": []}})).poll("AAA") == []


def test_every_live_source_is_marked_reachable_and_has_a_tier_key():
    from newsfollower.config import SOURCE_TIERS
    for source in LIVE_SOURCES:
        assert source.reachable
        assert source.poll_s > 0
    # Dead sources stay in the registry so the gap is visible.
    assert any(not s.reachable for s in SOURCES)
    # Every key should resolve to a real tier rather than the default.
    unknown = {s.key for s in LIVE_SOURCES
               if not any(k in s.key for k in SOURCE_TIERS)}
    assert unknown == set(), f"sources with no configured trust tier: {unknown}"
