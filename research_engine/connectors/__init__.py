"""
Source connectors (Spec Section 2, 3, 11, 16)

    WebConnector     Tavily -> Wikipedia -> DuckDuckGo
    PaperConnector   OpenAlex, arXiv, Crossref, DOAJ, PubMed, Semantic Scholar
    BookConnector    Internet Archive, Open Library, Google Books
    ClassicTextConnector
                     Wikisource (official MediaWiki action API) — public-domain
                     mool text ka lane, catalogue nahi
    DatasetConnector Zenodo, data.gov (US), WHO GHO, World Bank, HuggingFace,
                     data.gov.in (key optional)
    PatentDiscoveryConnector
                     EPO linked open data (keyless), USPTO ODP (key optional)
    MarketConnector  World Bank Indicators + ECB (keyless), FRED + Alpha Vantage
                     (free key, bina card) — TIME SERIES ka lane, catalogue nahi
    MediaConnector   archive.org (keyless) — video/audio items ka PARICHAY
                     (description). Media khud padha nahi jaata: read_level
                     hamesha "snippet" rehta hai

Naya provider add karna = BaseConnector ka ek naya subclass + facade list mein entry.
"""
from .base import (
    DEFAULT_TIMEOUT,
    SLOW_TIMEOUT,
    AccessBlocked,
    BaseConnector,
    ConnectorError,
    ConnectorHTTPError,
    ConnectorSkipped,
    RateLimited,
    content_terms,
    http_get,
    select_terms,
    term_overlap,
)
from .book_connector import (
    BookConnector,
    GoogleBooksConnector,
    InternetArchiveConnector,
    OpenLibraryConnector,
)
from .classic_connector import (
    ClassicTextConnector,
    WikisourceConnector,
    wikisource_langs,
)
from .dataset_connector import (
    DataGovConnector,
    DataGovInConnector,
    DatasetConnector,
    HuggingFaceDatasetsConnector,
    WHOGhoConnector,
    WorldBankConnector,
    ZenodoConnector,
)
from .market_connector import (
    AlphaVantageConnector,
    EcbSeriesConnector,
    FredSeriesConnector,
    MarketConnector,
    WorldBankSeriesConnector,
)
from .media_connector import (
    MediaArchiveConnector,
    MediaConnector,
    build_query as media_search_query,
    media_label,
)
from .paper_connector import (
    ArxivConnector,
    CrossrefConnector,
    DOAJConnector,
    OpenAlexConnector,
    PaperConnector,
    PubMedConnector,
    SemanticScholarConnector,
)
from .patent_connector import (
    EpoLinkedDataConnector,
    PatentDiscoveryConnector,
    PatentProviderConnector,
    UsptoOdpConnector,
    espacenet_lookup,
)
from .web_connector import (
    DuckDuckGoConnector,
    TavilyConnector,
    WebConnector,
    WikipediaConnector,
)

__all__ = [
    "BaseConnector", "http_get",
    # honest failure types — pipeline in par reason decide karta hai
    "ConnectorError", "RateLimited", "AccessBlocked", "ConnectorHTTPError",
    "ConnectorSkipped",
    # query + timeout helpers (test aur live script dono use karte hain)
    "content_terms", "select_terms", "term_overlap",
    "DEFAULT_TIMEOUT", "SLOW_TIMEOUT",
    "WebConnector", "TavilyConnector", "WikipediaConnector", "DuckDuckGoConnector",
    "PaperConnector", "OpenAlexConnector", "ArxivConnector", "CrossrefConnector",
    "DOAJConnector", "PubMedConnector", "SemanticScholarConnector",
    "BookConnector", "InternetArchiveConnector", "OpenLibraryConnector",
    "GoogleBooksConnector",
    # public-domain MOOL TEXT lane (granth/classic) — official Wikimedia API only
    "ClassicTextConnector", "WikisourceConnector", "wikisource_langs",
    "DatasetConnector", "ZenodoConnector", "DataGovConnector", "WHOGhoConnector",
    "WorldBankConnector", "HuggingFaceDatasetsConnector", "DataGovInConnector",
    # patents — alag tier, kyunki patent legal document hai, science proof nahi
    "PatentDiscoveryConnector", "PatentProviderConnector",
    "EpoLinkedDataConnector", "UsptoOdpConnector", "espacenet_lookup",
    # market/economic TIME SERIES — bhi alag tier, kyunki backtest ke liye
    # catalogue kaafi nahi, asli period→value chahiye
    "MarketConnector", "WorldBankSeriesConnector", "EcbSeriesConnector",
    "FredSeriesConnector", "AlphaVantageConnector",
    # video/audio DHOONDHNE ka lane (#133b) — parichay padha jaata hai, media
    # nahi. Isliye ye lane kabhi full_text nahi likhta.
    "MediaConnector", "MediaArchiveConnector", "media_search_query",
    "media_label",
]
