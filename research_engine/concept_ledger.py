"""ConceptLedger — jo naam app ne KHUD pehchana, wo agli baar yaad rahe.

Kyun: intel ki shart thi — "mene jitne bhi topic mathmetic ya jo bhi books
vegyanik ka naam btaya h sirf unhe hi mt add krna, aesi hi or bhi topic honge
book hongi scintist honge unke baare me app khud se soch reserch kr ske waisa
bhi bnana". Static list badhane se ye kaam kabhi poora nahi hota. Isliye ye
module wo naam yaad rakhta hai jo pipeline ne khud dekhe:

  * sawaal me jab cue mila ("ibn khaldun ki book muqaddimah me...") → us baar
    classics.py ne "muqaddimah" (kriti) aur "ibn khaldun" (vyakti) nikaal liye.
  * agli baar bina cue wale sawaal ("muqaddimah me sabhyata ka chakra") par
    static rule kuch nahi nikaal paate — ledger unhe pehchan kar lane khol deta
    hai. Yahi "badhta hua" hissa hai.

TEEN HARD NIYAM (inhe tests aur mutation harness pakadte hain):

  1. **Ye evidence nahi hai.** Har entry aur har hint par ``verified`` PAKKA
     False hai — ise True karne ka koi setter is module me nahi hai. Naam yaad
     rakhna us naam ke baare me kuch saabit karna nahi hai. Isliye ledger se
     kabhi koi claim, confidence, ya evidence level nahi banta.
  2. **Sirf jodta hai, kabhi kaatta nahi.** Hint se lane KHULTI hai, band kabhi
     nahi hoti; base plan ki ek bhi query hint ke baad gayab nahi hoti. Galat
     yaad ka nuksaan is tarah zyada-se-zyada ek bekaar search query hai.
  3. **Jo static list se pehle hi nikal aata hai, wo yaad nahi rakha jaata.**
     "granth", "book", "dharm", "summary" jaise aam shabd ledger me ghus jaayein
     to ledger khud ko zeher de leta hai (har sawaal par galat lane). Admission
     filter unhe rok deta hai.

Kharcha: 0 model call, 0 network. Storage ek chhoti JSON file — koi DB nahi.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from typing import Dict, Iterable, List, Optional, Sequence

from . import classics as CL
from . import lenses as L
from utils.process_lock import ExclusiveProcessFileLock, ProcessLockError


# ── shabdkosh: entry me kya-kya reh sakta hai ────────────────────────────────
SCHEMA_VERSION = 1

KIND_WORK = "work"          # kriti/granth/book jaisa naam
KIND_PERSON = "person"      # lekhak/vichaarak/vaigyanik
KINDS = (KIND_WORK, KIND_PERSON)

LANE_PRIMARY = "primary_text"   # mool text dhoondhna chahiye
LANE_SUMMARY = "summary"        # summary/vyakhya lane (copyright book ka raasta)
LANES = (LANE_PRIMARY, LANE_SUMMARY)

# Ek hi baar dekha hua naam lane nahi kholta. Do alag mauke chahiye — warna ek
# tukka poori aage ki research ko kheech leta hai.
MIN_CONFIRM = 2
# Ledger file bandhi hui rehni chahiye (laptop/Railway dono par).
MAX_CONCEPTS = 800
# ``MAX_CONCEPTS`` akela byte-bound nahi hai: ek bahut lamba title poori JSON
# file ko phula sakta tha. Dono limits milkar laptop/Railway store ko bounded
# rakhte hain, bina kisi normal multilingual kriti/vyakti naam ko kaate.
MAX_CONCEPT_CHARS = 160
MAX_LEDGER_BYTES = 2 * 1024 * 1024
MAX_PENDING_EVENTS = MAX_CONCEPTS * 4
_MAX_ORIGINS = 6
_MAX_HINTS = 6
_MAX_WORDS_IN_CONCEPT = 4
_MIN_CONCEPT_LEN = 4

# Ye string har hint ke saath jaati hai. Iska kaam ek hi hai: report/audit me
# ledger ko galti se evidence ki tarah padha na ja sake.
NOT_EVIDENCE = (
    "ledger_hint_only__remembered_search_lead_not_evidence_and_no_text_was_read"
)
LEDGER_NOTE = (
    "ledger ne ye naam pichhli research se yaad rakha tha (app ne khud pehchana "
    "tha) — ye sirf search hint hai, iska matlab ye NAHI hai ki is naam ke baare "
    "me kuch padha ya saabit hua"
)


# ── admission filter: kaun sa naam yaad rakhne laayak hai ───────────────────

def _clean(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _key(concept: object) -> str:
    return _clean(concept).casefold()


def _is_derivable(word: str) -> bool:
    """Ye shabd static rule se pehle hi nikal aata hai (isliye yaad rakhna bekaar)?

    Do jagah se: (a) classics.py ka generic text/read/summary shabd
    ("granth", "book", "padho", "summary"), (b) lenses.py ka tradition marker
    ("dharm", "veda" jaisa parampara-shabd jo pehle se marker list me hai).

    Ye "list se azaadi" ka ulta nahi, uska hi hissa hai: ledger sirf WO yaad
    rakhta hai jo kisi list me nahi tha.
    """
    low = _key(word)
    if not low:
        return True
    if CL.is_generic_text_word(low):
        return True
    if CL.is_question_word(low):
        return True
    try:
        if L.tradition_hits(low):
            return True
    except Exception:                                  # pragma: no cover
        pass
    return False


def admission_reason(concept: object) -> str:
    """Khaali string = andar aa sakta hai. Warna reject ki NAAMIT wajah.

    Wajah naam ke saath wapas aati hai taaki test/audit me pata chale ki kis
    niyam ne roka (silently drop karna sabse buri baat hoti — probe me pakda
    nahi jaata).
    """
    text = _clean(concept)
    if not text:
        return "empty"
    words = [w for w in re.split(r"\s+", text) if w]
    if len(words) > _MAX_WORDS_IN_CONCEPT:
        return "too_many_words"
    if len(text) > MAX_CONCEPT_CHARS:
        return "too_long"
    if len(text) < _MIN_CONCEPT_LEN:
        return "too_short"
    if re.search(r"https?://|www\.", text, re.I):
        return "looks_like_url"
    if not any(ch.isalpha() for ch in text):
        return "no_letters"
    # Phrase ke kinaare matlab-wale hone chahiye: "of medicine" jaisa tukda
    # naam nahi hai. Beech me stopword chalega ("canon of medicine").
    edges = [words[0], words[-1]]
    for edge in edges:
        bare = edge.strip("-'\".,:;()[]")
        if len(bare) < 3:
            return "edge_too_short"
        if L.is_stopword(bare):
            return "edge_stopword"
        if _is_derivable(bare):
            return "already_derivable"
    if all(_is_derivable(w.strip("-'\"")) or L.is_stopword(w.strip("-'\""))
           for w in words):
        return "already_derivable"
    return ""


def is_admissible(concept: object) -> bool:
    return admission_reason(concept) == ""


# ── naam nikaalne ke chhote helper (source title / corpus) ───────────────────

def _dict_stance_kwargs(record: dict) -> Dict:
    """dict-jaisa record ho to classics ko naamit fields do (guess nahi)."""
    return {"url": str(record.get("url") or ""),
            "title": str(record.get("title") or ""),
            "year": record.get("year"),
            "publisher": str(record.get("publisher") or ""),
            "source_type": str(record.get("source_type") or ""),
            "licence": str(record.get("licence") or record.get("license") or "")}


def _title_concept(title: str) -> str:
    """Title se kriti ka naam. Subtitle kaat kar, kinaare saaf kar ke.

    Zyada chalaaki nahi ki gayi: agar poora phrase admission filter paar nahi
    karta to kinaare se ek-ek shabd chhoda jaata hai, aur phir bhi na bane to
    kuch bhi yaad nahi kiya jaata. Kuch na seekhna galat seekhne se behtar hai.
    """
    head = re.split(r"[:;(\[—]|\s+-\s+", _clean(title))[0]
    words = [w for w in re.split(r"\s+", re.sub(r"[\"'’]", "", head)) if w]
    words = [w.strip(".,") for w in words if w.strip(".,")]
    while words and len(words) > _MAX_WORDS_IN_CONCEPT:
        words = words[:_MAX_WORDS_IN_CONCEPT]
    while words:
        candidate = " ".join(words)
        if is_admissible(candidate):
            return candidate
        if len(words) == 1:
            return ""
        # kinaare hi rejection ki wajah hote hain — pehle aage se, phir peeche se
        if admission_reason(candidate) in ("edge_stopword", "edge_too_short",
                                           "already_derivable"):
            if not is_admissible(" ".join(words[1:])):
                words = words[:-1]
            else:
                words = words[1:]
            continue
        return ""
    return ""


def _corpus_people(records: Sequence[object]) -> List[str]:
    """Corpus me BAAR-BAAR aaya lekhak naam (lenses ka apna niyam)."""
    try:
        found = L.author_thinkers(list(records or []), min_repeat=2)
    except Exception:                                      # pragma: no cover
        return []
    return [name for name in found if is_admissible(name)][:_MAX_HINTS]


def _lookup_phrases(question: str) -> List[str]:
    """Sawaal ke wo tukde jinse ledger me dhoondha jaayega.

    Ek shabd se le kar chaar shabd tak ke run. Lambe run PEHLE dekhe jaate
    hain, taaki "canon of medicine" mil jaane par akela "canon" na uthe.
    """
    try:
        words = [w.strip("-'\".,:;()[]") for w in L.tokens(question)]
    except Exception:                                      # pragma: no cover
        words = re.findall(r"[\w']+", str(question or "").lower())
    words = [w for w in words if w]
    out: List[str] = []
    seen = set()
    for span in range(_MAX_WORDS_IN_CONCEPT, 0, -1):
        for index in range(0, max(0, len(words) - span + 1)):
            phrase = " ".join(words[index:index + span])
            low = _key(phrase)
            if low in seen:
                continue
            seen.add(low)
            out.append(phrase)
    return out


def _merge_lists(base: object, extra: object, limit: int = 8) -> List[str]:
    """base + extra, base ka kramm aur poora content bacha kar.

    Ye function ledger ka "sirf jodo" niyam hai: base ka ek bhi item kabhi
    nahi girta, extra sirf peeche judta hai, aur limit base se chhoti ho to
    bhi base poora rehta hai (warna hint base ko kaat deta).
    """
    kept: List[str] = []
    seen = set()
    for item in list(base or []) + list(extra or []):
        text = _clean(item)
        if not text:
            continue
        low = text.casefold()
        if low in seen:
            continue
        seen.add(low)
        kept.append(text)
    if len(kept) <= limit:
        return kept
    base_len = len({_clean(i).casefold() for i in (base or []) if _clean(i)})
    return kept[:max(limit, base_len)]


# ── storage ─────────────────────────────────────────────────────────────────

def _default_dir() -> str:
    """Wahi jagah jahan ResearchMemory rehti hai, uske andar apna folder.

    Naya env var nahi banaya — jo laptop par ``INFINITY_DATA_ROOT`` set karta
    hai, uske andar hi ye file bhi chali jaati hai (C: na bhare, wahi niyam).
    """
    configured = str(os.getenv("CONCEPT_LEDGER_DIR", "")).strip()
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    base = str(os.getenv("RESEARCH_MEMORY_DIR", "")).strip()
    if not base:
        try:
            from utils.storage_paths import ensure_layout
            base = ensure_layout()["research_memory"]
        except Exception:
            base = os.path.abspath("./research_memory")
    return os.path.join(os.path.abspath(os.path.expanduser(base)),
                        "concept_ledger")


def _today() -> str:
    return time.strftime("%Y-%m-%d")


class ConceptLedger:
    """Badhta hua concept ledger. Poora file-based, ₹0, model-free.

    Do taraf ka kaam: ``observe_*`` yaad rakhta hai, ``hints``/``lane_plan``
    yaad hui cheez ko WAPAS DETA hai — hamesha hint ke roop me.
    """

    def __init__(self, directory: Optional[str] = None,
                 filename: str = "concepts.json"):
        self.directory = os.path.abspath(directory or _default_dir())
        self.filename = filename or "concepts.json"
        self._data: Optional[Dict] = None
        # Ek process ke threads ko serialise karta hai; alag processes ke liye
        # neeche OS-backed ``ExclusiveProcessFileLock`` hai.
        self._thread_lock = threading.RLock()
        # ``learn`` ke baad ke sirf naye increments. Save latest on-disk JSON
        # par in events ko replay karta hai, isliye stale worker kisi doosre
        # worker ka concept/count overwrite nahi kar sakta.
        self._pending_events: List[Dict] = []
        self._pending_clear = False
        self._disk_signature: Optional[tuple[int, int]] = None

    @property
    def path(self) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", self.filename)
        return os.path.join(self.directory, safe)

    @property
    def lock_path(self) -> str:
        return f"{self.path}.lock"

    def _blank(self) -> Dict:
        return {"version": SCHEMA_VERSION, "concepts": {}}

    def _fingerprint(self) -> Optional[tuple[int, int]]:
        try:
            stat = os.stat(self.path)
            return int(stat.st_mtime_ns), int(stat.st_size)
        except OSError:
            return None

    def _read_disk(self) -> Dict:
        """Bounded, sanitised disk read. Koi error ho to khaali ledger."""
        data = self._blank()
        try:
            if os.path.getsize(self.path) > MAX_LEDGER_BYTES:
                return data
            with open(self.path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if isinstance(raw, dict) and isinstance(raw.get("concepts"), dict):
                clean: Dict[str, Dict] = {}
                for key, entry in raw["concepts"].items():
                    fixed = self._sanitise(key, entry)
                    if fixed:
                        clean[_key(key)] = fixed
                data = {"version": SCHEMA_VERSION, "concepts": clean}
        except Exception:
            data = self._blank()
        return data

    def load(self) -> Dict:
        """File corrupt/gayab ho to khaali ledger — research kabhi nahi rukti.

        Shared instance ab file ko hamesha ke liye cache nahi karta. Kisi doosre
        worker ne save kiya ho to fingerprint badalte hi taaza data reload hota
        hai. Apne pending events ke dauran reload nahi hota; save unhe latest
        disk state par merge karega.
        """
        with self._thread_lock:
            current = self._fingerprint()
            if self._data is not None:
                if self._pending_events or self._pending_clear:
                    return self._data
                if current == self._disk_signature:
                    return self._data
            self._data = self._read_disk()
            self._disk_signature = current
            return self._data

    def _sanitise(self, key: str, entry: object) -> Optional[Dict]:
        """Disk se aaya entry apne hi schema me laao.

        Koi bhi file (haath se badli hui bhi) ``verified: true`` likh de to wo
        yahan MAAN nahi liya jaata — ledger ke liye verified ka ek hi maan hai:
        False. Ye niyam code me hai, file me nahi.
        """
        if not isinstance(entry, dict):
            return None
        concept = _clean(entry.get("concept") or key)
        if not concept or not is_admissible(concept):
            return None
        kinds = {k: int(v) for k, v in (entry.get("kinds") or {}).items()
                 if k in KINDS and isinstance(v, (int, float)) and v > 0}
        lanes = {k: int(v) for k, v in (entry.get("lanes") or {}).items()
                 if k in LANES and isinstance(v, (int, float)) and v > 0}
        if not kinds:
            return None
        origins = [str(o)[:60] for o in (entry.get("origins") or [])][:_MAX_ORIGINS]
        seen = entry.get("seen")
        return {
            "concept": concept,
            "kinds": kinds,
            "lanes": lanes,
            "origins": origins,
            "first_seen": str(entry.get("first_seen") or _today())[:10],
            "last_seen": str(entry.get("last_seen") or _today())[:10],
            "seen": int(seen) if isinstance(seen, (int, float)) and seen > 0 else 1,
            "verified": False,
        }

    def _prune(self, concepts: Dict[str, Dict]) -> Dict[str, Dict]:
        """Ledger bandha hua rahe. Sabse kam kaam ka pehle jaata hai.

        Kramm: pehle jo zyada baar dikha (seen), phir jo haal me dikha
        (last_seen). Yaani ek purana par baar-baar mila naam bacha rehta hai,
        aur ek baar dikha kar bhoola hua naam nikal jaata hai.
        """
        if len(concepts) <= MAX_CONCEPTS:
            return concepts
        ranked = sorted(concepts.items(),
                        key=lambda pair: (int(pair[1].get("seen") or 0),
                                          str(pair[1].get("last_seen") or "")),
                        reverse=True)
        return dict(ranked[:MAX_CONCEPTS])

    def _apply_event(self, data: Dict, event: Dict) -> None:
        """Ek pehle-se-validated learning event ko ``data`` par lagao."""
        text = event["concept"]
        concepts = data.setdefault("concepts", {})
        entry = concepts.get(_key(text))
        if not entry:
            entry = {"concept": text, "kinds": {}, "lanes": {}, "origins": [],
                     "first_seen": event["date"], "last_seen": event["date"],
                     "seen": 0, "verified": False}
            concepts[_key(text)] = entry
        kind = event["kind"]
        entry["kinds"][kind] = int(entry["kinds"].get(kind, 0)) + 1
        lane = event.get("lane") or ""
        if lane:
            entry["lanes"][lane] = int(entry["lanes"].get(lane, 0)) + 1
        origin = event.get("origin") or ""
        if origin:
            tag = str(origin)[:60]
            if tag not in entry["origins"]:
                entry["origins"] = ([*entry["origins"], tag])[-_MAX_ORIGINS:]
        entry["seen"] = int(entry.get("seen") or 0) + 1
        entry["last_seen"] = event["date"]
        entry["verified"] = False

    def _write_atomic(self, data: Dict) -> None:
        os.makedirs(self.directory, exist_ok=True)
        handle, tmp = tempfile.mkstemp(prefix="ledger_", suffix=".json",
                                       dir=self.directory)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            if os.path.getsize(tmp) > MAX_LEDGER_BYTES:
                raise ValueError("concept ledger exceeds bounded byte limit")
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def _acquire_process_lock(self) -> Optional[ExclusiveProcessFileLock]:
        """Chhota bounded retry: contention data-loss nahi, sirf deferred save."""
        lock = ExclusiveProcessFileLock(self.lock_path)
        for attempt in range(25):
            try:
                lock.acquire()
                return lock
            except ProcessLockError:
                if attempt == 24:
                    return None
                time.sleep(0.02)
            except Exception:
                # Read-only/broken runtime root: ledger fail-safe rehta hai;
                # caller ko False milta hai, research answer nahi rukta.
                return None
        return None                                                    # pragma: no cover

    def save(self) -> bool:
        """Cross-process merge + atomic replace; failure par pending events bachte hain."""
        with self._thread_lock:
            self.load()
            lock = self._acquire_process_lock()
            if lock is None:
                return False
            try:
                latest = self._blank() if self._pending_clear else self._read_disk()
                for event in self._pending_events:
                    self._apply_event(latest, event)
                latest["concepts"] = self._prune(
                    dict(latest.get("concepts") or {}))
                self._write_atomic(latest)
                self._data = latest
                self._pending_events.clear()
                self._pending_clear = False
                self._disk_signature = self._fingerprint()
                return True
            except Exception:
                return False
            finally:
                lock.release()

    def clear(self) -> bool:
        with self._thread_lock:
            self._data = self._blank()
            self._pending_events.clear()
            self._pending_clear = True
            return self.save()

    def stats(self) -> Dict:
        concepts = self.load().get("concepts") or {}
        confirmed = sum(1 for entry in concepts.values()
                        if any(int(count) >= MIN_CONFIRM
                               for count in (entry.get("lanes") or {}).values()))
        return {"concepts": len(concepts), "lane_confirmed": confirmed,
                "path": self.path, "verified": False,
                "evidence_status": NOT_EVIDENCE}

    # ── seekhna (ek hi darwaza) ─────────────────────────────────────────────
    def learn(self, concept: object, kind: str, *, lane: str = "",
              origin: str = "") -> Dict:
        """Ek naam yaad rakho. Har naya naam ISI raaste se andar aata hai.

        Ek hi admission point rakhne ki wajah: filter ko bypass karne ka koi
        doosra darwaza na bache (classics ka route-0 wala hi usool).

        Wapas: ``{"stored": bool, "reason": str, "concept": str}``.
        """
        text = _clean(concept)
        reason = admission_reason(text)
        if reason:
            return {"stored": False, "reason": reason, "concept": text}
        if kind not in KINDS:
            return {"stored": False, "reason": "unknown_kind", "concept": text}
        if lane and lane not in LANES:
            return {"stored": False, "reason": "unknown_lane", "concept": text}

        with self._thread_lock:
            if len(self._pending_events) >= MAX_PENDING_EVENTS:
                return {"stored": False, "reason": "pending_capacity",
                        "concept": text}
            event = {"concept": text, "kind": kind, "lane": lane,
                     "origin": str(origin)[:60], "date": _today()}
            data = self.load()
            self._apply_event(data, event)
            self._pending_events.append(event)
            return {"stored": True, "reason": "", "concept": text}

    # ── sawaal se seekhna ───────────────────────────────────────────────────
    def observe_question(self, question: str) -> Dict:
        """Jab sawaal me cue mila, us baar ke nikale naam yaad rakh lo.

        Sirf usi waqt lane bhi yaad hoti hai jab classics ne KHUD kaha ki mool
        text chahiye. Bina cue wale sawaal se lane nahi seekhi jaati — warna
        ledger apni hi galti se seekhta rehta.
        """
        text = _clean(question)
        if not text:
            return {"learned": [], "rejected": []}
        try:
            intent = CL.text_intent(text)
            works = CL.work_candidates(text)
        except Exception:                                  # pragma: no cover
            return {"learned": [], "rejected": []}
        wants = bool(intent.get("wants_primary_text"))
        lane = LANE_PRIMARY if wants else ""
        learned: List[str] = []
        rejected: List[Dict] = []

        def _take(name: str, kind: str, origin: str) -> None:
            result = self.learn(name, kind, lane=lane, origin=origin)
            if result["stored"]:
                learned.append(result["concept"])
            elif result["concept"]:
                rejected.append({"concept": result["concept"],
                                 "reason": result["reason"]})

        for name in works:
            _take(name, KIND_WORK, "question:work_candidate")
        for person in (intent.get("people") or []):
            _take(person, KIND_PERSON, "question:thinker_cue")
        # Summary lane hamesha kaam ki hai (copyright book ka ek hi imaandaar
        # raasta), isliye jo naam mool-text ke saath aaya usme summary bhi ginti
        # hai — par sirf tab jab lane khud khuli thi.
        if wants:
            for name in works:
                self.learn(name, KIND_WORK, lane=LANE_SUMMARY,
                           origin="question:summary_pair")
        return {"learned": learned, "rejected": rejected,
                "wants_primary_text": wants, "verified": False}

    # ── mile hue sources se seekhna ─────────────────────────────────────────
    def observe_sources(self, records: Sequence[object]) -> Dict:
        """Jo source pipeline ne DEKHE, unse naam seekho — lane licence se.

        Yahi wo hissa hai jo intel ki baat poori karta hai: naam kisi list se
        nahi, duniya me jo mila usse aata hai. Public-domain/khuli licence wali
        kriti ka naam mool-text lane sikhati hai; copyright wali kitab ka naam
        SUMMARY lane sikhata hai (usi shart par: ignore nahi, summary dekho).

        Source dikh jaana use padh lena nahi hai — isliye yahan bhi sirf naam
        yaad hota hai, koi content, koi claim, koi URL nahi.
        """
        learned: List[str] = []
        skipped = 0
        for record in list(records or [])[:40]:
            title = _clean(getattr(record, "title", "")
                           or (record.get("title") if isinstance(record, dict) else ""))
            if not title:
                skipped += 1
                continue
            try:
                stance = CL.copyright_stance(record if not isinstance(record, dict)
                                             else None,
                                             **(_dict_stance_kwargs(record)
                                                if isinstance(record, dict) else {}))
            except Exception:                              # pragma: no cover
                skipped += 1
                continue
            verdict = str(stance.get("verdict") or "")
            if verdict == CL.COPYRIGHT_LIKELY:
                lane, origin = LANE_SUMMARY, "corpus:copyright_title"
            elif verdict in (CL.PUBLIC_DOMAIN, CL.OPEN_LICENSED):
                lane, origin = LANE_PRIMARY, "corpus:open_licence_title"
            else:
                skipped += 1
                continue
            name = _title_concept(title)
            if not name:
                skipped += 1
                continue
            if self.learn(name, KIND_WORK, lane=lane, origin=origin)["stored"]:
                learned.append(name)

        for person in _corpus_people(records):
            if self.learn(person, KIND_PERSON, lane="",
                          origin="corpus:repeated_author")["stored"]:
                learned.append(person)
        return {"learned": learned, "skipped": skipped, "verified": False}

    # ── yaad hua wapas dena (hint, evidence nahi) ───────────────────────────
    def hints(self, question: str) -> Dict:
        """Is sawaal me ledger ko kaun se yaad naam mile.

        Lane sirf tab suggest hoti hai jab wahi naam KAM SE KAM ``MIN_CONFIRM``
        baar usi lane ke saath dekha gaya ho. Ek baar ka tukka lane nahi kholta.
        """
        concepts = self.load().get("concepts") or {}
        blank = {"concepts": [], "works": [], "people": [],
                 "wants_primary_text": False, "summary_lane": False,
                 "reasons": [], "note": "", "verified": False,
                 "is_evidence": False, "evidence_status": NOT_EVIDENCE}
        text = _clean(question)
        if not text or not concepts:
            return blank

        matched: List[Dict] = []
        for phrase in _lookup_phrases(text):
            entry = concepts.get(_key(phrase))
            if not entry:
                continue
            if any(item["concept"] == entry["concept"] for item in matched):
                continue
            lanes = {k: int(v) for k, v in (entry.get("lanes") or {}).items()}
            matched.append({
                "concept": entry["concept"],
                "kind": max((entry.get("kinds") or {"work": 1}).items(),
                            key=lambda pair: pair[1])[0],
                "lanes": lanes,
                "seen": int(entry.get("seen") or 1),
                "confirmed_lanes": sorted(k for k, v in lanes.items()
                                          if v >= MIN_CONFIRM),
                "verified": False,
            })
            if len(matched) >= _MAX_HINTS:
                break
        if not matched:
            return blank

        works = [item["concept"] for item in matched
                 if item["kind"] == KIND_WORK]
        people = [item["concept"] for item in matched
                  if item["kind"] == KIND_PERSON]
        wants = any(LANE_PRIMARY in item["confirmed_lanes"] for item in matched)
        summary = any(LANE_SUMMARY in item["confirmed_lanes"] for item in matched)
        reasons = [f"ledger_hint:{item['concept']}"
                   f"({item['kind']},seen={item['seen']})" for item in matched]
        return {"concepts": matched, "works": works, "people": people,
                "wants_primary_text": wants, "summary_lane": summary,
                "reasons": reasons, "note": LEDGER_NOTE if matched else "",
                "verified": False, "is_evidence": False,
                "evidence_status": NOT_EVIDENCE}

    def lane_plan(self, question: str, limit: int = 4) -> Dict:
        """classics.lane_plan + ledger hint. SIRF jodta hai.

        Base plan ki ek bhi query/naam yahan se gayab nahi hota — ye test se
        bandha hua hai. Ledger ke paas lane BAND karne ka koi raasta nahi.
        """
        base = dict(CL.lane_plan(question, limit=limit))
        hint = self.hints(question)
        base["ledger"] = {"concepts": hint["concepts"],
                          "note": hint["note"],
                          "verified": False,
                          "is_evidence": False,
                          "evidence_status": NOT_EVIDENCE}
        if not hint["concepts"]:
            base["ledger_opened_lane"] = False
            return base

        works = _merge_lists(base.get("works"), hint["works"], limit=limit + 2)
        people = _merge_lists(base.get("people"), hint["people"], limit=limit)
        opened = bool(hint["wants_primary_text"]) and not base.get("wants_primary_text")
        wants = bool(base.get("wants_primary_text")) or bool(hint["wants_primary_text"])
        classic_q = list(base.get("classic_queries") or [])
        summary_q = list(base.get("summary_queries") or [])
        if wants:
            classic_q = _merge_lists(
                classic_q, CL.classic_text_queries(question, works=works,
                                                   people=people, limit=limit),
                limit=limit + 3)
        if wants or hint["summary_lane"]:
            summary_q = _merge_lists(
                summary_q, CL.summary_lane_queries(question, works=works,
                                                   people=people, limit=limit),
                limit=limit + 3)
        base.update({"wants_primary_text": wants, "works": works,
                     "people": people, "classic_queries": classic_q,
                     "summary_queries": summary_q,
                     "reasons": _merge_lists(base.get("reasons"),
                                             hint["reasons"], limit=8),
                     "ledger_opened_lane": opened,
                     "verified": False})
        return base

    def note(self, hint: Optional[Dict] = None) -> str:
        """Report me chipkane wali imaandaar line (khaali = kuch kehna hi nahi)."""
        data = hint if isinstance(hint, dict) else {}
        items = data.get("concepts") or []
        if not items:
            return ""
        names = ", ".join(str(item.get("concept") or "") for item in items[:3])
        return f"{LEDGER_NOTE}. Yaad aaye naam: {names}."


# ── module-level, fail-safe API (pipeline isi ko bulati hai) ────────────────
# Niyam: ledger ki koi bhi kharaabi research ko rok nahi sakti. Isliye har
# public function apne andar sab kuch pakadta hai aur base behaviour par gir
# jaata hai. "Ledger kaam na kare" ka natija = pehle jaisa app, kam nahi.

_SHARED: Optional[ConceptLedger] = None


def enabled() -> bool:
    """``RV_CONCEPT_LEDGER=0`` se poora ledger band (ops ka switch)."""
    flag = str(os.getenv("RV_CONCEPT_LEDGER", "1")).strip().casefold()
    return flag not in ("0", "false", "no", "off")


def shared(directory: Optional[str] = None) -> ConceptLedger:
    """Ek hi instance — har sawaal par file dobara-dobara na padhi jaaye."""
    global _SHARED
    if directory:
        return ConceptLedger(directory)
    from utils.research_runtime import current, digest
    context = current()
    if context:
        # Private questions must not teach a global cross-project hint cache.
        return ConceptLedger(os.path.join(_default_dir(), "projects", digest(context.project)))
    if _SHARED is None:
        _SHARED = ConceptLedger()
    return _SHARED


def reset_shared() -> None:
    """Test/maintenance ke liye — agli baar taaza instance bane."""
    global _SHARED
    _SHARED = None


def lane_plan(question: str, limit: int = 4,
              ledger: Optional[ConceptLedger] = None) -> Dict:
    """classics.lane_plan ka ledger-aware roop. Fail hone par base plan.

    Ye function pipeline ka darwaza hai. Ledger band ho, file na khule, ya
    koi bhi exception aaye — wapas wahi plan aata hai jo pehle aata tha.
    """
    base_only = None
    try:
        base_only = CL.lane_plan(question, limit=limit)
    except Exception:                                      # pragma: no cover
        base_only = {"wants_primary_text": False, "works": [], "people": [],
                     "classic_queries": [], "summary_queries": [],
                     "verified": False}
    if not enabled():
        base_only["ledger"] = {"concepts": [], "note": "",
                               "enabled": False, "verified": False,
                               "is_evidence": False,
                               "evidence_status": NOT_EVIDENCE}
        base_only["ledger_opened_lane"] = False
        return base_only
    try:
        return (ledger or shared()).lane_plan(question, limit=limit)
    except Exception:
        base_only["ledger"] = {"concepts": [], "note": "", "enabled": True,
                               "error": "ledger_unavailable", "verified": False,
                               "is_evidence": False,
                               "evidence_status": NOT_EVIDENCE}
        base_only["ledger_opened_lane"] = False
        return base_only


def remember_question(question: str,
                      ledger: Optional[ConceptLedger] = None) -> Dict:
    """Sawaal se seekho aur file me likh do. Fail-safe."""
    if not enabled():
        return {"learned": [], "saved": False, "enabled": False}
    try:
        store = ledger or shared()
        result = store.observe_question(question)
        result["saved"] = store.save() if result.get("learned") else False
        return result
    except Exception:
        return {"learned": [], "saved": False, "error": "ledger_unavailable"}


def remember_sources(records: Sequence[object],
                     ledger: Optional[ConceptLedger] = None) -> Dict:
    """Mile hue sources se seekho aur likh do. Fail-safe."""
    if not enabled():
        return {"learned": [], "saved": False, "enabled": False}
    try:
        store = ledger or shared()
        result = store.observe_sources(records)
        result["saved"] = store.save() if result.get("learned") else False
        return result
    except Exception:
        return {"learned": [], "saved": False, "error": "ledger_unavailable"}


def _blank_hint() -> Dict:
    return {"concepts": [], "works": [], "people": [],
            "wants_primary_text": False, "summary_lane": False,
            "reasons": [], "note": "", "verified": False,
            "is_evidence": False, "evidence_status": NOT_EVIDENCE}


def hints(question: str, ledger: Optional[ConceptLedger] = None) -> Dict:
    """Sirf padhne wala raasta (report/UI ke liye). Fail-safe."""
    if not enabled():
        return _blank_hint()
    try:
        return (ledger or shared()).hints(question)
    except Exception:
        return _blank_hint()
