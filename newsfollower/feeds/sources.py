"""Registry of free, key-less news sources.

Every URL here was reachable without an API key or account when this file was
written (2026-08-29); `reachable` records that check so a source that rots is
visible rather than silently absent. Run `python -m newsfollower.squawk.runner
--check` to re-verify.

`poll_s` is a floor, not a promise: the client sends conditional GETs, so a
quiet feed costs a 304. Primary sources (central banks, statistical agencies,
exchange halts) are polled hardest because they are where a squawk actually
originates - everything else is downstream reporting.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    key: str            # matched against config.SOURCE_TIERS for the trust weight
    name: str
    url: str
    poll_s: float
    region: str = ""    # default region tag when the text does not imply one
    primary: bool = False   # publisher of record, not a report about one
    reachable: bool = True
    note: str = ""


SOURCES: tuple[Source, ...] = (
    # --- primary: central banks -----------------------------------------
    Source("federalreserve.gov", "Fed press",
           "https://www.federalreserve.gov/feeds/press_all.xml",
           10, "US", primary=True),
    Source("federalreserve.gov", "Fed speeches",
           "https://www.federalreserve.gov/feeds/speeches.xml",
           15, "US", primary=True),
    Source("ecb", "ECB press",
           "https://www.ecb.europa.eu/rss/press.html",
           15, "EU", primary=True),
    Source("boe", "Bank of England news",
           "https://www.bankofengland.co.uk/rss/news",
           20, "UK", primary=True),
    Source("boe", "Bank of England publications",
           "https://www.bankofengland.co.uk/rss/publications",
           60, "UK", primary=True),

    # --- primary: statistical agencies and regulators --------------------
    Source("bls.gov", "BLS releases",
           "https://www.bls.gov/feed/bls_latest.rss",
           10, "US", primary=True,
           note="403 unless NEWSFOLLOWER_CONTACT is set to your email"),
    Source("census.gov", "Census economic indicators",
           "https://www.census.gov/economic-indicators/indicator.xml",
           30, "US", primary=True),
    Source("sec.gov", "SEC EDGAR 8-K",
           "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K"
           "&company=&dateb=&owner=include&count=40&output=atom",
           20, "US", primary=True,
           note="403 unless NEWSFOLLOWER_CONTACT is set to your email"),
    Source("nasdaqtrader", "Nasdaq trade halts",
           "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts",
           10, "US", primary=True),
    Source("eia.gov", "EIA Today in Energy",
           "https://www.eia.gov/rss/todayinenergy.xml",
           60, "US", primary=True),

    # --- secondary: wires and majors -------------------------------------
    Source("cnbc", "CNBC top news",
           "https://search.cnbc.com/rs/search/combinedcms/view.xml"
           "?partnerId=wrss01&id=100003114", 15),
    Source("cnbc", "CNBC economy",
           "https://search.cnbc.com/rs/search/combinedcms/view.xml"
           "?partnerId=wrss01&id=20910258", 20),
    Source("cnbc", "CNBC finance",
           "https://search.cnbc.com/rs/search/combinedcms/view.xml"
           "?partnerId=wrss01&id=10000664", 30),
    Source("cnbc", "CNBC earnings",
           "https://search.cnbc.com/rs/search/combinedcms/view.xml"
           "?partnerId=wrss01&id=15839135", 30),
    Source("marketwatch", "MarketWatch real-time",
           "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines", 15),
    Source("marketwatch", "MarketWatch top stories",
           "https://feeds.content.dowjones.io/public/rss/mw_topstories", 30),
    Source("ft", "FT home", "https://www.ft.com/rss/home", 60),

    # --- tertiary: aggregators and general press --------------------------
    Source("yahoo", "Yahoo Finance",
           "https://finance.yahoo.com/news/rssindex", 30),
    Source("investing.com", "Investing.com",
           "https://www.investing.com/rss/news.rss", 30),
    Source("bbc", "BBC Business",
           "https://feeds.bbci.co.uk/news/business/rss.xml", 60, "UK"),
    Source("guardian", "Guardian Business",
           "https://www.theguardian.com/uk/business/rss", 60, "UK"),
    Source("nytimes", "NYT Business",
           "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", 60, "US"),

    # --- known-dead, kept so the gap is visible rather than forgotten -----
    Source("reuters", "Reuters business", "https://feeds.reuters.com/reuters/businessNews",
           30, reachable=False, note="public RSS retired; no free replacement"),
    Source("usda", "USDA releases", "https://www.usda.gov/rss/latest-releases.xml",
           60, "US", primary=True, reachable=False,
           note="403 to non-browser UAs; WASDE needs scraping instead"),
)

LIVE_SOURCES = tuple(s for s in SOURCES if s.reachable)
PRIMARY_SOURCES = tuple(s for s in LIVE_SOURCES if s.primary)
