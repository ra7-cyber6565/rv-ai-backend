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
from .network_safety import (
    NetworkSafetyError,
    declared_length,
    public_error,
    read_bounded_response,
    require_content_type,
    safe_get_with_redirects,
    validate_public_http_url,
)
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

# §12 — byte-size par file "unusable" nahi hoti.
#
# PEHLE: `_MAX_BYTES = 4 MB` aur usse badi file par seedha
#        "skip (memory safety)". Yaani 20 MB ka review ya 100 MB ki thesis
#        kabhi padhi hi nahi jaati thi.
# AB:    4 MB tak → poora document normal path se.
#        4 MB se badi → download hoti hai, par PAGE-BY-PAGE stream hoti hai
#        (processing/pdf_chunker.py): relevance se kaam ke pages chune jaate
#        hain, poora text kabhi memory mein nahi aata.
#        `_HARD_MAX_BYTES` sirf disk/bandwidth ki aakhri deewar hai — env
#        `MAX_FETCH_MB` se badhaya ja sakta hai.
_LARGE_BYTES = 4 * 1024 * 1024           # isse badi = streaming path


def _hard_cap_bytes() -> int:
    try:
        mb = float(os.getenv("MAX_FETCH_MB", "120").strip() or 120)
    except Exception:
        mb = 120.0
    return int(max(4.0, mb) * 1024 * 1024)


