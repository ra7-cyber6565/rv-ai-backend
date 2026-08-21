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

from .connectors import (BaseConnector, BookConnector, DatasetConnector,
                         PaperConnector, WebConnector)
from .models import SourceRecord
from .network_safety import public_error


class SourceDiscovery:
    # Agar caller budget na de to itna (DEEP ka default) maan lo
    DEFAULT_BUDGET_SECONDS = 90

    def __init__(self, max_workers: int = 6):
        self.web = WebConnector()
        self.papers = PaperConnector()
        self.books = BookConnector()
        self.datasets = DatasetConnector()
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

        for name in plan.get("papers", []):
            connector = self.papers.by_name(name)
            if connector:
                for q in queries:
                    tasks.append((connector.name,
                                  self._single(connector, q, max_per_connector)))

        for name in plan.get("books", []):
            connector = self.books.by_name(name)
            if connector:
                tasks.append((connector.name,
                              self._single(connector, primary, max_per_connector)))

        # Datasets (Spec Section 2 + 11) — books ki tarah PRIMARY query par hi
        # chalte hain, taaki discovery budget safe rahe. Ye raw data locate karte
        # hain jispar claims tikte hain (verification ke liye zaroori).
        for name in plan.get("datasets", []):
            connector = self.datasets.by_name(name)
            if connector:
                tasks.append((connector.name,
                              self._single(connector, primary, max_per_connector)))

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
                  "datasets": [names]}
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
    #              no_key / deadline)
    #   fail     — code ya API error
    _STOPPED_REASONS = ("rate_limited", "blocked", "timeout", "no_key", "deadline")
    # human-readable wajah — jo user seedhe padhega
    _REASON_TEXT = {
        "rate_limited": "API ne rate limit lagayi",
        "blocked": "403, server ne mana kiya",
        "timeout": "server slow tha",
        "no_key": "API key nahi hai",
        "deadline": "time budget khatam",
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
