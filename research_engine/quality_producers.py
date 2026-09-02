"""
§7 + §19 — quality counters aur `quality_context` ke PRODUCER.

Ye module sirf GINTI karta hai, faisla nahi. Faisla (final gate) alag file ka
kaam hai; yahan se sirf imaandaar numbers aur unki definitions nikalti hain.

Do galtiyan yahin roki jaati hain, kyunki asli dark-matter answer inhi se
jhootha lag raha tha:

1. **"18 retrieved" ko "18 used" likh dena.** Retrieval ki ginti evidence ki
   taakat nahi hai. Isliye har counter alag hai: screened / retrieved / opened /
   full-text / cited / supporting-critical / directly-relevant, aur inka matlab
   docstring mein likha hai — na ki kisi ke sir par chhod diya gaya.

2. **"check nahi hua" ko "zero mila" bana dena.** `None` ka matlab hamesha
   "ye check chala hi nahi" hai, aur `0` ka matlab "chala, aur kuch nahi mila".
   Dono ek dikhne lagein to audit jhootha ho jaata hai. Isliye har dict ke
   saath `unknown_fields` aur `checked` map bhi jaata hai.

Independence ka rule (§7 verbatim): **alag URL alag source nahi hota.** Ek hi
group ka ek hi method wala kaam ek hi family hai, chahe wo teen websites par
chhapa ho. Isliye family key group+method se banti hai (patent ki apni family
key pehle aati hai), aur `distinct_urls` bhi saath report hota hai — taaki farq
saaf dikhe ki URL ginti aur asli independence mein kitna antar hai.

Poora module pure-Python hai: koi network, koi API key, koi paid call (₹0).
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence

# §17 — "kitne hisaab kaam ke nikle" ka faisla ek hi jagah hota hai
# (physics_checks), taaki audit aur ledger do alag ginti na dikhayein.
from .models import normalize_doi
from .physics_checks import usable_calculation_count

# Counter ke naam ek jagah — audit, UI aur test ek hi shabd dekhein.
COUNTER_DEFINITIONS: Dict[str, str] = {
    "sources_screened": "kitne candidate mile the (dedup/ranking se pehle)",
    "sources_retrieved": "dedup ke baad evidence pack mein kitne unique source aaye",
    "sources_opened": "kitne source metadata se aage khole gaye (snippet+)",
    "sources_full_text": "kitno ka poora text asli mein process hua",
    "sources_cited": "answer mein [S#] se kitne PACK-MAUJOOD source cite hue",
    "citations_without_source": "answer mein likhi [S#] jo pack mein hi nahi hai",
    "sources_unused": "pack mein aaye par answer mein cite hi nahi hue",
    "sources_supporting_critical_claims":
        "jinke TEXT ne kisi critical claim ko asli support diya (check C pass)",
    "directly_relevant_sources":
        "jo is sawaal ki proposition ko hi test karte hain (relevance floor + "
        "reject na hona)",
    "independent_source_families":
        "alag group/method wali families — alag URL alag family nahi banata",
    "distinct_urls": "sirf tulna ke liye: kitne alag URL the (independence NAHI)",
}

# Per-source floor jiske upar hum kehte hain "ye source seedha is sawaal ki baat
# karta hai". Ye number PROVISIONAL hai (benchmark corpus par calibrate hona
# baaki hai) — isliye iska status bhi output mein saath jaata hai, taaki koi ise
# universal sachchai na samjhe.
DIRECT_RELEVANCE_FLOOR = 0.50
DIRECT_RELEVANCE_FLOOR_STATUS = (
    "provisional — benchmark corpus par calibrate hona baaki hai")

_SID_RE = re.compile(r"\[\s*S\s*(\d{1,3})[^\]]*\]", re.IGNORECASE)
_NO_SOURCE_RE = re.compile(r"\[\s*NO[\s\-]?SOURCE\s*\]", re.IGNORECASE)
_STRONG_LABEL_RE = re.compile(
    r"\[\s*(ESTABLISHED(?:\s+FACT)?|FACT|STRONG\s+EVIDENCE)\s*\]", re.IGNORECASE)
_HYPO_LABEL_RE = re.compile(
    r"\[\s*(HYPOTHESIS|SPECULATION)\s*\]", re.IGNORECASE)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_LAB_HEADING_RE = re.compile(r"APP\s+ORIGINAL\s+RESEARCH\s+LAB", re.IGNORECASE)
_ESTABLISHED_SECTION_RE = re.compile(
    r"(established|research\s+se\s+kya|evidence\s+kya\s+kehta|supporting\s+evidence|"
    r"seedha\s+jawab|direct\s+answer|final\s+conclusion)", re.IGNORECASE)
# §9 ka banned label — kabhi output mein nahi hona chahiye.
BANNED_ACCESS_LABEL = "FULL-TEXT VERIFIED"


def _lower_surname(name: str) -> str:
    """"Rubin, Vera C." / "Vera C. Rubin" → "rubin"."""
    raw = (name or "").strip()
    if not raw:
        return ""
    if "," in raw:
        return re.sub(r"[^a-z]", "", raw.split(",")[0].lower())
    parts = [p for p in re.split(r"\s+", raw) if p]
    return re.sub(r"[^a-z]", "", parts[-1].lower()) if parts else ""


def research_group_of(source) -> str:
    """
    Is source ke peeche kaun hai — pehla author, warna publisher/venue, warna
    domain. Yahi "group" independence ka asli paimana hai.
    """
    authors = list(getattr(source, "authors", []) or [])
    if authors:
        surname = _lower_surname(authors[0])
        if surname:
            return f"author:{surname}"
    for attr in ("publisher", "venue"):
        value = (getattr(source, attr, "") or "").strip().lower()
        if value:
            return f"org:{re.sub(r'[^a-z0-9]+', '', value)[:40]}"
    domain = (getattr(source, "domain", "") or "").strip().lower()
    if domain:
        return f"site:{domain}"
    return ""


def research_family_key(source) -> str:
    """
    §7 — "independent source" ka key: ALAG GROUP / ALAG METHOD, alag URL nahi.

    Order jaan-boojh kar aisa hai:
      1. patent family (ek invention US+EP+WO teen jagah chhapti hai — ek hi baat)
      2. group + method (ek hi lab ka ek hi tareeka = ek hi family, chahe do
         paper hon, chahe teen websites par copy ho)
      3. group hi na pata ho to DOI (kam se kam "ek hi kaam" pakad lo)
      4. warna normalized title

    Ye ginti jaan-boojh kar CONSERVATIVE hai: shak ho to families kam ginte hain.
    Zyada independence bata dena overclaim hai; kam batana sirf tanginess hai.
    """
    if getattr(source, "is_patent", False):
        family = getattr(source, "patent_family_key", "") or ""
        if family:
            return f"patent:{family}"
    group = research_group_of(source)
    method = (getattr(source, "methodology", "") or "unknown").strip().lower()
    if group:
        return f"{group}|method:{method}"
    doi = normalize_doi(getattr(source, "doi", ""))
    if doi:
        return f"doi:{doi}"
    title = (getattr(source, "normalized_title", "") or
             getattr(source, "title", "") or "").strip().lower()
    return f"title:{title[:60]}" if title else "unknown"


def independent_families(sources: Sequence) -> Dict[str, List[str]]:
    """{family_key: [source_id, ...]} — audit isse dikhata hai ki kaun kis ke saath ginaa gaya."""
    out: Dict[str, List[str]] = {}
    for source in sources or []:
        key = research_family_key(source)
        out.setdefault(key, []).append(getattr(source, "source_id", "") or "?")
    return out


def cited_source_ids(answer_text: str) -> List[str]:
    """Answer mein likhi hui [S#] IDs, likhne ke order mein, bina duplicate."""
    out: List[str] = []
    for num in _SID_RE.findall(answer_text or ""):
        sid = f"S{int(num)}"
        if sid not in out:
            out.append(sid)
    return out


def _relevance_ran(sources: Sequence) -> bool:
    """Relevance scoring chali thi ya nahi — "0 relevant" aur "check nahi hua" ka farq."""
    for source in sources or []:
        if float(getattr(source, "relevance_score", 0) or 0) > 0:
            return True
        if getattr(source, "relevance_parts", None):
            return True
        if (getattr(source, "rejected_reason", "") or "").strip():
            return True
    return False


def directly_relevant_ids(sources: Sequence,
                          floor: float = DIRECT_RELEVANCE_FLOOR
                          ) -> Optional[List[str]]:
    """
    §7 — wo sources jo SAWAAL KI BAAT karte hain, sirf topic ke aas-paas nahi.

    Teen shart: reject na hua ho, relevance floor paar ho, aur proposition-test
    ne saaf 'nahi' na kaha ho (`relevance_parts["tests_proposition"] is False`).
    Return `None` = relevance chali hi nahi (yani ye ginti "0" nahi hai).
    """
    if not sources:
        return None
    if not _relevance_ran(sources):
        return None
    out: List[str] = []
    for source in sources:
        if (getattr(source, "rejected_reason", "") or "").strip():
            continue
        parts = getattr(source, "relevance_parts", None) or {}
        if parts.get("tests_proposition") is False:
            continue
        if float(getattr(source, "relevance_score", 0) or 0) >= float(floor):
            out.append(getattr(source, "source_id", "") or "?")
    return out


def _mean(values: Sequence[float]) -> Optional[float]:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 4)