# Purana naam zinda rakha gaya hai (koi bhi purana caller/test na toote), par
# iska matlab badal gaya: ye "skip" ki line nahi, "streaming path" ki line hai.
_MAX_BYTES = _LARGE_BYTES
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
        try:
            # DNS/network yahan nahi chalta; private literals, localhost-style
            # names, credentials and unsafe ports still fail before routing.
            validate_public_http_url(url, resolve_dns=False)
        except NetworkSafetyError:
            return {"ok": False, "reason": "unsafe/private network URL blocked"}

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
        resp = None
        try:
            requests = self._requests()
            api = ("https://www.ebi.ac.uk/europepmc/webservices/rest/search"
                   f"?query=EXT_ID:{quote(pmid)}%20AND%20SRC:MED"
                   "&resultType=core&format=json&pageSize=1")
            resp, _final_url = safe_get_with_redirects(
                requests,
                api,
                headers={"User-Agent": _UA},
                timeout=_TIMEOUT,
                stream=True,
                allowed_hosts={"www.ebi.ac.uk", "ebi.ac.uk"},
                resolve_dns=False,
                max_redirects=2,
            )
            status = int(getattr(resp, "status_code", 200) or 200)
            if status >= 400:
                return {"ok": False, "reason": f"Europe PMC lookup HTTP {status}"}
            require_content_type(resp, "json")
            read_bounded_response(resp, 1024 * 1024)
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
            return {"ok": False, "reason": f"Europe PMC lookup fail: {public_error(exc)}"}
        finally:
            try:
                if resp is not None:
                    resp.close()
            except Exception:
                pass

    # ── download ─────────────────────────────────────────────────────────────
    def _download(self, url: str, kind: str, directory: str) -> Dict:
        """
        Bytes laao aur temp file mein likho.

        §12: yahan se "4 MB se badi = skip" hat gaya hai. Ab do cheezein hoti
        hain — file `large` mark ho jaati hai (aage streaming reading chalegi),
        aur sirf HARD cap par (default 120 MB, `MAX_FETCH_MB` se badalta hai)
        download rukta hai. Wo cap disk/bandwidth ki deewar hai, "ye document
        bekaar hai" ka faisla nahi.
        """
        out = {"ok": False, "path": "", "error": "", "bytes": 0, "large": False}
        try:
            requests = self._requests()
        except Exception:
            out["error"] = "HTTP client available nahi hai"
            return out

        try:
            resp, final_url = safe_get_with_redirects(
                requests,
                url,
                headers={"User-Agent": _UA},
                timeout=_TIMEOUT,
                stream=True,
                # Full-text URLs came from untrusted discovery results: resolve
                # every original/redirect host and reject any non-global answer.
                resolve_dns=True,
            )
        except Exception as exc:
            out["error"] = public_error(exc)
            return out

        path = ""
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
            if _is_blocked(final_url):
                out["error"] = f"redirect {_host(final_url)} par gaya — {_BLOCK_REASON}"
                return out

            try:
                require_content_type(resp, kind)
            except NetworkSafetyError as exc:
                out["error"] = public_error(exc)
                return out

            extension = {"pdf": ".pdf", "txt": ".txt", "html": ".html",
                         "wikipedia": ".json"}.get(kind, ".txt")
            path = os.path.join(directory, f"fetched_{abs(hash(url)) % 10**8}{extension}")

            size = 0
            hard_cap = _hard_cap_bytes()
            stated = declared_length(resp)
            if stated is not None and stated > hard_cap:
                out["error"] = (
                    f"file {hard_cap // (1024 * 1024)}MB (MAX_FETCH_MB) se "
                    f"bhi badi hai — download roka gaya")
                return out
            with open(path, "wb") as handle:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > hard_cap:
                        # Ye "badi file" ka reject nahi hai — ye disk/bandwidth
                        # ki aakhri deewar hai. Badhani ho to MAX_FETCH_MB.
                        out["error"] = (
                            f"file {hard_cap // (1024 * 1024)}MB (MAX_FETCH_MB) se "
                            f"bhi badi hai — download roka gaya")
                        try:
                            os.unlink(path)
                        except OSError:
                            pass
                        return out
                    handle.write(chunk)

            # Content-Type can be absent or occasionally generic.  A PDF must
            # still carry the PDF magic bytes; HTML/JSON/text must not be a
            # binary/NUL-filled payload masquerading as research text.
            try:
                with open(path, "rb") as check_handle:
                    prefix = check_handle.read(64)
            except OSError:
                prefix = b""
            if kind == "pdf" and not prefix.startswith(b"%PDF-"):
                out["error"] = "downloaded file valid PDF nahi thi"
                try:
                    os.unlink(path)
                except OSError:
                    pass
                return out
            if kind in {"txt", "html", "wikipedia"} and b"\x00" in prefix:
                out["error"] = "downloaded response text document nahi thi"
                try:
                    os.unlink(path)
                except OSError:
                    pass
                return out

            out.update({"ok": size > 0, "path": path, "bytes": size,
                        "large": size > _LARGE_BYTES})
            if not size:
                out["error"] = "khaali response mila"
            return out
        except Exception as exc:
            out["error"] = public_error(exc)
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
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

            processed = self._processor().process(
                target, use_ocr=True, question=question,
                size_bytes=int(downloaded.get("bytes") or 0),
                large=bool(downloaded.get("large")))
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
                          "bytes": int(downloaded.get("bytes") or 0),
                          # §12 — badi file streaming (page-by-page) se padhi
                          # gayi ya poori? Report mein yahi farak imaandaari se
                          # dikhna chahiye.
                          "streamed": bool(processed.get("streamed")),
                          "selection": processed.get("selection") or {},
                          # Spec Section 7 — COI/funding sirf yahin pata chal
                          # sakte hain, kyunki abstract mein ye statements hoti
                          # hi nahi. Isliye full text padhne ka ek aur fayda.
                          "signals": self.signals_from_text(text)})
            return entry
        except Exception as exc:      # kabhi pipeline na todo
            entry["reason"] = f"unexpected fetch failure: {public_error(exc)}"
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

            # §12 — agar file badi thi aur page-by-page padhi gayi, to yahan
            # likh do ki kitne pages mein se kaun chune gaye. read_level
            # "full_text" hi rehta hai (download + process asli mein hua), par
            # ab uske saath scope ki line bhi chalti hai, taaki report ya model
            # "poora 300-page document padh liya" na samjhe.
            selection = entry.get("selection") or {}
            if entry.get("streamed") and selection:
                source.read_note = selection.get("note", "") or ""
                source.pages_read = int(selection.get("pages_kept") or 0)
                source.pages_total = int(selection.get("pages_total") or 0)

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

            # The source object has just been upgraded to full_text. Any
            # passage captured before this successful read still represents the
            # old snippet/abstract depth, so it must not survive as if it were a
            # full-text passage. Keep other sources untouched.
            pack.passages[:] = [
                passage for passage in pack.passages
                if passage.source_id != source.source_id
            ]

            combined = []
            for excerpt in entry["excerpts"]:
                locator = excerpt.get("locator") or ""
                prefix = f"[{locator}] " if locator else ""
                combined.append(prefix + excerpt["text"])
                pack.passages.append(Passage(
                    source_id=source.source_id,
                    text=excerpt["text"],
                    locator=locator,
                    provenance="full_text_excerpt",
                    read_level_at_capture=source.reading_level(),
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

        # §12 — badi files ka hisaab alag se, kyunki inka "full text padha" ka
        # matlab "chune hue pages padhe" hai. Ye farak chhupana hi purana bug tha.
        streamed = [e for e in report.get("entries", [])
                    if e.get("ok") and e.get("streamed")]
        if streamed:
            kept = sum(int((e.get("selection") or {}).get("pages_kept") or 0)
                       for e in streamed)
            total = sum(int((e.get("selection") or {}).get("pages_total") or 0)
                        for e in streamed)
            piece = (f"{len(streamed)} badi file page-by-page padhi gayi "
                     f"(4MB+ file ab skip nahi hoti)")
            if total:
                piece += (f": {total} pages mein se sawaal se sabse milte-julte "
                          f"{kept} pages process hue — poora document padha gaya "
                          f"aisa dava nahi hai")
            bits.append(piece)
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
