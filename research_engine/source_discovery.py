"""
SourceDiscovery — Spec Section 2 (Multi-Source Discovery)

"Search universe jitna bada aur legally accessible ho, utna bada rakho...
 sabhi sources ko blindly process mat karo."

Ye module sirf DISCOVERY karta hai (kya-kya मिला), selection nahi.
Selection RelevanceEngine + EvidenceEngine ka kaam hai.

Speed: connectors network-bound hain, isliye threads mein parallel chalate hain —
warna 9 paper connectors x 2 attempts x 35s = kai minute lag jaate.

WALL-CLOCK BUDGET (Spec Section 13 — "Maximum ka matlab unlimited internet nahi"):
    Gemini calls par rail pehle din se thi, par network par koi rail nahi thi.
    DEEP round 2 mein 6 paper connectors x 3 queries = 18 tasks, har task 2
    attempts x (10s connect + 25s read) le sakta hai — worst case ~7 minute,
    aur user ke liye wo "app hang ho gayi" jaisa dikhta hai. Ab `discover()`
    ek deadline leta hai: jo task usme poora nahi hota, wo `reason="deadline"`
    ke saath honestly log hota hai (chup-chaap "0 results" NAHI banta), aur
    pool `wait=False` se chhoda jaata hai taaki ek atka connector poore
    research ko na roke.

WEB TIER SEQUENTIAL HAI (jaan-boojh kar):
    Papers/books parallel chalte hain, par web ke teen connectors ek CHAIN hain:
    Tavily → Wikipedia → DuckDuckGo, aur target pura hote hi ruk jao.

    Pehle teeno parallel submit hote the. Nateeja: (1) har round mein Tavily ka
    free quota (~1000/month) kharch hota tha chahe zaroorat ho ya na ho,
    (2) DuckDuckGo "last resort" ke bajaye hamesha chalta tha aur server ke
    andar rate-limit hokar 0 results deta tha. Ab poori chain ek hi thread
    mein chalti hai, isliye WebConnector.search() ka "jitna chahiye utna milte
    hi ruk jao" rule sach mein lagta hai.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Callable, Dict, List, Optional, Tuple

from .connectors import (BaseConnector, BookConnector, ClassicTextConnector,
                         DatasetConnector, MarketConnector, MediaConnector,
                         PaperConnector, PatentDiscoveryConnector, WebConnector)
from .models import SourceRecord
from .network_safety import public_error
from . import songcraft
from . import listener_study
from . import music_study
from . import trademodel
from . import exammodel


class SourceDiscovery:
    # Agar caller budget na de to itna (DEEP ka default) maan lo
    DEFAULT_BUDGET_SECONDS = 90

    def __init__(self, max_workers: int = 6):
        self.web = WebConnector()
        self.papers = PaperConnector()
        self.books = BookConnector()
        self.datasets = DatasetConnector()
        # Patents ek ALAG tier hai (paper tier mein ghusane se patent ka legal
        # claim science jaisa dikhne lagta tha). Plan mein `patents` key na ho to
        # ye tier chalta hi nahi — planner hi decide karta hai kab zaroorat hai.
        self.patents = PatentDiscoveryConnector()
        # Classic/mool-text tier bhi ALAG hai: book connectors CATALOGUE dete
        # hain (kahan milegi), ye lane wo text deta hai jo ASLI ME padha ja
        # sakta hai (public-domain granth, mahan logon ka apna likha). Plan mein
        # `classics` key na ho to ye tier chalta hi nahi.
        self.classics = ClassicTextConnector()
        # Market/economic TIME SERIES ka tier bhi ALAG hai. `datasets` lane
        # catalogue deta hai ("ye dataset maujood hai"), aur usse koi backtest
        # nahi chal sakta. Ye lane period→value laata hai jo record ke
        # `series_meta` me baith jaata hai, aur LAB usi ko padh kar walk-forward
        # test chalata hai — bina khud koi network call kiye. Plan me `markets`
        # key na ho to ye tier chalta hi nahi.
        self.markets = MarketConnector()
        # Video/audio ka lane bhi ALAG hai (#133b). Book lane CATALOGUE deta hai
        # aur classics lane MOOL TEXT — ye lane un dono se alag cheez laata hai:
        # kisi lecture/interview/recording ka LIKHA HUA parichay. Media khud
        # padha nahi jaata (na dekha, na suna), isliye har record par
        # `read_level="snippet"` hi rehta hai. Ye lane sirf craft-study tier se
        # chalta hai, aur wahan bhi tab jab planner ne `craft_study` bhara ho.
        self.media = MediaConnector()
        self.max_workers = max_workers

    # ── task builders ────────────────────────────────────────────────────────
    @staticmethod
    def _single(connector: BaseConnector, query: str, limit: int) -> Callable[[], Dict]:
        """Ek connector ka call, normalized {"records", "log"} shape mein."""
        def run() -> Dict:
            result = connector.safe_search(query, limit)
            return {"records": result.get("records", []),
                    "log": [{k: v for k, v in result.items() if k != "records"}]}
        return run

    def _web_chain(self, query: str, limit: int) -> Callable[[], Dict]:
        """Tavily → Wikipedia → DuckDuckGo, target pura hone par ruk jaata hai."""
        def run() -> Dict:
            result = self.web.search(query, limit)
            return {"records": result.get("records", []),
                    "log": result.get("log", [])}
        return run

    def _tasks(self, queries: List[str], plan: Dict, max_per_connector: int,
               max_web: int) -> List[Tuple[str, Callable[[], Dict]]]:
        """(label, callable) ki list — sab parallel chalengi."""
        tasks: List[Tuple[str, Callable[[], Dict]]] = []
        primary = queries[0] if queries else ""

        if plan.get("web", True) and primary:
            # sirf EK task — andar sequential fallback chain hai
            tasks.append(("web_chain", self._web_chain(primary, max_web)))

            # Official archives are an extra, explicitly bounded lane for CIA
            # Reading Room/NARA/FBI Vault/GovInfo questions.  They still use the
            # same safe web connector and URL boundary; site-specific queries do
            # not scrape private endpoints or bypass access controls.  Keeping
            # them as separate tasks means the ordinary web query is not lost.
            seen_archive_queries = set()
            for archive_query in list(plan.get("official_archive_queries", []))[:3]:
                clean = str(archive_query or "").strip()
                key = clean.casefold()
                if not clean or key in seen_archive_queries:
                    continue
                seen_archive_queries.add(key)
                tasks.append((
                    "official_archive_web",
                    self._web_chain(clean, max(1, min(2, max_web))),
                ))

        for name in plan.get("papers", []):
            connector = self.papers.by_name(name)
            if connector:
                for q in queries:
                    tasks.append((connector.name,
                                  self._single(connector, q, max_per_connector)))

        book_queries = []
        seen_book_queries = set()
        for candidate in list(plan.get("book_queries", []))[:2] or [primary]:
            clean = str(candidate or "").strip()
            key = clean.casefold()
            if not clean or key in seen_book_queries:
                continue
            seen_book_queries.add(key)
            book_queries.append(clean)

        for name in plan.get("books", []):
            connector = self.books.by_name(name)
            if connector:
                for book_query in book_queries:
                    tasks.append((connector.name,
                                  self._single(connector, book_query,
                                               max_per_connector)))

        # Datasets (Spec Section 2 + 11) — books ki tarah PRIMARY query par hi
        # chalte hain, taaki discovery budget safe rahe. Ye raw data locate karte
        # hain jispar claims tikte hain (verification ke liye zaroori).
        for name in plan.get("datasets", []):
            connector = self.datasets.by_name(name)
            if connector:
                tasks.append((connector.name,
                              self._single(connector, primary, max_per_connector)))

        # Patents (₹0 patent batch) — SIRF tab jab planner ne `patents` bhara ho.
        # Ye jaan-boojh kar PRIMARY query par hi chalta hai: patent APIs slow +
        # fair-use limited hain (EPO ~10 search/min), aur "har generic sawaal par
        # patent search" na sirf bekaar hai, wo humara hi quota kha jaata hai.
        for name in plan.get("patents", []):
            connector = self.patents.by_name(name)
            if connector:
                tasks.append((connector.name,
                              self._single(connector, primary, max_per_connector)))

        # Market/economic TIME SERIES (#118) — SIRF tab jab planner ne `markets`
        # bhara ho. PRIMARY query par hi chalta hai: providers rate-limited hain
        # (World Bank 429 de chuka hai, Alpha Vantage free plan minute-capped),
        # aur har sawaal par market call bhejna humara hi quota khata hai. Yahan
        # se aaye record ke `series_meta` par LAB ka walk-forward test tikta hai.
        for name in plan.get("markets", []):
            connector = self.markets.by_name(name)
            if connector:
                tasks.append((connector.name,
                              self._single(connector, primary,
                                           max(1, min(2, max_per_connector)))))

        # Classic/mool text (task #84) — SIRF tab jab planner ne `classics` bhara
        # ho. Query bhi planner ki `classic_queries` hoti hai, kyunki mool text
        # dhoondhne ki bhasha aam web query se alag hai ("<naam> full text public
        # domain"). Ek bhi query na ho to primary par gir jaata hai, taaki tier
        # chup-chaap khaali na baithe.
        classic_queries = []
        seen_classic_queries = set()
        for candidate in list(plan.get("classic_queries", []))[:2] or [primary]:
            clean = str(candidate or "").strip()
            key = clean.casefold()
            if not clean or key in seen_classic_queries:
                continue
            seen_classic_queries.add(key)
            classic_queries.append(clean)

        for name in plan.get("classics", []):
            connector = self.classics.by_name(name)
            if connector:
                for classic_query in classic_queries:
                    tasks.append((connector.name,
                                  self._single(connector, classic_query,
                                               max_per_connector)))

        # Copyright-likely book ka MOOL TEXT kabhi nahi laaya jaata (wo faisla
        # `classics.copyright_stance()` ka hai, aur `content_fetcher` uspar rukta
        # hai) — par use IGNORE bhi nahi karte. Uski summary/vyakhya/review aam
        # web lane se dhoondhi jaati hai, alag query par, taaki report mein saaf
        # rahe ki text nahi padha, sirf uske baare mein padha.
        if plan.get("web", True):
            seen_summary_queries = set()
            for candidate in list(plan.get("summary_queries", []))[:2]:
                clean = str(candidate or "").strip()
                key = clean.casefold()
                if not clean or key in seen_summary_queries:
                    continue
                seen_summary_queries.add(key)
                tasks.append(("classic_summary_web",
                              self._web_chain(clean, max(1, min(2, max_web)))))

        # Gaane ka CRAFT-STUDY (#129) — SIRF tab jab planner ne `craft_study`
        # bhara ho. Ye tier "gaana likhne ka hunar" padhta hai: songwriting/
        # prosody/music-emotion ki kitaab aur paper. Kisi MAUJOODA gaane ke bol
        # yahan se NAHI aate — planner pehle rok chuka hota hai, aur yahan
        # doosri deewar bhi hai (do jagah guard jaan-boojh kar).
        #
        # Har query ek hi lane par jaati hai (sab connectors par nahi), aur
        # limit chhoti rehti hai: ye lane jawab ka mool sawaal nahi hai, sirf
        # likhne ka tareeka sikhne ke liye hai — iska budget kam hi rehna
        # chahiye warna asli sawaal ka discovery bhookha reh jaayega.
        craft_limit = max(1, min(2, max_per_connector))
        seen_craft = set()
        # Craft-study apna lane KHUD maangta hai: domain routing ne books band
        # ki hain (sawaal "gaana likho" hai, physics nahi) par gaane ka hunar
        # asli me kitaabon me likha hai — intel ki maang bhi wahi hai. Isliye
        # yahan facade se pehla maujood book/paper connector liya jaata hai,
        # bhale plan ka books tier khaali ho. Ye asli sawaal ka lane nahi
        # kholta: limit chhoti hai aur query sirf craft ki hai.
        book_name = next((n for n in plan.get("books", [])
                          if self.books.by_name(n)), "")
        if not book_name:
            book_name = next((c.name for c in getattr(self.books, "connectors",
                                                      [])), "")
        paper_name = next((n for n in plan.get("papers", [])
                           if self.papers.by_name(n)), "")
        if not paper_name:
            paper_name = next((c.name for c in getattr(self.papers,
                                                       "connectors", [])), "")
        # Media lane ka naam kisi plan tier se nahi aata — ye tier plan me hota
        # hi nahi (koi `plan["media"]` nahi hai). Wajah: media sirf craft padhne
        # ke liye chahiye, asli sawaal ke evidence ke liye nahi. Isliye naam
        # seedha facade se, aur budget wahi chhota `craft_limit`.
        media_name = next((c.name for c in getattr(self.media,
                                                   "connectors", [])), "")
        for entry in list(plan.get("craft_study", []))[
                :songcraft.MAX_STUDY_QUERIES]:
            if isinstance(entry, dict):
                clean = str(entry.get("query") or "").strip()
                lane = str(entry.get("lane") or "web").strip().lower()
            else:
                clean, lane = str(entry or "").strip(), "web"
            key = clean.casefold()
            if not clean or key in seen_craft:
                continue
            # Doosri deewar: bol/karaoke/mp3 wali query kabhi network par nahi
            # jaati, chahe plan me galti se aa gayi ho.
            if songcraft.is_lyrics_hunt(clean):
                continue
            seen_craft.add(key)
            connector = None
            if lane == "books" and book_name:
                connector = self.books.by_name(book_name)
            elif lane == "papers" and paper_name:
                connector = self.papers.by_name(paper_name)
            elif lane == "media" and media_name:
                # #133b — lecture/interview/recording ka parichay. Ye lane WEB
                # par fallback nahi karta jab media connector maujood ho: web
                # chain se aaya webpage media nahi hota, aur use
                # "craft_study_media" naam dena label ka jhooth hota.
                connector = self.media.by_name(media_name)
            if connector is not None:
                tasks.append(("craft_study_" + lane,
                              self._single(connector, clean, craft_limit)))
            elif plan.get("web", True):
                # lane band ho (QUICK mode) to chup na baitho — web chain se
                # padho, aur naam se saaf rahe ki ye craft-study thi.
                tasks.append(("craft_study_web",
                              self._web_chain(clean, max(1, min(2, max_web)))))

        # SUNNE WALE ki samajh (#134b) — craft tier ke SAATH, uske slot cheene
        # bina. Ye alag tier isliye hai ki intel ki maang ke do hisse hain:
        # (1) gaana likhne ka hunar (upar wala craft tier), aur (2) sunne wale ka
        # dil/bhaav — psychology, human behaviour, nostalgia, dohraav. Dono ki
        # ginti mila dena wahi jhooth hota jise #133 me bhi rokha gaya tha,
        # isliye label bhi alag hai: `listener_study_<lane>`.
        #
        # Budget jaan-boojh kar chhota (`MAX_LISTENER_QUERIES`, aur per-connector
        # 2 tak): asli sawaal ka discovery bhookha nahi rehna chahiye.
        listener_limit = max(1, min(2, max_per_connector))
        seen_listener = set()
        for entry in list(plan.get("listener_study", []))[
                :listener_study.MAX_LISTENER_QUERIES]:
            if isinstance(entry, dict):
                clean = str(entry.get("query") or "").strip()
                lane = str(entry.get("lane") or "web").strip().lower()
            else:
                clean, lane = str(entry or "").strip(), "web"
            key = clean.casefold()
            if not clean or key in seen_listener or key in seen_craft:
                # `seen_craft` bhi dekha jaata hai: ek hi query do label ke saath
                # do baar bhejna network aur budget dono ka nuksaan hai.
                continue
            # Teesri deewar (planner + craft tier ke baad) — bol/karaoke wali
            # query yahan se bhi network par nahi jaati.
            if songcraft.is_lyrics_hunt(clean):
                continue
            seen_listener.add(key)
            connector = None
            if lane == "books" and book_name:
                connector = self.books.by_name(book_name)
            elif lane == "papers" and paper_name:
                connector = self.papers.by_name(paper_name)
            elif lane == "media" and media_name:
                connector = self.media.by_name(media_name)
            if connector is not None:
                tasks.append(("listener_study_" + lane,
                              self._single(connector, clean, listener_limit)))
            elif plan.get("web", True):
                tasks.append(("listener_study_web",
                              self._web_chain(clean, max(1, min(2, max_web)))))

        # MUSIC DIRECTION ki research (#140c) — craft aur listener tier ke SAATH,
        # dono ke slot cheene bina. Teesra tier isliye ki intel ki maang ka
        # teesra hissa hai: "konsa tone bnega music kaisa bnega" — tempo, scale/
        # raag, vaadya, aawaz aur arrangement ke peeche PADHI HUI baat. Iski
        # ginti craft/listener me mila dena wahi jhooth hota jise #133/#134 me
        # rokha gaya tha, isliye label bhi alag hai: `music_study_<lane>`.
        #
        # Budget jaan-boojh kar chhota (`MAX_MUSIC_QUERIES`, per-connector 2 tak).
        music_limit = max(1, min(2, max_per_connector))
        seen_music = set()
        for entry in list(plan.get("music_study", []))[
                :music_study.MAX_MUSIC_QUERIES]:
            if isinstance(entry, dict):
                clean = str(entry.get("query") or "").strip()
                lane = str(entry.get("lane") or "web").strip().lower()
            else:
                clean, lane = str(entry or "").strip(), "web"
            key = clean.casefold()
            if not clean or key in seen_music or key in seen_craft \
                    or key in seen_listener:
                # Dono purane tier bhi dekhe jaate hain: ek hi query teen label
                # ke saath teen baar bhejna network aur budget dono ka nuksaan.
                continue
            # Chauthi deewar (planner + craft + listener tier ke baad) — bol/
            # karaoke wali query yahan se bhi network par nahi jaati.
            if songcraft.is_lyrics_hunt(clean):
                continue
            seen_music.add(key)
            connector = None
            if lane == "books" and book_name:
                connector = self.books.by_name(book_name)
            elif lane == "papers" and paper_name:
                connector = self.papers.by_name(paper_name)
            elif lane == "media" and media_name:
                connector = self.media.by_name(media_name)
            if connector is not None:
                tasks.append(("music_study_" + lane,
                              self._single(connector, clean, music_limit)))
            elif plan.get("web", True):
                tasks.append(("music_study_web",
                              self._web_chain(clean, max(1, min(2, max_web)))))

        # TRADING MODEL ka TRADE-STUDY (#150d) — SIRF tab jab planner ne
        # `trade_study` bhara ho. Ye tier gaane ke teen tier se poori tarah ALAG
        # hai: alag label (`trade_study_<lane>`), alag budget, aur `is_lyrics_hunt`
        # ka guard yahan JAAN-BOOJH KAR nahi hai — wo gaane ki lane ka pehra hai,
        # trading ki query par use lagana lane mixing hi hota (intel ki shart:
        # "sab mix mt kr dena"). Isi wajah se yahan `seen_craft`/`seen_listener`/
        # `seen_music` bhi nahi dekhe jaate: un teen se koi query milti hi nahi.
        #
        # Kram planner se aata hai aur wo institutional-first hai — exchange/
        # regulator ka document pehle (web lane), phir theory/paper, phir concept
        # ki kitaab. Yahan wo kram badla nahi jaata.
        trade_limit = max(1, min(2, max_per_connector))
        seen_trade = set()
        for entry in list(plan.get("trade_study", []))[
                :trademodel.MAX_STUDY_QUERIES]:
            if isinstance(entry, dict):
                clean = str(entry.get("query") or "").strip()
                lane = str(entry.get("lane") or "web").strip().lower()
            else:
                clean, lane = str(entry or "").strip(), "web"
            key = clean.casefold()
            if not clean or key in seen_trade:
                continue
            seen_trade.add(key)
            connector = None
            if lane == "books" and book_name:
                connector = self.books.by_name(book_name)
            elif lane == "papers" and paper_name:
                connector = self.papers.by_name(paper_name)
            if connector is not None:
                tasks.append(("trade_study_" + lane,
                              self._single(connector, clean, trade_limit)))
            elif plan.get("web", True):
                # `lane == "web"` ka asli raasta yahi hai (exchange/regulator ka
                # document webpage hai, paper nahi), aur lane band hone par bhi
                # naam se saaf rahe ki ye trade-study thi.
                tasks.append(("trade_study_web",
                              self._web_chain(clean, max(1, min(2, max_web)))))

        # EXAM/PADHAI ka EXAM-STUDY (#171d) — SIRF tab jab planner ne
        # `exam_study` bhara ho. Ye tier baaki chaaron se ALAG hai: alag label
        # (`exam_study_<lane>_<channel>`), alag budget, aur `is_lyrics_hunt` ka
        # guard yahan JAAN-BOOJH KAR nahi hai — wo gaane ki lane ka pehra hai,
        # exam ki query par use lagana lane mixing hi hota. Isi wajah se
        # `seen_craft`/`seen_listener`/`seen_music`/`seen_trade` bhi nahi dekhe
        # jaate: un chaaron se koi query milti hi nahi.
        #
        # Ek baat khaas hai: exammodel ke lane ka naam CONNECTOR ka naam NAHI
        # hai (`official`/`textbook`/`pedagogy`/`practice`). Isliye yahan saaf
        # mapping likhi hai — padhne wali kitaab wala lane book connector par,
        # "kaise padhein" wala research paper connector par, aur official/
        # practice web par (board ka syllabus PDF webpage hai, paper nahi).
        # Label me DONO rehte hain: kaun lane thi AUR asal me kis channel par
        # gayi. Sirf lane likhna us haalat me jhoot hota jab paper connector na
        # mile aur query chup-chaap web par chali jaaye.
        exam_limit = max(1, min(2, max_per_connector))
        seen_exam = set()
        for entry in list(plan.get("exam_study", []))[
                :exammodel.MAX_STUDY_QUERIES]:
            if isinstance(entry, dict):
                clean = str(entry.get("query") or "").strip()
                lane = str(entry.get("lane") or "").strip().lower()
            else:
                clean, lane = str(entry or "").strip(), ""
            key = clean.casefold()
            if not clean or key in seen_exam:
                continue
            seen_exam.add(key)
            connector = None
            channel = "web"
            if lane == exammodel.LANE_TEXTBOOK and book_name:
                connector = self.books.by_name(book_name)
                channel = "books"
            elif lane == exammodel.LANE_PEDAGOGY and paper_name:
                connector = self.papers.by_name(paper_name)
                channel = "papers"
            if connector is not None:
                tasks.append((f"exam_study_{lane}_{channel}",
                              self._single(connector, clean, exam_limit)))
            elif plan.get("web", True):
                tasks.append((f"exam_study_{lane or 'web'}_web",
                              self._web_chain(clean, max(1, min(2, max_web)))))

        return tasks

    def discover(
        self,
        queries: List[str],
        plan: Dict,
        max_per_connector: int = 3,
        max_web: int = 5,
        round_no: int = 1,
        exclude_urls: Optional[set] = None,
        budget_seconds: Optional[int] = None,
    ) -> Dict:
        """
        queries: planner se aayi ek ya zyada search strings
        plan:    {"web": bool, "papers": [names], "books": [names],
                  "datasets": [names], "patents": [names],
                  "markets": [names], "classics": [names],
                  "classic_queries": [...], "summary_queries": [...],
                  "craft_study": [{"query","lane","why"}, ...]}

        budget_seconds: is round ki discovery ka wall-clock budget (depth config se)
        """
        tasks = self._tasks(queries, plan, max_per_connector, max_web)
        records: List[SourceRecord] = []
        log: List[Dict] = []
        seen = set(exclude_urls or ())

        if not tasks:
            return {"records": [], "log": [], "connectors_searched": [],
                    "seen_urls": seen}

        # floor 1s: user-facing values DepthConfig mein pehle hi >=20 par clamp
        # hote hain, isliye yahan ka floor sirf "0 ya None mat maano" ke liye hai
        # (test 1s ka budget de sakta hai bina suite ko slow kiye).
        budget = max(1, int(budget_seconds or self.DEFAULT_BUDGET_SECONDS))
        started = time.time()
        # NOTE: `with ThreadPoolExecutor(...)` jaan-boojh kar nahi hai — uska
        # __exit__ shutdown(wait=True) karta hai, yaani ek atka connector wahin
        # rok leta aur deadline ka koi matlab hi na rehta.
        pool = ThreadPoolExecutor(max_workers=self.max_workers)
        try:
            futures = {pool.submit(run): label for label, run in tasks}
            try:
                for future in as_completed(futures, timeout=budget):
                    label = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        log.append({"connector": label, "count": 0, "reason": "error",
                                    "error": public_error(exc)})
                        continue
                    for record in result.get("records", []):
                        key = (record.url or "").strip().rstrip("/").lower()
                        if key and key in seen:
                            continue
                        if key:
                            seen.add(key)
                        record.round_found = round_no
                        records.append(record)
                    # web chain ek se zyada log entries deti hai (har tier ki apni)
                    log.extend(result.get("log", []))
            except FuturesTimeout:
                # Budget khatam. Jo bacha hai use CHUPKE se "0 results" mat banao —
                # ye "humne dekha hi nahi" hai, aur ye farak report tak jaana chahiye.
                spent = round(time.time() - started, 1)
                for future, label in futures.items():
                    if future.done():
                        continue
                    future.cancel()
                    log.append({
                        "connector": label, "count": 0, "reason": "deadline",
                        "error": f"{budget}s ka discovery budget khatam hua "
                                 f"({spent}s mein) — ye source is round mein "
                                 f"dekha hi nahi gaya",
                        "note": "", "seconds": spent,
                    })
        finally:
            # atke threads ka intezaar mat karo — unka result ab chahiye hi nahi
            pool.shutdown(wait=False, cancel_futures=True)

        return {
            "records": records,
            "log": log,
            "connectors_searched": sorted({entry.get("connector", "unknown")
                                           for entry in log}),
            "seen_urls": seen,
            "seconds": round(time.time() - started, 2),
            "budget_seconds": budget,
        }

    # ── honest reporting (Spec Section 2 + 13) ────────────────────────────────
    # "0 results mile" aur "search chali hi nahi" ek jaise report karna jhooth
    # hai — pehla matlab hai duniya mein kuch nahi mila, dusra matlab hai humne
    # dekha hi nahi (rate limit / key nahi / server slow / budget khatam). Live
    # test mein semantic_scholar aur google_books "khaali" dikh rahe the jabki
    # asli wajah rate limit aur missing country param thi.
    #
    # Isliye har log entry in 5 buckets mein se ek mein jaati hai:
    #   mile     — kuch mila
    #   khaali   — search sach mein chali aur kuch nahi mila
    #   chhanta  — mila tha, par HUMNE relevance guard se hataya (alag baat hai)
    #   ruka     — search hui hi nahi (rate_limited / blocked / timeout /
    #              no_key / deadline / no_query)
    #   fail     — code ya API error
    #
    # `no_query` patent batch mein juda: patent connector ko query se kaam ka
    # term chahiye (SPARQL FILTER banane ke liye). Term na bane to wo request
    # bhejta hi nahi. Bina ise list mein daale wo entry "khaali (search chali,
    # result 0)" bucket mein jaati thi — yaani hum keh rahe hote "EPO ne dekha,
    # kuch nahi mila", jabki EPO ko koi call hi nahi gayi.
    _STOPPED_REASONS = ("rate_limited", "blocked", "timeout", "no_key",
                        "deadline", "no_query")
    # human-readable wajah — jo user seedhe padhega
    _REASON_TEXT = {
        "rate_limited": "API ne rate limit lagayi",
        "blocked": "403, server ne mana kiya",
        "timeout": "server slow tha",
        "no_key": "API key nahi hai",
        "deadline": "time budget khatam",
        "no_query": "is sawaal se search-layak term nahi bana",
    }

    @classmethod
    def discovery_note(cls, log: List[Dict]) -> str:
        ok, empty, stopped, failed, filtered = [], [], [], [], []
        for entry in log:
            reason = entry.get("reason") or ""
            if entry.get("count"):
                ok.append(entry)
            elif reason in cls._STOPPED_REASONS:
                stopped.append(entry)
            elif reason == "filtered":
                filtered.append(entry)
            elif entry.get("error"):
                failed.append(entry)
            else:
                empty.append(entry)

        parts = []
        if ok:
            parts.append("mile: " + ", ".join(f"{e['connector']}({e['count']})" for e in ok))
        if empty:
            parts.append("khaali (search chali, result 0): " + ", ".join(
                e.get("connector", "unknown") for e in empty))
        if filtered:
            parts.append("chhaante gaye (result aaye par topic se door the): " + ", ".join(
                e.get("connector", "unknown") for e in filtered))
        if stopped:
            parts.append("ruka (search hi nahi hui): " + ", ".join(
                f"{e.get('connector', 'unknown')} "
                f"[{cls._REASON_TEXT.get(e.get('reason'), e.get('reason'))}]"
                for e in stopped))
        if failed:
            parts.append("fail: " + ", ".join(
                f"{e.get('connector', 'unknown')} [{str(e.get('error'))[:60]}]"
                for e in failed))

        note = " | ".join(parts) if parts else "koi connector nahi chala"
        # connector ke apne honest comments (e.g. "2 result relevance guard se hate")
        extras = [f"{e.get('connector')}: {e['note']}" for e in log if e.get("note")]
        return note + (" || " + " ; ".join(extras) if extras else "")