def source_counters(pack=None, answer_text: str = "",
                    supporting_critical: Optional[Sequence[str]] = None,
                    floor: float = DIRECT_RELEVANCE_FLOOR) -> Dict:
    """
    §7 — saare source counters, har ek apni saaf definition ke saath.

    `pack is None` par sab kuch `None` rehta hai: "retrieval hua hi nahi" ko
    "0 source mile" likhna wahi jhooth hai jise ye module rokne ke liye bana hai.
    """
    out: Dict = {"definitions": dict(COUNTER_DEFINITIONS),
                 "relevance_floor": float(floor),
                 "relevance_floor_status": DIRECT_RELEVANCE_FLOOR_STATUS}
    for key in COUNTER_DEFINITIONS:
        out[key] = None
    out["cited_ids"] = None
    out["unused_ids"] = None
    out["directly_relevant_ids"] = None
    out["average_relevance"] = None
    out["average_relevance_cited"] = None
    out["families"] = None
    if pack is None:
        out["note"] = "evidence pack hi nahi mila — koi counter chala nahi"
        return out

    sources = list(getattr(pack, "sources", []) or [])
    by_id = {getattr(s, "source_id", ""): s for s in sources}
    written = cited_source_ids(answer_text)
    cited = [sid for sid in written if sid in by_id]
    missing = [sid for sid in written if sid not in by_id]

    out["sources_screened"] = int(getattr(pack, "discovered_count", 0) or 0) or None
    out["sources_retrieved"] = len(sources)
    opened, full = [], []
    for source in sources:
        try:
            level = source.reading_level()
        except Exception:               # pragma: no cover - defensive
            level = "metadata"
        if level != "metadata":
            opened.append(source.source_id)
        if level == "full_text":
            full.append(source.source_id)
    out["sources_opened"] = len(opened)
    out["sources_full_text"] = len(full)
    out["sources_cited"] = len(cited)
    out["cited_ids"] = cited
    out["citations_without_source"] = len(missing)
    out["citations_without_source_ids"] = missing
    out["sources_unused"] = len([s for s in by_id if s and s not in cited])
    out["unused_ids"] = [s for s in by_id if s and s not in cited]

    direct = directly_relevant_ids(sources, floor)
    out["directly_relevant_sources"] = None if direct is None else len(direct)
    out["directly_relevant_ids"] = direct

    families = independent_families(sources)
    out["independent_source_families"] = len(families) if sources else None
    out["families"] = {k: list(v) for k, v in families.items()}
    urls = {(getattr(s, "url", "") or "").strip().lower()
            for s in sources if (getattr(s, "url", "") or "").strip()}
    out["distinct_urls"] = len(urls) if urls else None

    if _relevance_ran(sources):
        out["average_relevance"] = _mean(
            [float(getattr(s, "relevance_score", 0) or 0) for s in sources])
        out["average_relevance_cited"] = _mean(
            [float(getattr(by_id[s], "relevance_score", 0) or 0) for s in cited])

    if supporting_critical is None:
        out["sources_supporting_critical_claims"] = None
    else:
        ids = [sid for sid in supporting_critical if sid]
        out["sources_supporting_critical_claims"] = len(ids)
        out["sources_supporting_critical_claims_ids"] = list(ids)
    return out


# ── answer text ke scanner (§19) ─────────────────────────────────────────────
def _sections(answer_text: str):
    """(section_title, line) jodi — heading track karte hue."""
    section = ""
    for raw in (answer_text or "").splitlines():
        heading = _HEADING_RE.match(raw)
        if heading:
            section = " ".join(heading.group(1).split())
            continue
        yield section, raw.strip()


def no_source_claims(answer_text: str) -> List[Dict]:
    """
    §19 — wo dave jinke peeche koi source hi nahi.

    Do tarah ke: saaf `[NO-SOURCE]` label wale, aur wo jinka label strong hai
    ([ESTABLISHED FACT]/[FACT]/[STRONG EVIDENCE]) par line par ek bhi [S#] nahi.
    Dusri qism zyada khatarnak hai — wahi asli dark-matter answer mein 14 baar
    thi, aur audit mein dikhi hi nahi.
    """
    out: List[Dict] = []
    for section, line in _sections(answer_text):
        if len(line) < 25:
            continue
        has_ids = bool(_SID_RE.search(line))
        no_source = bool(_NO_SOURCE_RE.search(line))
        strong = bool(_STRONG_LABEL_RE.search(line))
        if not (no_source or (strong and not has_ids)):
            continue
        out.append({"section": section, "line": line[:220],
                    "kind": "no_source_label" if no_source else "strong_without_citation",
                    "critical": bool(strong or _ESTABLISHED_SECTION_RE.search(section))})
    return out


def hypothesis_fact_mix(answer_text: str) -> Dict:
    """
    §19 — app ki hypothesis aur established fact ka MIX kitni baar hua.

    Do galtiyan ginte hain:
      * LAB section ke andar strong/fact label lagana (apni hypothesis ko sach
        bata dena) — spec ka sabse bada non-negotiable.
      * established/evidence wale sections mein [HYPOTHESIS]/[SPECULATION] line
        ghusa dena (padhne wale ko lagta hai ye bhi research ka nateeja hai).
    """
    details: List[Dict] = []
    for section, line in _sections(answer_text):
        if len(line) < 25:
            continue
        in_lab = bool(_LAB_HEADING_RE.search(section))
        if in_lab and _STRONG_LABEL_RE.search(line):
            details.append({"section": section, "line": line[:200],
                            "kind": "hypothesis_labelled_as_fact"})
        elif (not in_lab and _HYPO_LABEL_RE.search(line)
                and _ESTABLISHED_SECTION_RE.search(section)):
            details.append({"section": section, "line": line[:200],
                            "kind": "hypothesis_inside_evidence_section"})
    return {"count": len(details), "details": details}


# Access label ki gehrai ka order — "claimed" aur "actual" tulna isi se hoti hai.
_ACCESS_RANK: Dict[str, int] = {}


def _access_rank_table() -> Dict[str, int]:
    global _ACCESS_RANK
    if _ACCESS_RANK:
        return _ACCESS_RANK
    try:
        from .models import (ACCESS_ABSTRACT, ACCESS_FULL, ACCESS_METADATA,
                             ACCESS_SECTIONS, ACCESS_SNIPPET)
        _ACCESS_RANK = {ACCESS_METADATA: 0, ACCESS_SNIPPET: 1,
                        ACCESS_ABSTRACT: 2, ACCESS_SECTIONS: 3, ACCESS_FULL: 4}
    except Exception:                   # pragma: no cover - defensive
        _ACCESS_RANK = {"METADATA ONLY": 0, "SNIPPET ONLY": 1,
                        "ABSTRACT ONLY": 2, "RELEVANT SECTIONS REVIEWED": 3,
                        "FULL TEXT ACCESSED": 4}
    return _ACCESS_RANK


def _claimed_access_label(line: str) -> str:
    """Line mein likha hua access label (sabse gehra jo mila)."""
    best, best_rank = "", -1
    for label, rank in _access_rank_table().items():
        if label.lower() in (line or "").lower() and rank > best_rank:
            best, best_rank = label, rank
    return best


