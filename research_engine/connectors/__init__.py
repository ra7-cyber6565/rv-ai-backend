"""
Source connectors (Spec Section 2, 3, 11, 16)

    WebConnector     Tavily -> Wikipedia -> DuckDuckGo
    PaperConnector   OpenAlex, arXiv, Crossref, DOAJ, PubMed, Semantic Scholar
    BookConnector    Internet Archive, Open Library, Google Books
    DatasetConnector Zenodo, data.gov (US), WHO GHO, World Bank, HuggingFace,
                     data.gov.in (key optional)
    PatentDiscoveryConnector
                     EPO linked open data (keyless), USPTO ODP (key optional)

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
from .dataset_connector import (
    DataGovConnector,
    DataGovInConnector,
    DatasetConnector,
    HuggingFaceDatasetsConnector,
    WHOGhoConnector,
    WorldBankConnector,
    ZenodoConnector,
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
    "DatasetConnector", "ZenodoConnector", "DataGovConnector", "WHOGhoConnector",
    "WorldBankConnector", "HuggingFaceDatasetsConnector", "DataGovInConnector",
    # patents — alag tier, kyunki patent legal document hai, science proof nahi
    "PatentDiscoveryConnector", "PatentProviderConnector",
    "EpoLinkedDataConnector", "UsptoOdpConnector", "espacenet_lookup",
]
