"""
ContentFetcher — Spec Section 3, 4, 5 ka missing link

PEHLE KYA GALAT THA:
    `processing/` ke andar PDFProcessor, OCRProcessor, TranscriptProcessor aur
    DocumentProcessor bane pade the, par pipeline mein unhe koi call NAHI karta
    tha. Matlab system sources DHOONDHTA tha, unka snippet padhta tha, aur bas.
    Spec ka "books/papers/PDFs ko actually padho" wala hissa file ke roop mein
    maujood tha, kaam ke roop mein nahi. Ye module wahi khaali jagah bharta hai.

YE MODULE KYA KARTA HAI:
    Top-ranked sources mein se un par jaata hai jinka full text LEGALLY FREE
    hai, use download karta hai, processing/ ke through text nikaalta hai, aur
    question se sabse relevant hisse (locator ke saath) evidence pack mein daal
    deta hai. Isse source ka read_level "snippet" se "full_text" ho jaata hai.

SABSE ZAROORI RULE (Spec Section 2):
    > "Aisi copyrighted/paywalled saamagri ko bypass nahi karna hai jiski
    >  access anumati nahi hai."

    Isliye ye module ek *whitelist* par chalta hai, scraper nahi hai:

      * arXiv          → open-access preprint PDF
      * Internet Archive → sirf wo items jinka public djvu.txt maujood hai
      * Europe PMC     → sirf Open Access subset (isOpenAccess == "Y")
      * Wikipedia      → official REST/Action API ka plaintext extract
      * koi bhi direct .pdf link jo blocked publisher host par na ho

    Paywalled publishers (Elsevier, Springer, Wiley, JSTOR, IEEE, ACM, Nature,
    NEJM, Lancet...) aur wo sites jinki ToS scraping mana karti hai
    (ResearchGate, Academia.edu, Scribd) — inhe chhua bhi nahi jaata. Unke liye
    honest skip reason record hota hai jo final report mein dikhta hai.

QUOTA:
    Ye module Gemini ki EK BHI call nahi karta. Ye sirf network + time kharch
    karta hai, aur uska budget depth mode se aata hai (config.max_fulltext).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from typing import Dict, List, Optional
from urllib.parse import urlparse, quote

from .connectors.base import SLOW_TIMEOUT
from .models import EvidencePack, Passage, SourceRecord
from .quality_signals import (
    coi_from_full_text,
    funding_from_full_text,
    methodology_from_text,
    replication_status,
)

# ── budget / safety limits ───────────────────────────────────────────────────
# Timeout ek hi number (15s) tha — yaani search wala aadha system to patient
# tha (connect/read alag, retry ke saath), par PADHNE wala aadha impatient.
# Full text download search se BADA kaam hai (PDF/djvu.txt megabytes ke hote
# hain), isliye ise slow-source budget milta hai. Ye bhi usi env knob se chalta
# hai — CONNECTOR_READ_TIMEOUT badhane par reading bhi patient ho jaati hai.
_TIMEOUT = SLOW_TIMEOUT          # (connect, read) tuple

_MAX_BYTES = 4 * 1024 * 1024     # 4 MB — isse badi file skip (memory safety)
_MIN_USEFUL_CHARS = 400          # itne se kam mila to "full text" nahi kehna
_UA = ("InfinityResearchAI/1.0 (educational research project; "
       "contact: local user) python-requests")

# ── paywalled / ToS-restricted hosts — inhe kabhi fetch nahi karna ───────────
# Note: in mein se kuch par kuch articles open-access bhi hote hain, par host
# level par batana mushkil hai. Isliye conservative rehte hain: galti se
# paywall todne se accha hai ek source ka sirf abstract padhna.
_BLOCKED_HOSTS = {
    "sciencedirect.com", "elsevier.com", "springer.com", "link.springer.com",
    "springerlink.com", "wiley.com", "onlinelibrary.wiley.com",
    "tandfonline.com", "jstor.org", "sagepub.com", "journals.sagepub.com",
    "nature.com", "science.org", "sciencemag.org", "cell.com",
    "ieee.org", "ieeexplore.ieee.org", "acm.org", "dl.acm.org",
    "cambridge.org", "oup.com", "academic.oup.com", "thelancet.com",
    "nejm.org", "bmj.com", "jamanetwork.com", "ahajournals.org",
    "researchgate.net", "academia.edu", "scribd.com", "books.google.com",
    "play.google.com", "amazon.com", "chegg.com", "coursehero.com",
}

_BLOCK_REASON = ("paywalled/ToS-restricted publisher — spec ke rule ke hisaab se "
                 "bypass nahi kiya (sirf abstract level tak padha)")


def _host(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""


def _is_blocked(url: str) -> bool:
    host = _host(url)
    if not host:
        return True
    return any(host == b or host.endswith("." + b) for b in _BLOCKED_HOSTS)


# ── query relevance (excerpt chunna hai, poora document nahi bhejna) ─────────
_STOP = {
    "kya", "kyu", "kyun", "hai", "hain", "the", "and", "for", "with", "that",
    "this", "from", "what", "how", "why", "does", "can", "could", "would",
    "aur", "mein", "par", "koi", "kaise", "karta", "karte", "karna", "sakta",
    "sakti", "hota", "hoti", "wala", "wali", "bhi", "toh", "kar",
}


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-zऀ-ॿ]{4,}", (text or "").lower())
            if w not in _STOP}


class ContentFetcher:
    """
    Sources ka legally-free full text laao aur EvidencePack ko amir banao.

    Ek bhi exception bahar nahi jaati — har fail honest log line ban jaati hai,
    kyunki reading fail hona research fail hone ka kaaran nahi hona chahiye.
    """

    name = "content_fetcher"

    def __init__(self, allow_network: Optional[bool] = None):
        # .env se band kiya ja sakta hai: ALLOW_FULLTEXT_FETCH=false
        if allow_network is None:
            flag = os.getenv("ALLOW_FULLTEXT_FETCH", "true").strip().lower()
            allow_network = flag not in ("false", "0", "no", "off")
        self.allow_network = allow_network
        self.log: List[Dict] = []

    # ── lazy deps ────────────────────────────────────────────────────────────
    def _requests(self):
        import requests
        return requests

    def _processor(self):
        from .processing import DocumentProcessor
        return DocumentProcessor()

    # ── kaun sa URL padhne layak hai ─────────────────────────────────────────
    def resolve(self, source: SourceRecord) -> Dict:
        """
        Source ko dekh kar batao ki full text kahan se legally mil sakta hai.

        Returns {"ok": bool, "url": str, "kind": "pdf|txt|html|wikipedia",
                 "reason": str, "needs_lookup": str}
        `kind` batata hai ki bytes ko kis extension se save karna hai, taaki
        DocumentProcessor sahi processor chune.
        """
        url = (source.url or "").strip()
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "reason": "URL nahi hai (sirf metadata mila)"}

        host = _host(url)
        path = urlparse(url).path or ""

        # 1. Wikipedia — official API se saaf plaintext
        if host.endswith("wikipedia.org") and "/wiki/" in path:
            title = path.split("/wiki/", 1)[1]
            api = (f"https://{urlparse(url).netloc}/w/api.php?action=query&"
                   f"prop=extracts&explaintext=1&redirects=1&format=json&"
                   f"titles={title}")
            return {"ok": True, "url": api, "kind": "wikipedia",
                    "reason": "Wikipedia API plaintext extract"}

        # 2. arXiv — open access preprint
        if host.endswith("arxiv.org"):
            match = re.search(r"/(?:abs|pdf)/([^\s/?#]+?)(?:v\d+)?(?:\.pdf)?$", path)
            if match:
                return {"ok": True, "url": f"https://arxiv.org/pdf/{match.group(1)}",
                        "kind": "pdf", "reason": "arXiv open-access PDF"}
            return {"ok": False, "reason": "arXiv ID URL se nahi nikla"}

        # 3. Internet Archive — sirf public full-text items
        if host.endswith("archive.org") and "/details/" in path:
            identifier = path.split("/details/", 1)[1].strip("/").split("/")[0]
            if identifier:
                return {"ok": True,
                        "url": f"https://archive.org/download/{identifier}/{identifier}_djvu.txt",
                        "kind": "txt",
                        "reason": "Internet Archive public plain-text (djvu.txt)"}
            return {"ok": False, "reason": "archive.org identifier nahi mila"}

        # 4. PubMed Central — sirf Open Access subset (lookup ke baad)
        if "ncbi.nlm.nih.gov" in host and "PMC" in url.upper():
            match = re.search(r"(PMC\d+)", url, re.IGNORECASE)
            if match:
                pmcid = match.group(1).upper()
                return {"ok": True, "kind": "html",
                        "url": ("https://www.ebi.ac.uk/europepmc/webservices/rest/"
                                f"{pmcid}/fullTextXML"),
                        "reason": "Europe PMC Open Access full text"}
        if host.endswith("pubmed.ncbi.nlm.nih.gov"):
            match = re.search(r"/(\d{5,9})", path)
            if match:
                return {"ok": True, "kind": "html", "url": "",
                        "needs_lookup": match.group(1),
                        "reason": "Europe PMC se OA status check karna hai"}
            return {"ok": False, "reason": "PubMed ID URL se nahi nikla"}

        # 5. Blocked publishers — yahan rukna hi sahi hai
        if _is_blocked(url):
            return {"ok": False, "reason": _BLOCK_REASON}

        # 6. Koi bhi seedha open PDF link
        if path.lower().endswith(".pdf"):
            return {"ok": True, "url": url, "kind": "pdf",
                    "reason": "direct open PDF link"}

        # 7. DOI resolver — pata nahi kahan le jayega, aur zyada tar paywall par
        #    le jaata hai. Isliye nahi khol te (honesty > coverage).
        if host in ("doi.org", "dx.doi.org"):
            return {"ok": False,
                    "reason": "DOI link publisher par le jaata hai — paywall risk, "
                              "isliye nahi khola"}

        return {"ok": False,
                "reason": "is host ke liye koi bharosemand free full-text route "
                          "nahi hai (sirf snippet level tak padha)"}

    # ── Europe PMC OA lookup (PubMed ID → PMCID, sirf agar OA ho) ────────────
    def _europepmc_lookup(self, pmid: str) -> Dict:
        try:
            requests = self._requests()
            api = ("https://www.ebi.ac.uk/europepmc/webservices/rest/search"
                   f"?query=EXT_ID:{quote(pmid)}%20AND%20SRC:MED"
                   "&resultType=core&format=json&pageSize=1")
            resp = requests.get(api, headers={"User-Agent": _UA}, timeout=_TIMEOUT)
            data = resp.json()
            hits = (data.get("resultList") or {}).get("result") or []
            if not hits:
                return {"ok": False, "reason": "Europe PMC par record nahi mila"}
            hit = hits[0]
            pmcid = (hit.get("pmcid") or "").strip()
            is_oa = (hit.get("isOpenAccess") or "").upper() == "Y"
            if not pmcid:
                return {"ok": False, "reason": "PMC full text maujood nahi (sirf abstract)"}
            if not is_oa:
                return {"ok": False,
                        "reason": "PubMed record open-access nahi hai — full text "
                                  "nahi liya (paywall bypass mana hai)"}
            return {"ok": True, "kind": "html",
                    "url": ("https://www.ebi.ac.uk/europepmc/webservices/rest/"
                            f"{pmcid}/fullTextXML"),
                    "reason": f"Europe PMC OA full text ({pmcid})"}
        except Exception as exc:
            return {"ok": False, "reason": f"Europe PMC lookup fail: {type(exc).__name__}"}

    # ── download ─────────────────────────────────────────────────────────────
    def _download(self, url: str, kind: str, directory: str) -> Dict:
        """Bytes laao aur temp file mein likho. Size cap enforce hota hai."""
        out = {"ok": False, "path": "", "error": "", "bytes": 0}
        try:
            requests = self._requests()
        except Exception as exc:
            out["error"] = f"requests library nahi hai: {exc}"
            return out

        try:
            resp = requests.get(url, headers={"User-Agent": _UA}, timeout=_TIMEOUT,
                                stream=True, allow_redirects=True)
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
            return out

        try:
            if resp.status_code == 403:
                out["error"] = "403 — server ne access nahi diya (restricted content)"
                return out
            if resp.status_code == 404:
                out["error"] = "404 — is item ka free full text maujood nahi hai"
                return out
            if resp.status_code >= 400:
                out["error"] = f"HTTP {resp.status_code}"
                return out

            # Redirect ne kisi blocked publisher par pahuncha diya? Wahin ruko.
            final_url = str(getattr(resp, "url", url) or url)
            if _is_blocked(final_url):
                out["error"] = f"redirect {_host(final_url)} par gaya — {_BLOCK_REASON}"
                return out

            extension = {"pdf": ".pdf", "txt": ".txt", "html": ".html",
                         "wikipedia": ".json"}.get(kind, ".txt")
            path = os.path.join(directory, f"fetched_{abs(hash(url)) % 10**8}{extension}")

            size = 0
            with open(path, "wb") as handle:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > _MAX_BYTES:
                        out["error"] = (f"file {_MAX_BYTES // (1024 * 1024)}MB se badi "
                                        f"hai — skip (memory safety)")
                        handle.close()
                        return out
                    handle.write(chunk)

            out.update({"ok": size > 0, "path": path, "bytes": size})
            if not size:
                out["error"] = "khaali response mila"
            return out
        finally:
            try:
                resp.close()
            except Exception:
                pass

    # ── wikipedia JSON → plain text ──────────────────────────────────────────
    @staticmethod
    def _wikipedia_text(path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                data = json.load(handle)
            pages = ((data.get("query") or {}).get("pages") or {})
            texts = [(page.get("extract") or "") for page in pages.values()]
            return "\n\n".join(t for t in texts if t).strip()
        except Exception:
            return ""

    # ── excerpt chunna ───────────────────────────────────────────────────────

    # ── Spec Section 7 ke wo signals jo SIRF full text mein hote hain ────────
    # Ye jaan-boojh kar static + pure rakha hai: test ise seedhe text de kar
    # check kar sakta hai, bina network aur bina PDF ke.
    _METHODOLOGY_WINDOW = 3000

    @classmethod
    def signals_from_text(cls, text: str) -> Dict:
        """
        Full text se conflict-of-interest, funding, replication aur (agar
        pehle se pata na ho to) methodology nikalo.

        Ek zaroori faisla: methodology sirf pehle 3000 chars mein dhoondhte
        hain, poore document mein nahi. Kyunki ek systematic review apne
        discussion mein "randomized controlled trial" 50 baar likhta hai — poora
        text scan karne par wo review "RCT" ban jaata, jo galat upgrade hai.
        Shuruaat mein title + abstract hote hain, jahan study apna design khud
        batati hai.
        """
        body = str(text or "")
        return {
            "coi_disclosed": coi_from_full_text(body),
            "funding_disclosed": funding_from_full_text(body),
            # replication ka zikr poore text mein kahin bhi ho to maayne rakhta
            # hai (label bhi "zikr hai" hi kehta hai, "ho gaya" nahi)
            "replication": replication_status("", body),
            "methodology": methodology_from_text(body[: cls._METHODOLOGY_WINDOW]),
        }

    def best_excerpts(self, chunks: List[Dict], question: str,
                      budget_chars: int) -> List[Dict]:
        """
        Poora full text Gemini ko nahi bhejte (quota aur context dono limit
        hain). Question se sabse zyada milte-julte hisse chunte hain, taaki
        "padha" ka matlab "kaam ka hissa padha" ho.
        """
        query_words = _words(question)
        scored = []
        for index, chunk in enumerate(chunks):
            text = (chunk.get("text") or "").strip()
            if len(text) < 80:
                continue
            overlap = len(query_words & _words(text))
            # bilkul shuruaat (abstract/intro) ko halka bonus — wahan thesis hota hai
            position_bonus = 0.5 if index < 2 else 0.0
            scored.append((overlap + position_bonus, index, chunk))

        if not scored:
            return []
        scored.sort(key=lambda row: (-row[0], row[1]))
        picked: List[Dict] = []
        used = 0
        for score, _index, chunk in scored:
            if used >= budget_chars:
                break
            text = chunk["text"].strip()
            room = budget_chars - used
            if len(text) > room:
                text = text[:room].rsplit(" ", 1)[0] + " …"
            picked.append({"locator": chunk.get("locator", ""), "text": text,
                           "score": score})
            used += len(text)
        return picked

    # ── ek source padho ──────────────────────────────────────────────────────
    def read_source(self, source: SourceRecord, question: str,
                    budget_chars: int = 2400) -> Dict:
        """
        Ek source ka full text laane ki koshish karo.
        Kabhi raise nahi karta — {"ok": ..., "reason": ...} deta hai.
        """
        entry = {"source_id": source.source_id, "title": source.title[:70],
                 "url": source.url, "ok": False, "reason": "", "chars": 0,
                 "excerpts": []}

        if not self.allow_network:
            entry["reason"] = "full-text fetch .env se band hai (ALLOW_FULLTEXT_FETCH=false)"
            return entry

        plan = self.resolve(source)
        if plan.get("needs_lookup"):
            plan = self._europepmc_lookup(plan["needs_lookup"])
        if not plan.get("ok"):
            entry["reason"] = plan.get("reason", "koi free full-text route nahi")
            return entry

        directory = tempfile.mkdtemp(prefix="infinity_fetch_")
        try:
            downloaded = self._download(plan["url"], plan["kind"], directory)
            if not downloaded["ok"]:
                entry["reason"] = f"download fail: {downloaded['error']}"
                return entry

            if plan["kind"] == "wikipedia":
                text = self._wikipedia_text(downloaded["path"])
                if not text:
                    entry["reason"] = "Wikipedia API se extract khaali aaya"
                    return entry
                plain_path = os.path.join(directory, "wikipedia.txt")
                with open(plain_path, "w", encoding="utf-8") as handle:
                    handle.write(text)
                target = plain_path
            else:
                target = downloaded["path"]

            processed = self._processor().process(target, use_ocr=True)
            if not processed.get("ok"):
                entry["reason"] = f"processing fail: {processed.get('error', 'unknown')}"
                return entry

            text = processed.get("text") or ""
            if len(text) < _MIN_USEFUL_CHARS:
                entry["reason"] = (f"sirf {len(text)} chars mile — itne kam ko "
                                   f"'full text padha' nahi kehna chahiye")
                return entry

            excerpts = self.best_excerpts(processed.get("chunks") or [], question,
                                          budget_chars)
            if not excerpts:
                # chunks nahi bane par bhi text hai — seedha kaat lo
                excerpts = [{"locator": "", "text": text[:budget_chars], "score": 0}]

            entry.update({"ok": True, "chars": len(text), "excerpts": excerpts,
                          "reason": plan.get("reason", ""),
                          "notes": processed.get("notes", []),
                          "kind": processed.get("kind", plan["kind"]),
                          # Spec Section 7 — COI/funding sirf yahin pata chal
                          # sakte hain, kyunki abstract mein ye statements hoti
                          # hi nahi. Isliye full text padhne ka ek aur fayda.
                          "signals": self.signals_from_text(text)})
            return entry
        except Exception as exc:      # kabhi pipeline na todo
            entry["reason"] = f"unexpected: {type(exc).__name__}: {str(exc)[:120]}"
            return entry
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    # ── poora pack padho ─────────────────────────────────────────────────────
    def enrich(self, pack: EvidencePack, max_sources: int = 3,
               budget_chars: int = 2400) -> Dict:
        """
        Pack ke top sources ka full text laao aur unhe upgrade karo.

        Sirf `max_sources` tak jaate hain (depth mode ka budget), aur pehle un
        par jinka full text milne ki sambhavna zyada hai.
        """
        report = {"attempted": 0, "succeeded": 0, "failed": 0, "skipped": 0,
                  "chars_read": 0, "entries": [], "note": ""}
        if not pack.sources or max_sources <= 0:
            report["note"] = ("Full-text reading nahi chali — "
                              + ("koi source nahi tha." if not pack.sources
                                 else "is depth mode mein budget 0 hai."))
            return report

        # user ke apne documents pehle se poore process ho chuke hain
        candidates = [s for s in pack.sources
                      if s.source_type.value != "document"
                      and s.reading_level() != "full_text"]

        def priority(source: SourceRecord) -> tuple:
            plan = self.resolve(source)
            return (0 if plan.get("ok") or plan.get("needs_lookup") else 1,
                    0 if source.full_text_available else 1,
                    -source.combined_score)

        candidates.sort(key=priority)
        report["skipped"] = max(0, len(candidates) - max_sources)

        for source in candidates[:max_sources]:
            report["attempted"] += 1
            entry = self.read_source(source, pack.question, budget_chars)
            report["entries"].append(entry)
            self.log.append(entry)

            if not entry["ok"]:
                report["failed"] += 1
                continue

            report["succeeded"] += 1
            report["chars_read"] += entry["chars"]

            # source ko honestly upgrade karo
            source.read_level = "full_text"
            source.full_text_chars = entry["chars"]
            source.full_text_available = True

            # Spec Section 7 — jo signals sirf full text mein milte hain, unhe
            # ab record par likh do. Jo field connector pehle se bhar chuka hai
            # (API ka structured data) use overwrite NAHI karte; COI/funding ke
            # liye None se True/False par jaana upgrade hai, isliye wo lagte hain.
            signals = entry.get("signals") or {}
            if signals.get("coi_disclosed") is not None:
                source.coi_disclosed = signals["coi_disclosed"]
            if signals.get("funding_disclosed") is not None:
                source.funding_disclosed = signals["funding_disclosed"]
            if signals.get("replication") and not source.replication:
                source.replication = signals["replication"]
            if signals.get("methodology") and not source.methodology:
                source.methodology = signals["methodology"]

            combined = []
            for excerpt in entry["excerpts"]:
                locator = excerpt.get("locator") or ""
                prefix = f"[{locator}] " if locator else ""
                combined.append(prefix + excerpt["text"])
                pack.passages.append(Passage(
                    source_id=source.source_id,
                    text=excerpt["text"],
                    locator=locator,
                ))
            # snippet ko full-text excerpt se badlo, taaki Gemini asli content
            # dekhe — warna download ka koi fayda hi nahi
            source.snippet = "\n\n".join(combined)[: budget_chars + 200]
            if entry["excerpts"] and entry["excerpts"][0].get("locator"):
                source.locator = entry["excerpts"][0]["locator"]

        report["note"] = self.reading_note(report)
        return report

    # ── honest note ──────────────────────────────────────────────────────────
    @staticmethod
    def reading_note(report: Dict) -> str:
        if not report.get("attempted"):
            return report.get("note", "Full-text reading nahi chali.")
        bits = [f"{report['succeeded']}/{report['attempted']} sources ka full text "
                f"padha gaya (~{report['chars_read']:,} chars)"]
        if report.get("skipped"):
            bits.append(f"{report['skipped']} sources budget ke bahar the (sirf "
                        f"snippet/abstract level tak padhe gaye)")
        reasons: Dict[str, int] = {}
        for entry in report.get("entries", []):
            if not entry.get("ok"):
                key = (entry.get("reason") or "unknown")[:90]
                reasons[key] = reasons.get(key, 0) + 1
        if reasons:
            top = sorted(reasons.items(), key=lambda kv: -kv[1])[:3]
            bits.append("jo nahi padhe ja sake: "
                        + "; ".join(f"{reason} ({count})" for reason, count in top))
        return " | ".join(bits)