def access_depth_mismatches(pack=None, answer_text: str = "") -> Optional[List[Dict]]:
    """
    §9 — jahan answer ne source se ZYADA gehrai ka dava kiya.

    Asli failure: S12 ka sirf abstract mila tha, par answer ne use "FULL-TEXT
    VERIFIED" likh diya. Ab do cheezein pakdi jaati hain — (1) banned label ka
    kahin bhi hona, (2) kisi line par likha access label us source ke asli
    `access_depth()` se gehra hona.

    `None` = check chala hi nahi (pack ya answer text nahi tha).
    """
    if pack is None or not (answer_text or "").strip():
        return None
    ranks = _access_rank_table()
    sources = {getattr(s, "source_id", ""): s
               for s in (getattr(pack, "sources", []) or [])}
    out: List[Dict] = []
    for section, line in _sections(answer_text):
        if not line:
            continue
        if BANNED_ACCESS_LABEL.lower() in line.lower():
            out.append({"kind": "banned_label", "section": section,
                        "line": line[:200], "claimed": BANNED_ACCESS_LABEL,
                        "actual": "", "source_id": "",
                        "why": ("'FULL-TEXT VERIFIED' label band hai — poora text "
                                "padhna claim verify karna NAHI hai")})
            continue
        claimed = _claimed_access_label(line)
        if not claimed:
            continue
        for num in _SID_RE.findall(line):
            sid = f"S{int(num)}"
            source = sources.get(sid)
            if source is None:
                continue
            try:
                actual = source.access_depth()
            except Exception:           # pragma: no cover - defensive
                continue
            if ranks.get(claimed, 0) > ranks.get(actual, 0):
                out.append({"kind": "depth_overclaim", "section": section,
                            "line": line[:200], "claimed": claimed,
                            "actual": actual, "source_id": sid,
                            "why": (f"{sid} par asli gehrai {actual} thi, par line "
                                    f"{claimed} ka dava kar rahi hai")})
    return out


_CONFIDENCE_WORDS = ("confidence", "confident", "probability", "likelihood",
                     "chance", "certainty", "sambhavna", "vishwas", "yakeen",
                     "probable", "odds")
_PERCENT_RE = re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%")
# `(?<![\d.])` (2026-08-22, §24): pehle `\b0?\.\d+\b` tha, jo "5.4 guna" me se
# ".4" utha leta tha aur "8.6 keV" me se ".6" — yaani har imaandaar measurement
# ek "numeric confidence claim" ban jaata tha aur `numeric_confidence_calibrated`
# hamesha False ho jaata tha. Ab sirf 0.xx / .xx jaisa akela probability number.
_PROB_RE = re.compile(r"(?<![\d.])0?\.\d+\b")
# Number aur confidence-shabd ke beech ki max doori. Kyun: coverage ka imaandaar
# note ek hi line mein "average topic match 0.68" bhi likhta hai aur 205 character
# baad "Ye confidence retrieved evidence par hai" bhi — wo 0.68 relevance ka naap
# hai, confidence ka dava nahi. Asli dava ("90% confidence") paas-paas hi likha
# jaata hai.
_CONF_NEAR = 60
# Line jo KISI SOURCE ki baat quote kar rahi hai — source-title bullet (`**[S7]
# …**`) ya verbatim excerpt (`- Isse kya liya gaya: …`). Retracted paper ke title
# mein khud "90% probability" likha tha; use app ka apna dava ginna §18 ko ulta
# kar deta hai (imaandaar quote par report fail hone lagti hai).
_QUOTED_SOURCE_RE = re.compile(r"^\s*[-*>\s]*\**\s*\[s\d+\]|isse kya liya gaya",
                               re.IGNORECASE)


def numeric_confidence_claims(answer_text: str) -> List[Dict]:
    """
    §18 — jawab mein kahin NUMBER wala confidence likha hai ya nahi.

    Kyun zaroori: humare paas koi calibrated benchmark nahi hai, isliye "90%
    probability" jaisa number apne aap mein ek jhooth hai (spec ka non-negotiable
    #4). Ye function wo jagahein dhoondta hai; faisla producer nahi karta —
    `numeric_confidence_calibrated` False ho jaata hai aur wajah saath jaati hai.

    Teen shart (§24 ke baad): number probability jaisa ho, confidence-shabd uske
    PAAS ho, aur line kisi source ka quote na ho. Teenon isliye ki ye check ek
    imaandaar report ko fail na kare — warna "5.4 guna" aur retracted paper ka
    quote bhi "fake probability" gin liye jaate the.
    """
    out: List[Dict] = []
    for section, line in _sections(answer_text):
        low = line.lower()
        if not any(word in low for word in _CONFIDENCE_WORDS):
            continue
        if _QUOTED_SOURCE_RE.search(low):
            continue
        word_at = [low.index(w) for w in _CONFIDENCE_WORDS if w in low]
        hits: List[str] = []
        for match in list(_PERCENT_RE.finditer(line)) + list(_PROB_RE.finditer(line)):
            if any(min(abs(match.start() - at), abs(match.end() - at)) <= _CONF_NEAR
                   for at in word_at):
                hits.append(match.group(0))
        if not hits:
            continue
        out.append({"section": section, "line": line[:200],
                    "numbers": hits[:4]})
    return out


def _verification_dict(verification) -> Optional[Dict]:
    """VerificationReport ya uska dict — dono chalein; warna `None`."""
    if verification is None:
        return None
    if isinstance(verification, dict):
        return verification
    to_dict = getattr(verification, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception:               # pragma: no cover - defensive
            return None
    return None


def _evidence_graph_complete(vdict: Optional[Dict], cited: Optional[List[str]]
                             ) -> Optional[bool]:
    """
    Evidence graph "poora" tab hai jab (a) har critical claim ke saath asli span
    ho, aur (b) answer mein cite hua har source kisi claim se juda ho.

    `None` = graph banaya hi nahi gaya (claim verification nahi chali). Ye
    "adhoora" se ALAG baat hai.
    """
    if not vdict:
        return None
    spans_complete = vdict.get("critical_claim_spans_complete")
    if spans_complete is None and not vdict.get("claims"):
        return None
    linked: set = set()
    for claim in vdict.get("claims") or []:
        for sid in claim.get("cited_ids") or []:
            linked.add(sid)
        for span in claim.get("evidence_spans") or []:
            if span.get("source_id"):
                linked.add(span["source_id"])
    orphan_cited = [sid for sid in (cited or []) if sid not in linked]
    return bool(spans_complete) and not orphan_cited


# §19 ke wo field jinka `None` hona apne aap mein ek khabar hai — inhe kabhi
# 0/False se replace nahi karna.
TRISTATE_FIELDS: tuple = (
    "directly_relevant_sources", "sources_supporting_critical_claims",
    "average_relevance", "critical_claim_spans_complete",
    "critical_contradiction_spans_complete",
    "critical_claims_same_source_ae_passed", "claim_verification_achievement",
    "critical_claim_coverage_complete",
    "evidence_first_required", "critical_claim_preselection_complete",
    "critical_claims_preselected_span_unmatched", "evidence_first_achievement",
    "evidence_graph_complete", "counter_search_performed", "recovery_used",
    "progress_snapshot_preserved", "numeric_confidence_calibrated",
    "access_depth_mismatch_count", "unsupported_critical_claims",
    "independent_source_families", "calculations_count",
    # §17 — "hisaab hi nahi dhoondha" (None) aur "dhoondha, ek bhi poora nahi
    # nikla" (0) do alag baatein hain. Dono ko milaana hi wo purani galti thi
    # jisme "numeric sanity check kiya" likh diya gaya tha bina kisi hisaab ke.
    "calculations_usable", "calculations_failed_checks",
    "calculations_with_invented_inputs",
    # §5 — axis coverage bhi tri-state hai: `None` = axes naape hi nahi gaye.
    "axes_covered", "axes_mandatory_missing",
    # §6 — relevance gate: `None` = proposition-test chala hi nahi. Ise 0 likhna
    # "koi source sawaal ki baat nahi karta" jaisa ulta matlab de deta.
    "sources_testing_proposition", "relevance_gate_ran",
    # §11 — contradiction ki chhaanti: `None` = jaanch hi nahi chali. "0 nakli
    # takraav mile" ek nateeja hai, "dekha hi nahi" doosra.
    "contradictions_rejected", "contradictions_schema_complete",
    # §13-§18 — hypothesis ka record: `None` = hypothesis step chala hi nahi.
    # "0 hypotheses bani" (allowed outcome) aur "step chala hi nahi" alag hain.
    "hypothesis_schema_complete", "hypothesis_novel_without_search",
)


def relevance_gate_report(pack=None) -> Dict:
    """
    §6 — relevance gate ka structured nateeja, pack se seedha padha hua.

    Gate chala hi nahi (purana pack, ya relevance skip) to sab `None` rehta hai.
    "0 source sawaal ko test karte hain" aur "check nahi hua" do bilkul alag
    baatein hain, aur pehli wali VERIFIED ko rokti hai — isliye inhe milaana
    mana hai.
    """
    empty = {"ran": False, "dimensions": [], "checklist": [],
             "tests_proposition": None,
             "does_not_test": None, "undecided": None,
             "failed_dimensions": {}, "reject_codes": {}, "note": ""}
    if pack is None:
        return empty
    getter = getattr(pack, "proposition_report", None)
    prop = getter() if callable(getter) else {}
    if not prop:
        return empty
    codes_getter = getattr(pack, "reject_code_counts", None)
    return {
        "ran": True,
        "dimensions": list(prop.get("dimensions") or []),
        # §6 ki poori das-item checklist (nau dimension + daswa aakhri faisla).
        # Purane pack mein ye key na ho to dimensions par gir jaate hain, aur
        # report tab bhi sirf utna hi likhegi jitna sach mein dekha gaya.
        "checklist": list(prop.get("checklist")
                          or prop.get("dimensions") or []),
        "tests_proposition": prop.get("tests_proposition"),
        "does_not_test": prop.get("does_not_test"),
        "undecided": prop.get("undecided"),
        "failed_dimensions": dict(prop.get("failed_dimensions") or {}),
        "reject_codes": (codes_getter() if callable(codes_getter) else {}),
        "note": prop.get("note") or "",
    }


def _axis_summary(records: Optional[Sequence[Dict]]) -> Dict:
    """
    evidence_axes.coverage_summary() ka safe wrapper — import lazy hai taaki ye
    module akela bhi (bina axes ke) chal sake.
    """
    if not records:
        return {"axes_total": None, "axes_covered": None, "axes_weak": None,
                "axes_missing": None, "axes_not_searched": None,
                "mandatory_missing": None, "missing_labels": []}
    try:
        from .evidence_axes import coverage_summary
        return coverage_summary(records)
    except Exception:                       # pragma: no cover - defensive
        return {"axes_total": len(records), "axes_covered": None,
                "axes_weak": None, "axes_missing": None,
                "axes_not_searched": None, "mandatory_missing": None,
                "missing_labels": []}


def quality_context(pack=None, answer_text: str = "", verification=None,
                    counter_search: Optional[bool] = None,
                    calculations: Optional[Sequence] = None,
                    numeric_confidence_calibrated: Optional[bool] = None,
                    recovery_used: Optional[bool] = None,
                    progress_snapshot_preserved: Optional[bool] = None,
                    hypotheses: Optional[Sequence] = None,
                    contradictions: Optional[Sequence] = None,
                    contradiction_rejections: Optional[Dict] = None,
                    evidence_graph: Optional[bool] = None,
                    axis_coverage: Optional[Sequence[Dict]] = None,
                    evidence_first_audit: Optional[Dict] = None,
                    floor: float = DIRECT_RELEVANCE_FLOOR) -> Dict:
    """
    §19 — poora `quality_context`, ek hi jagah se, ek hi definition se.

    Yahan koi cheez "acchi lage" isliye nahi bhari jaati. Jo check nahi hua wo
    `None` rehta hai aur `unknown_fields` mein apna naam likha kar jaata hai.
    Final gate isi dict ko padhta hai, isliye jhoothi 0/True yahan sabse mehnga
    jhooth hoti — wahi asli answer ka "numeric sanity check passed" tha, jabki
    koi calculation hi nahi hui thi.
    """
    vdict = _verification_dict(verification)
    evidence_first = (dict(evidence_first_audit)
                      if isinstance(evidence_first_audit, dict) else None)
    supporting = None
    if vdict is not None:
        supporting = vdict.get("sources_supporting_critical_claims")
        if isinstance(supporting, int):
            supporting = (vdict.get("sources_supporting_critical_claims_ids")
                          or [f"?{i}" for i in range(supporting)])
    counters = source_counters(pack=pack, answer_text=answer_text,
                               supporting_critical=supporting, floor=floor)
    no_source = no_source_claims(answer_text)
    mix = hypothesis_fact_mix(answer_text)
    mismatches = access_depth_mismatches(pack, answer_text)
    calc_list = None if calculations is None else [dict(c) if isinstance(c, dict)
                                                  else {"note": str(c)}
                                                  for c in calculations]
    numeric_claims = numeric_confidence_claims(answer_text)
    if numeric_confidence_calibrated is None and numeric_claims:
        # Number wala confidence likha hai par calibration ka koi saboot nahi —
        # is haalat mein "unknown" chhodna hi jhooth hoga.
        numeric_confidence_calibrated = False

    ctx: Dict = {
        # ── §7 counters (alag-alag, kabhi ek doosre ki jagah nahi) ───────────
        "counters": counters,
        "sources_retrieved": counters.get("sources_retrieved"),
        "sources_cited": counters.get("sources_cited"),
        "sources_unused": counters.get("sources_unused"),
        "citations_without_source": counters.get("citations_without_source"),
        "sources_supporting_critical_claims":
            counters.get("sources_supporting_critical_claims"),
        "directly_relevant_sources": counters.get("directly_relevant_sources"),
        "independent_source_families": counters.get("independent_source_families"),
        "distinct_urls": counters.get("distinct_urls"),
        "average_relevance": counters.get("average_relevance"),
        # ── claim-level (§8/§9) ─────────────────────────────────────────────
        "claim_results": (vdict or {}).get("result_counts"),
        "unsupported_critical_claims": (vdict or {}).get("unsupported_critical_claims"),
        "unverifiable_critical_claims": (vdict or {}).get("unverifiable_critical_claims"),
        "critical_contradicted_claims": (vdict or {}).get("critical_contradicted_claims"),
        "critical_contradiction_spans_complete":
            (vdict or {}).get("critical_contradiction_spans_complete"),
        "critical_claims": (vdict or {}).get("critical_claims"),
        "critical_claims_same_source_ae_passed":
            (vdict or {}).get("critical_claims_same_source_ae_passed"),
        "claim_verification_achievement":
            (vdict or {}).get("claim_verification_achievement"),
        "critical_claim_coverage_complete":
            (vdict or {}).get("critical_claim_coverage_complete"),
        "critical_claim_supporting_source_ids":
            (vdict or {}).get("sources_supporting_critical_claims"),
        "critical_claim_spans_complete":
            (vdict or {}).get("critical_claim_spans_complete"),
        "critical_claim_evidence_spans": (vdict or {}).get("critical_claim_spans"),
        # P0-B — no raw evidence passage is copied into quality_context;
        # hashes/locators/counts are sufficient for release audit.
        "evidence_first_required": (evidence_first or {}).get("evidence_first_required")
            if evidence_first is not None else None,
        "preselected_evidence_spans_count":
            (evidence_first or {}).get("preselected_evidence_spans_count")
            if evidence_first is not None else None,
        "preselected_strong_eligible_spans":
            (evidence_first or {}).get("preselected_strong_eligible_spans")
            if evidence_first is not None else None,
        "critical_claims_preselected_span_matched":
            (evidence_first or {}).get("critical_claims_preselected_span_matched")
            if evidence_first is not None else None,
        "critical_claims_preselected_span_unmatched":
            (evidence_first or {}).get("critical_claims_preselected_span_unmatched")
            if evidence_first is not None else None,
        "critical_claim_preselection_complete":
            (evidence_first or {}).get("critical_claim_preselection_complete")
            if evidence_first is not None else None,
        "evidence_first_achievement":
            (evidence_first or {}).get("evidence_first_achievement")
            if evidence_first is not None else None,
        "evidence_first_claim_matches":
            list((evidence_first or {}).get("claim_matches") or [])
            if evidence_first is not None else None,
        "evidence_first_failures":
            list((evidence_first or {}).get("preselection_failures") or [])
            if evidence_first is not None else None,
        "critical_no_source_claims": len([c for c in no_source if c["critical"]]),
        "no_source_claims": len(no_source),
        "no_source_claim_details": no_source,
        "access_depth_mismatches": mismatches,
        "access_depth_mismatch_count": None if mismatches is None else len(mismatches),
        # ── separation aur process (§10, §12, §17, §18, §21, §22) ────────────
        "evidence_graph_complete": (evidence_graph if evidence_graph is not None
                                    else _evidence_graph_complete(
                                        vdict, counters.get("cited_ids"))),
        "hypothesis_fact_mix_count": mix["count"],
        "hypothesis_fact_mix_details": mix["details"],
        "hypotheses_present": None if hypotheses is None else len(list(hypotheses)),
        "contradictions_present": None if contradictions is None else len(list(contradictions)),
        "counter_search_performed": counter_search,
        "calculations": calc_list,
        "calculations_count": None if calc_list is None else len(calc_list),
        # §17 — do ALAG ginti: kitne hisaab mile, aur unme se kitne poore hue
        # (formula+inputs+units+result likha ho aur koi chala hua check fail na
        # hua ho). "5 calculations dikhaye" aur "5 verified calculations" ek
        # baat nahi hai, isliye report mein bhi dono alag rehti hain.
        "calculations_usable": usable_calculation_count(calc_list),
        "calculations_failed_checks": None if calc_list is None else len(
            [c for c in calc_list
             if c.get("unit_check_passed") is False
             or c.get("recalculation_passed") is False
             or c.get("sanity_check_passed") is False]),
        "calculations_with_invented_inputs": None if calc_list is None else len(
            [c for c in calc_list if c.get("invented_input") is True]),
        "numeric_confidence_calibrated": numeric_confidence_calibrated,
        "numeric_confidence_claims": numeric_claims,
        "recovery_used": recovery_used,
        "progress_snapshot_preserved": progress_snapshot_preserved,
    }
    # §5 — per-axis coverage. `None` matlab axes naape hi nahi gaye; khaali list
    # bhi wahi baat kehti hai, isliye dono ko `None` par rakha jaata hai.
    axis_list = list(axis_coverage or [])
    axis_sum = _axis_summary(axis_list)
    ctx["evidence_axes"] = axis_list or None
    ctx["axes_total"] = axis_sum["axes_total"]
    ctx["axes_covered"] = axis_sum["axes_covered"]
    ctx["axes_weak"] = axis_sum["axes_weak"]
    ctx["axes_missing"] = axis_sum["axes_missing"]
    ctx["axes_not_searched"] = axis_sum["axes_not_searched"]
    ctx["axes_mandatory_missing"] = axis_sum["mandatory_missing"]
    ctx["axes_missing_labels"] = axis_sum["missing_labels"]
    # §6 — relevance gate (proposition-test) ka structured nateeja
    gate = relevance_gate_report(pack)
    ctx["relevance_gate"] = gate
    ctx["relevance_gate_ran"] = True if gate["ran"] else None
    ctx["sources_testing_proposition"] = gate["tests_proposition"]
    ctx["sources_not_testing_proposition"] = gate["does_not_test"]
    ctx["relevance_undecided_sources"] = gate["undecided"]
    ctx["relevance_reject_codes"] = gate["reject_codes"] or None
    # §11 — contradiction ka structured hisaab. Teen alag baatein: kitne mile,
    # unmein se kitne poore schema wale hain, aur kitne "takraav" jaanch kar
    # hataye gaye (aur kis code se). Pichhli report mein saal-ka-farq wale nakli
    # takraav gine ja rahe the, isliye ye ginti alag rakhi gayi hai.
    contra_list = None if contradictions is None else [
        dict(c) if isinstance(c, dict) else {"summary": str(c)} for c in contradictions]
    ctx["contradictions"] = contra_list
    ctx["contradictions_schema_complete"] = (
        None if contra_list is None
        else all(bool(c.get("schema_complete")) for c in contra_list))
    if contradiction_rejections is None:
        # Reject ki jaanch chali hi nahi → `None`, "0 reject hue" nahi.
        ctx["contradictions_rejected"] = None
        ctx["contradiction_reject_codes"] = None
    else:
        ctx["contradictions_rejected"] = int(contradiction_rejections.get("rejected") or 0)
        ctx["contradiction_reject_codes"] = dict(
            contradiction_rejections.get("counts") or {})
    # §13-§18 — app ki apni hypothesis ka structured hisaab (novelty labels,
    # confidence bands, adhoore schema, safety ki kami).
    hyp_report = hypothesis_report(hypotheses)
    ctx["hypothesis_report"] = hyp_report if hyp_report["ran"] else None
    ctx["hypothesis_novelty_counts"] = hyp_report["novelty_counts"]
    ctx["hypothesis_schema_complete"] = hyp_report["schema_complete"]
    ctx["hypothesis_confidence_bands"] = hyp_report["confidence_bands"]
    ctx["hypothesis_numeric_confidence"] = hyp_report["numeric_confidence"]
    ctx["hypothesis_novel_without_search"] = hyp_report["claimed_novel_without_search"]
    ctx["hypothesis_missing_risk_checks"] = hyp_report["missing_risk_checks"]
    ctx["unknown_fields"] = [k for k in TRISTATE_FIELDS if ctx.get(k) is None]
    ctx["checked"] = {k: (ctx.get(k) is not None) for k in TRISTATE_FIELDS}
    return ctx


# §13-§18 — app ki apni hypothesis ka hisaab. Ye ALAG rakha gaya hai kyunki
# "app ne kya socha" aur "sources ne kya kaha" ek dict mein mila dene se hi
# pichhli report mein PBH/MOND/dark photon app ki khoj jaise dikh gaye the.
_NOVELTY_OK = ("KNOWN IDEA", "KNOWN VARIANT", "MINOR MODIFICATION",
               "POSSIBLY NOVEL — NO CLOSE MATCH FOUND", "NOVELTY UNVERIFIED",
               "REJECTED AS DUPLICATE")


def hypothesis_report(hypotheses: Optional[Sequence] = None) -> Dict:
    """
    Hypotheses ka structured audit — ginti, novelty labels, adhoore schema,
    confidence bands, aur safety ki kami.

    `hypotheses is None` = hypothesis step chala hi nahi → sab `None`. Khaali
    list = chala aur kuch nahi bana (ye ALLOWED outcome hai, galti nahi).
    """
    if hypotheses is None:
        return {"count": None, "ran": None, "ids": None, "novelty_counts": None,
                "schema_complete": None, "incomplete_ids": None,
                "confidence_bands": None, "numeric_confidence": None,
                "claimed_novel_without_search": None,
                "known_ideas_flagged": None, "validation_states": None,
                "missing_risk_checks": None, "forbidden_novelty_labels": None}

    items = [dict(h) if isinstance(h, dict) else {} for h in hypotheses]
    novelty_counts: Dict[str, int] = {}
    bands: Dict[str, int] = {}
    validation: Dict[str, int] = {}
    ids: List[str] = []
    incomplete: List[str] = []
    known_flagged: List[str] = []
    bad_labels: List[str] = []
    numeric = 0
    novel_without_search = 0
    missing_risk: List[str] = []

    required = ("hypothesis_id", "statement", "provenance", "mechanism",
                "source_claim_disclaimer", "prediction", "novelty_status",
                "closest_prior_work", "confidence", "validation_status")
    for h in items:
        hid = str(h.get("hypothesis_id") or "") or "(bina ID)"
        ids.append(hid)
        missing = [k for k in required if h.get(k) in (None, "", [], {})]
        if missing:
            incomplete.append(hid)
        label = str(h.get("novelty_status") or "")
        novelty_counts[label or "(khaali)"] = novelty_counts.get(label or "(khaali)", 0) + 1
        if label and label not in _NOVELTY_OK:
            bad_labels.append(f"{hid}: {label}")
        search = h.get("novelty_search") or {}
        if label.startswith("POSSIBLY NOVEL") and search.get("performed") is not True:
            novel_without_search += 1
        if h.get("known_idea_hits"):
            known_flagged.append(hid)
        conf = h.get("confidence") or {}
        band = str(conf.get("band") or h.get("confidence_band") or "")
        bands[band or "(khaali)"] = bands.get(band or "(khaali)", 0) + 1
        if conf.get("numeric_allowed") is True:
            numeric += 1
        state = str(h.get("validation_status") or "")
        validation[state or "(khaali)"] = validation.get(state or "(khaali)", 0) + 1
        if h.get("safety_sensitive") is True and len(
                str(h.get("risks") or "").strip()) < 15:
            missing_risk.append(hid)

    return {
        "count": len(items),
        "ran": True,
        "ids": ids,
        "novelty_counts": novelty_counts,
        "schema_complete": not incomplete,
        "incomplete_ids": incomplete,
        "confidence_bands": bands,
        "numeric_confidence": numeric,
        "claimed_novel_without_search": novel_without_search,
        "known_ideas_flagged": known_flagged,
        "validation_states": validation,
        "missing_risk_checks": missing_risk,
        "forbidden_novelty_labels": bad_labels,
    }


def _num(value) -> str:
    """`None` ko kabhi 0 nahi likhna — yahi poore module ka asal maqsad hai."""
    return "check nahi hua" if value is None else str(value)


def sections_present(answer_text: str) -> List[str]:
    """
    Final answer ke TOP-LEVEL (`##`) section titles, jaise ke waise.

    Numbering/emoji hata dete hain taaki "## 3. 🔬 Evidence kya kehta hai?" bhi
    contract ke naam se match kar sake — par shabd nahi badalte.
    """
    out: List[str] = []
    for raw in (answer_text or "").splitlines():
        stripped = raw.strip()
        if not stripped.startswith("##") or stripped.startswith("####"):
            continue
        title = stripped.lstrip("#").strip()
        title = re.sub(r"^[\d]+[\.\)]\s*", "", title)
        title = re.sub(r"[*_`]", "", title)
        title = "".join(ch for ch in title if ch.isalnum() or ch.isspace()
                        or ch in "-/?&,:()'").strip()
        if title:
            out.append(" ".join(title.split()))
    return out


def rescan_final_answer(ctx: Optional[Dict], pack=None,
                        final_answer: str = "") -> Optional[Dict]:
    """
    Assembled answer par doosra scan — kuch cheezein sirf wahin dikhti hain.

    Counters JAAN-BOOJH KAR model ke apne text (`annotated`) se aate hain: final
    answer ke "Sources" list mein har source ka [S#] likha hota hai, to usse
    "cited" ginna har uncited source ko cited bana deta — theek wahi jhoothi
    ginti jo §7 rok raha hai. Section titles, access-depth ke dave, aur
    hypothesis/fact ka mix, ye teen cheezein final text mein hi hoti hain.
    """
    if not ctx or not (final_answer or "").strip():
        return ctx
    ctx["sections_present"] = sections_present(final_answer)

    merged = list(ctx.get("access_depth_mismatches") or [])
    seen = {(m.get("kind"), m.get("source_id", ""), m.get("line", ""))
            for m in merged}
    for item in access_depth_mismatches(pack, final_answer) or []:
        key = (item.get("kind"), item.get("source_id", ""), item.get("line", ""))
        if key not in seen:
            merged.append(item)
            seen.add(key)
    if merged or ctx.get("access_depth_mismatches") is not None:
        ctx["access_depth_mismatches"] = merged
        ctx["access_depth_mismatch_count"] = len(merged)

    mix = hypothesis_fact_mix(final_answer)
    if mix["count"] > int(ctx.get("hypothesis_fact_mix_count") or 0):
        ctx["hypothesis_fact_mix_count"] = mix["count"]
        ctx["hypothesis_fact_mix_details"] = mix["details"]

    numeric = numeric_confidence_claims(final_answer)
    if numeric:
        have = {n["line"] for n in (ctx.get("numeric_confidence_claims") or [])}
        ctx["numeric_confidence_claims"] = (
            list(ctx.get("numeric_confidence_claims") or [])
            + [n for n in numeric if n["line"] not in have])
        if ctx.get("numeric_confidence_calibrated") is not True:
            ctx["numeric_confidence_calibrated"] = False

    ctx["unknown_fields"] = [k for k in TRISTATE_FIELDS if ctx.get(k) is None]
    ctx["checked"] = {k: (ctx.get(k) is not None) for k in TRISTATE_FIELDS}
    return ctx


# §19 — tri-state ka wo hissa jo SIRF audit dict mein reh jaata tha. Live
# dark-matter report isi par giri thi: audit mein "counter-search: 0" chhapa,
# jabki search chali hi nahi thi. Neeche ka block user ke jawab mein hi naam
# le kar likhta hai ki kaunsa check HO HI NAHI SAKA.
UNKNOWN_HEADING = "### Kaunse check HO HI NAHI SAKE"

# §7 — ginti wale block ki pehchaan. Isse do baar inject hona ruk jaata hai
# (orchestrator dobara chal sakta hai, aur recovery path bhi same answer
# text par kaam karta hai).
COUNTERS_HEADING = "**Ginti (har ek ka matlab alag hai):**"

_UNKNOWN_HUMAN: Dict[str, str] = {
    "directly_relevant_sources": "kitne source seedha sawaal ki baat karte hain",
    "sources_supporting_critical_claims": "critical dava ko asli support dene wale source",
    "average_relevance": "sources ka average relevance",
    "critical_claim_spans_complete": "har critical dava ke saath saboot ka tukda (span) mila ya nahi",
    "evidence_graph_complete": "claim-se-source ka poora evidence graph bana ya nahi",
    "counter_search_performed": "khilaf wali side ka search sach mein chala ya nahi",
    "recovery_used": "recovery (adhoore run se jawab bachana) laga ya nahi",
    # In do fields ka `None` "aalas" nahi hai, isliye wajah bhi saath likhi hai —
    # warna user samajhta hai ki koi check chup-chaap fail ho gaya.
    "progress_snapshot_preserved": ("progress ka snapshot bacha rakha gaya ya "
                                    "nahi — ye job-server ke level par tay hota "
                                    "hai, research engine ke andar iska record "
                                    "hi nahi hota"),
    "numeric_confidence_calibrated": ("confidence ka number kisi asli hisaab se "
                                      "bana ya nahi — is jawab mein koi "
                                      "percentage wala confidence number hi "
                                      "nahi tha, to calibrate karne ko kuch "
                                      "nahi bacha"),
    "access_depth_mismatch_count": "padhne ki gehrai ke dave ka mismatch",
    "unsupported_critical_claims": "bina support wali critical dava ki ginti",
    "independent_source_families": "independent source families ki ginti",
    "calculations_count": "kitne hisaab mile",
    "calculations_usable": "kitne hisaab poore aur bharose ke laayak the",
    "calculations_failed_checks": "kitne hisaab check mein fail hue",
    "calculations_with_invented_inputs": "kitne hisaab mein input khud bana liya gaya tha",
    "axes_covered": "kitne zaroori evidence raaste cover hue",
    "axes_mandatory_missing": "kitne zaroori evidence raaste khaali reh gaye",
    "sources_testing_proposition": "kitne source sawaal ki baat SACH MEIN test karte hain",
    "relevance_gate_ran": "relevance ka proposition-test chala ya nahi",
    "contradictions_rejected": "kitne nakli takraav jaanch kar hataye gaye",
    "contradictions_schema_complete": "takraav ka structured record poora bana ya nahi",
    "hypothesis_schema_complete": "hypothesis ka record poora bana ya nahi",
    "hypothesis_novel_without_search": "bina prior-art search 'novel' kehne wali hypotheses",
}


def render_unknown_block(ctx: Optional[Dict]) -> str:
    """
    §19 — jo check chala hi NAHI, uska naam user ke jawab mein.

    Khaali string laut sakti hai: agar sab kuch naapa gaya to ye block chhapne
    ki zaroorat hi nahi. `0` aur `None` ka farak yahi block sambhalta hai —
    isliye ismein sirf `None` wale naam aate hain, ginti wale counter nahi.
    """
    unknown = [str(name) for name in ((ctx or {}).get("unknown_fields") or [])]
    if not unknown:
        return ""
    lines = [
        UNKNOWN_HEADING,
        "",
        "In cheezon ka check is run mein HO HI NAHI SAKA. Inhe **'zero' na padha "
        "jaaye** — \"dekha aur kuch nahi mila\" aur \"dekha hi nahi gaya\" do "
        "alag baatein hain:",
        "",
    ]
    for name in unknown:
        gloss = _UNKNOWN_HUMAN.get(name)
        lines.append(f"- `{name}`" + (f" — {gloss}." if gloss else ""))
    lines.append("")
    lines.append("Jo check chala aur nateeja 0 nikla, wo upar ki ginti mein 0 "
                 "hi likha hai — is list mein nahi.")
    return "\n".join(lines)


def inject_unknown_block(answer: str, ctx: Optional[Dict]) -> str:
    """
    `render_unknown_block()` ko report ke audit section mein daal deta hai.

    Kyun baad mein inject: `unknown_fields` tabhi pakka hota hai jab counters
    final answer par ek baar chal chuke hon, aur synthesizer us waqt tak apna
    kaam khatam kar chuka hota hai. Idempotent hai (do baar nahi lagta), aur
    audit section na mile to `## Sources` se pehle jaata hai — Sources hamesha
    aakhri section rehta hai.
    """
    return _inject_into_audit(answer, render_unknown_block(ctx), UNKNOWN_HEADING)


def _inject_into_audit(answer: str, block: str, marker: str) -> str:
    """
    `block` ko audit section ke shuru mein daalo — ek hi baar.

    Ye logic pehle `inject_unknown_block` ke andar tha; ab do injector isi ek
    jagah se aate hain, taaki dono ka insertion behaviour bilkul same rahe
    (audit heading ke baad, warna `## Sources` se pehle, warna sabse aakhir).
    """
    from .answer_order import display_heading, section_start

    text = str(answer or "")
    if not block:
        return text
    if not text.strip():
        return block
    if marker and marker in text:
        return text
    audit = section_start(text, "audit")
    if audit >= 0:
        line_end = text.find("\n", audit)
        if line_end < 0:
            return text.rstrip() + "\n\n" + block + "\n"
        head, rest = text[:line_end + 1], text[line_end + 1:]
        return head + "\n" + block + "\n\n" + rest.lstrip("\n")
    sources = text.find(f"## {display_heading('sources')}")
    if sources < 0:
        sources = section_start(text, "sources")
    if sources >= 0:
        return text[:sources] + block + "\n\n" + text[sources:]
    return text.rstrip() + "\n\n" + block + "\n"


def inject_context_block(answer: str, ctx: Optional[Dict]) -> str:
    """
    §7 ki ginti (retrieved ≠ cited ≠ supporting) user ke jawab mein daalo.

    Ye producer pehle se maujood tha (`context_block`), par production mein use
    KOI nahi karta tha — sirf tests padhte the. Nateeja: jawab mein "7 sources
    use hue" jaisi ek hi ginti dikhti thi, aur §7 ka poora point ("18 retrieved
    ko 18 used mat banao") user tak pahunchta hi nahi tha. Wahi galti pehle
    `render_unknown_block` ke saath bhi hui thi.

    Unknown-fields ki poonchh yahan JAAN-BOOJH kar band hai — uska apna alag
    block (`inject_unknown_block`) already lagta hai, aur ek hi list do jagah
    chhapna sirf shor hai.
    """
    block = context_block(ctx, include_unknown=False)
    # ctx hi na ho to block ek honest ek-line ka bayaan hota hai jismein
    # COUNTERS_HEADING nahi aata — us haalat mein usi line ko marker bana lo,
    # warna dobara inject ho jaayega.
    marker = COUNTERS_HEADING if COUNTERS_HEADING in block else block.strip()
    return _inject_into_audit(answer, block, marker)


# §4 — "Final answer se pehle asked vs delivered ledger banega." Ledger banta
# tha (requested.contract_ledger) aur result JSON mein jaata bhi tha, par uski
# ✅/❔/❌ lines KISI ne render nahi ki — yaani user ko kabhi pata nahi chalta
# tha ki jo maanga gaya tha usme se kya NAHI mila. Ab wahi lines audit section
# mein chhapti hain.
LEDGER_HEADING = "### Kya maanga tha vs kya mila (asked vs delivered)"


def render_ledger_block(ledger: Optional[Dict]) -> str:
    """
    `contract_ledger()` ka `lines` hissa user ke padhne laayak block banao.

    Khaali string laut sakti hai: ledger hi na bana ho ya ek bhi item na ho to
    khaali heading chhapna sirf dhokha hai. Yahan koi naya faisla NAHI hota —
    ✅/❔/❌ waise hi aate hain jaise ledger ne tay kiye, taaki result JSON aur
    user ka jawab do alag baat na bolein.
    """
    lines = [str(x) for x in ((ledger or {}).get("lines") or []) if str(x).strip()]
    if not lines:
        return ""
    out = [
        LEDGER_HEADING,
        "",
        "❔ ka matlab \"check hi nahi hua\" hai — ❌ (\"dekha, nahi mila\") se "
        "alag baat hai:",
        "",
    ]
    out.extend(lines)
    missing = [str(i.get("what") or i.get("key"))
               for i in ((ledger or {}).get("mandatory_missing") or [])]
    if missing:
        out.append("")
        out.append("Inke bina jawab ko poora nahi kaha ja sakta: "
                   + ", ".join(missing) + ".")
    return "\n".join(out)


def inject_ledger_block(answer: str, ledger: Optional[Dict]) -> str:
    """`render_ledger_block()` ko audit section mein daalo — ek hi baar."""
    return _inject_into_audit(answer, render_ledger_block(ledger), LEDGER_HEADING)


# §9 — paanch claim-nateeje (SUPPORTED / PARTIALLY SUPPORTED / UNSUPPORTED /
# CONTRADICTED / UNABLE TO VERIFY) sirf result JSON mein pade rehte the. User ke
# jawab mein claim ke aage kuch bhi nahi likha tha, isliye "source cite hua"
# aur "dava verify hua" ka farak dikhta hi nahi tha — §8 ka poora point wahi
# hai. Ab har critical dava ka apna faisla audit mein chhapta hai.
CLAIMS_HEADING = "### Har critical dava par alag faisla"

_CLAIM_RESULT_NAMES = ("SUPPORTED", "PARTIALLY SUPPORTED", "UNSUPPORTED",
                       "CONTRADICTED", "UNABLE TO VERIFY")


def render_claim_block(ctx: Optional[Dict]) -> str:
    """
    §8/§9 — per-claim faisla, dava ka text DOBARA likhe bina.

    Jaan-boojh kar sirf structure chhapta hai (claim id, nateeja, entailment,
    padhne ki gehrai, source id, source ki haalat) — dava ka vaakya ya source ka
    passage yahan repeat nahi hota. Wajah: wahi vaakya audit section mein dobara
    likhne se ek hi dava do jagah dikhta hai, aur retracted source ka passage
    audit mein utha kar likhna use chupke se "evidence" bana deta hai.

    Khaali string laut sakti hai — koi critical dava hi na ho to khaali heading
    chhapna dhokha hai.
    """
    if not ctx:
        return ""
    counts = ctx.get("claim_results")
    rows = list(ctx.get("critical_claim_evidence_spans") or [])
    if counts is None and not rows:
        return ""
    out = [CLAIMS_HEADING, ""]
    if counts is None:
        out.append("Claim-level verification is run mein chali hi NAHI — isliye "
                   "kisi dave ke aage \"verified\" nahi likha ja sakta.")
        return "\n".join(out)
    out.append("\"Citation mil gayi\" aur \"dava sach nikla\" do alag baatein "
               "hain. Paanch nateeje alag-alag gine jaate hain:")
    out.append("")
    out.append("- " + " | ".join(
        f"{name}: {_num((counts or {}).get(name))}"
        for name in _CLAIM_RESULT_NAMES))
    total = ctx.get("critical_claims")
    if total is not None:
        out.append(f"- Critical dave: {_num(total)}; inme se bina support wale: "
                   f"{_num(ctx.get('unsupported_critical_claims'))}, "
                   f"verify hi na ho paane wale: "
                   f"{_num(ctx.get('unverifiable_critical_claims'))}.")
    if rows:
        out.append("")
        for row in rows[:8]:
            if not isinstance(row, dict):
                continue
            cid = str(row.get("claim_id") or "?")
            src = ", ".join(str(x) for x in (row.get("source_ids")
                                             or row.get("cited_ids") or []))
            bits = [f"nateeja: **{row.get('result') or 'pata nahi'}**"]
            if row.get("entailment"):
                bits.append(f"source ka text dave ko: {row['entailment']}")
            if row.get("access_depth"):
                bits.append(f"padhne ki gehrai: {row['access_depth']}")
            if row.get("epistemic_type"):
                bits.append(f"label: {row['epistemic_type']}")
            spans = row.get("evidence_spans") or row.get("spans") or []
            bits.append("saboot ka tukda mila" if spans
                        else "saboot ka tukda NAHI mila")
            out.append(f"- {cid}" + (f" [{src}]" if src else "") + " — "
                       + "; ".join(bits) + ".")
            if row.get("source_quality"):
                out.append(f"  - Source ki haalat: {row['source_quality']}.")
        if len(rows) > 8:
            out.append(f"- (aur {len(rows) - 8} critical dave — poora record "
                       f"technical audit ke claim_checks mein hai.)")
    return "\n".join(out)


def inject_claim_block(answer: str, ctx: Optional[Dict]) -> str:
    """`render_claim_block()` ko audit section mein daalo — ek hi baar."""
    return _inject_into_audit(answer, render_claim_block(ctx), CLAIMS_HEADING)


def context_block(ctx: Optional[Dict], include_unknown: bool = True) -> str:
    """
    Audit section ke liye saaf-saaf ginti — retrieved ≠ used, saaf likha hua.

    `include_unknown=False` sirf tab do jab "kaunse check ho hi nahi sake" wali
    list alag block ban kar already chhap rahi hai (dekho
    `inject_context_block`) — ek hi list do jagah likhna sirf shor hai.
    """
    if not ctx:
        return ("Quality counters chale hi nahi, isliye is jawab ke saath koi "
                "ginti nahi di ja rahi (jhoothi ginti dene se behtar hai).")
    lines = ["**Ginti (har ek ka matlab alag hai):**", ""]
    lines.append(
        f"- Pack mein aaye (retrieved): {_num(ctx.get('sources_retrieved'))} — "
        f"inme se answer mein cite hue: {_num(ctx.get('sources_cited'))}, "
        f"bilkul use nahi hue: {_num(ctx.get('sources_unused'))}. "
        f"Retrieval ki ginti evidence ki taakat NAHI hai.")
    lines.append(
        f"- Critical claim ko asli support dene wale source: "
        f"{_num(ctx.get('sources_supporting_critical_claims'))} "
        f"(yahi sabse matlab ki ginti hai).")
    lines.append(
        f"- Sawaal ki baat seedha karne wale (directly relevant): "
        f"{_num(ctx.get('directly_relevant_sources'))}; average relevance "
        f"{_num(ctx.get('average_relevance'))}.")
    lines.append(
        f"- Independent families: {_num(ctx.get('independent_source_families'))} "
        f"(alag URL: {_num(ctx.get('distinct_urls'))}) — alag URL alag source "
        f"nahi hota, ek hi group ka ek hi method ek hi family hai.")
    gate = ctx.get("relevance_gate") or {}
    if gate.get("ran"):
        checklist = list(gate.get("checklist") or gate.get("dimensions") or [])
        lines.append(
            f"- Sawaal ki baat SACH MEIN test karne wale source: "
            f"{_num(gate.get('tests_proposition'))}; nahi karne wale: "
            f"{_num(gate.get('does_not_test'))}; faisla nahi ho saka: "
            f"{_num(gate.get('undecided'))}. Har source par "
            f"{len(checklist)} cheezein alag-alag dekhi gayi "
            f"(entity, mechanism, naap, population, tareeka, zaroori raasta, "
            f"abstract ka nateeja, shirshak, field, aur aakhir mein 'ye source "
            f"sawaal ki BAAT test karta hai ya nahi' ka alag faisla).")
        failed = gate.get("failed_dimensions") or {}
        if failed:
            detail = ", ".join(f"{k}: {v}" for k, v in list(failed.items())[:5])
            lines.append(f"  - Sabse zyada kis cheez ki kami rahi — {detail}.")
        codes = {k: v for k, v in (gate.get("reject_codes") or {}).items() if v}
        if codes:
            lines.append("  - Hataye gaye sources ki wajah (code se): "
                         + ", ".join(f"{k}={v}" for k, v in codes.items()) + ".")
    else:
        lines.append("- Relevance ka proposition-test is run mein chala hi nahi, "
                     "isliye \"kitne source sawaal ki baat test karte hain\" ka "
                     "jawab yahan nahi hai (0 likhna galat hota).")
    # §11 — takraav ka hisaab: kitne bache, kitne jaanch kar hataye gaye.
    rejected = ctx.get("contradictions_rejected")
    if ctx.get("contradictions") is not None:
        lines.append(
            f"- Takraav (contradictions): {len(ctx['contradictions'])} report hue"
            + ("" if rejected is None else
               f", aur {rejected} 'takraav' jaanch kar hataye gaye")
            + ".")
        codes = ctx.get("contradiction_reject_codes") or {}
        shown = {k: v for k, v in codes.items() if v}
        if shown:
            lines.append("- Kis wajah se hataye gaye: "
                         + ", ".join(f"{k}: {v}" for k, v in shown.items())
                         + " (sirf saal ka farq ya topic hi alag hona takraav "
                           "nahi hai).")
        if ctx.get("contradictions_schema_complete") is False:
            lines.append("- ⚠️ Kuch takraav ka structured record adhoora hai "
                         "(proposition/dono claims/saboot ka tukda) — unhe "
                         "pakka takraav na maanein.")
    else:
        lines.append("- Takraav ki jaanch is run mein chali hi nahi, isliye "
                     "\"koi takraav nahi mila\" likhna galat hota.")
    if ctx.get("citations_without_source"):
        lines.append(
            f"- ⚠️ {ctx['citations_without_source']} citation aisi thi jiska source "
            f"pack mein hi nahi hai.")
    if ctx.get("critical_no_source_claims"):
        lines.append(
            f"- ⚠️ {ctx['critical_no_source_claims']} critical dava bina kisi source "
            f"ke likhi gayi thi.")
    mismatches = ctx.get("access_depth_mismatches")
    if mismatches:
        lines.append(
            f"- ⚠️ {len(mismatches)} jagah padhne ki gehrai ka dava asli gehrai se "
            f"zyada tha.")
    if ctx.get("hypothesis_fact_mix_count"):
        lines.append(
            f"- ⚠️ {ctx['hypothesis_fact_mix_count']} jagah app ki hypothesis aur "
            f"established fact ghul-mil gaye the.")
    # §13-§18 — app ki apni hypothesis ka hisaab, sources se ALAG.
    hyp = ctx.get("hypothesis_report")
    if hyp:
        novelty = ", ".join(f"{k}: {v}" for k, v in
                            (hyp.get("novelty_counts") or {}).items())
        bands = ", ".join(f"{k}: {v}" for k, v in
                          (hyp.get("confidence_bands") or {}).items())
        lines.append(
            f"- App ki apni hypothesis: {hyp.get('count')} bani"
            + (f" | novelty: {novelty}" if novelty else "")
            + (f" | confidence band: {bands}" if bands else "")
            + ". Ye app ka apna soch hai — kisi source ka claim nahi.")
        if hyp.get("known_ideas_flagged"):
            lines.append(
                f"- {len(hyp['known_ideas_flagged'])} hypothesis pehle se "
                f"maujood ideas par bani hain (PBH/MOND/dark photon jaisi "
                f"cheezein app ki khoj nahi hain) — kaunsi, ye LAB section ke "
                f"card par likha hai.")
        if hyp.get("claimed_novel_without_search"):
            lines.append(
                f"- ⚠️ {hyp['claimed_novel_without_search']} hypothesis 'novel' "
                f"dikh rahi thi jabki prior-art search nahi chali — label "
                f"'NOVELTY UNVERIFIED' hi sahi hai.")
        if hyp.get("incomplete_ids"):
            lines.append(
                f"- ⚠️ {len(hyp['incomplete_ids'])} hypothesis ka record adhoora "
                f"hai (mechanism/prior work/confidence jaisa hissa nahi bana) — "
                f"ID LAB section ke card par hi likhi hai.")
        if hyp.get("missing_risk_checks"):
            lines.append(
                f"- ⚠️ {len(hyp['missing_risk_checks'])} safety se judi hypothesis "
                f"par risk checks nahi likhe gaye — card LAB section mein hai.")
    elif ctx.get("hypotheses_present") is None:
        lines.append("- App ki apni hypothesis ka step is run mein chala hi nahi.")
    unknown = ctx.get("unknown_fields") or []
    if unknown and include_unknown:
        lines.append("")
        lines.append("_In cheezon ka check HO HI NAHI SAKA (inhe 'zero' na padha "
                     "jaaye): " + ", ".join(unknown) + "._")
    return "\n".join(lines)
