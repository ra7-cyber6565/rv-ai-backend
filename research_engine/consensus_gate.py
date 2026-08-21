"""
§11 ka consensus gate — "retrieved links ka dher = scientific consensus NAHI".

Live failure (superconductivity test #3): report ne likha ki sources mein
"apparent agreement" hai. Sach ye tha — sources mein maternal deaths aur
banana-fibre prosthetics the, kisi ka full text nahi pada gaya tha, opposition
(criticism/contradictory findings) ki search kabhi chali hi nahi, aur reasoning
pass quota se mar gaya tha. Us haalat mein "sehmati" ka koi bhi level chhapna
jhooth hai.

Isliye consensus ab GATE ke peeche hai. Chhe shart — user ke bug report se, usi
kram mein:

  1. source relevance kaafi ooncha ho
  2. claim-level evidence extraction hua ho (sirf metadata/title nahi)
  3. support AUR opposition — dono taraf ki search hui ho
  4. duplicates hata diye gaye hon
  5. kaafi independent sources hon (ek hi origin ki copies nahi)
  6. reasoning / contradiction analysis poora hua ho

Ek bhi shart tooti to level generate hi nahi hota, aur report mein exactly ye
vaakya jaata hai:

    "Consensus evaluate nahi kiya ja saka."

SAATVI SHART — SIRF TAB JUDTI HAI JAB PACK MEIN PATENT HO (₹0 patent batch,
point 4 + 7):

  7. patent ke alawa kaafi scientific sources hon

Patent legal document hai: uske claims "ye humara invention hai" wale dawe hain,
kisi experiment ka nateeja nahi. Ek hi topic par 5 patent mil jaana bilkul aam
hai (companies aas-paas file karti hain), aur purane counting rule mein wo 5
"independent origin" ban kar consensus ka darwaza khol dete — yaani hum kehte
"sources sehmat hain" jabki ek bhi scientific finding check nahi hui thi. Isliye
patent wale pack mein consensus ke liye patent-ke-ALAWA sources ki ginti dekhi
jaati hai. Jis pack mein patent hi nahi hai, us par ye shart lagti hi nahi (aur
purane run/report ka behaviour waisa hi rehta hai).

Module jaan-boojh kar pure-Python hai (koi model, koi network) taaki offline
test ho sake.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

# §11 ka maanga hua text, shabd-ba-shabd. Ise chhota ya "sudhaar kar" mat likhna.
CONSENSUS_UNAVAILABLE = "Consensus evaluate nahi kiya ja saka."

# Thresholds ek jagah — test aur report dono yahi padhte hain.
MIN_AVG_RELEVANCE = 0.40      # pack ka average topic match
STRONG_RELEVANCE = 0.45       # "is source ka content sach mein kaam ka hai"
MIN_STRONG_SOURCES = 3        # itne majboot sources se kam par consensus nahi
MIN_EXTRACTED = 3             # itne sources ka asli text pada gaya ho
MIN_INDEPENDENT = 3           # alag-alag origin
# Patent wale pack mein: patent ke ALAWA itne sources chahiye, warna "sehmati"
# asal mein patent claims ki ginti ban jaati hai (dekho module docstring, shart 7).
MIN_SCIENCE_SOURCES = 3

# Opposition search hui ya nahi — ye nishaan query text mein dhoondte hain.
# "critical" jaan-boojh kar list mein NAHI hai: "critical temperature" ek normal
# superconductivity term hai, opposition search nahi. Aise false positive se gate
# apne aap khul jaata, jo poori mehnat bekaar kar deta.
OPPOSITION_MARKERS = (
    "criticism", "critique", "limitation", "contradict", "counter-evidence",
    "counterevidence", "counter evidence", "refut", "debunk", "retract",
    "replication", "failed", "null result", "negative result", "no effect",
    "does not", "controvers", "disput", "skeptic", "rebuttal",
    "unsuccessful", "not reproducible", "irreproducib",
)

# Jo read levels "asli text pada gaya" maane jaate hain. "metadata" kabhi nahi —
# title aur DOI se claim-level evidence nahi nikalta.
_EXTRACTED_LEVELS = ("abstract", "full_text")
_MIN_PASSAGE_CHARS = 120


def opposition_in_queries(queries: Iterable) -> bool:
    """Kya chali hui queries mein kam se kam ek counter-evidence query thi?"""
    for q in queries or []:
        low = str(q or "").lower()
        if any(marker in low for marker in OPPOSITION_MARKERS):
            return True
    return False


def _extracted_count(pack) -> int:
    """
    Kitne sources ka claim-level text sach mein nikala gaya.

    Do tarah se ginti hoti hai aur dono asli hain: source ka read level
    abstract/full_text ho, ya uska passage (jo reasoning ko bheja gaya) itna
    bada ho ki usme koi claim ho sakti hai. Sirf title/metadata se stance
    nikaalna hi wo bug tha jise ye gate rok raha hai.
    """
    by_id: Dict[str, int] = {}
    for p in getattr(pack, "passages", None) or []:
        sid = str(getattr(p, "source_id", "") or "")
        text = str(getattr(p, "text", "") or "")
        if sid:
            by_id[sid] = max(by_id.get(sid, 0), len(text.strip()))

    count = 0
    for s in getattr(pack, "sources", None) or []:
        level = ""
        reader = getattr(s, "reading_level", None)
        if callable(reader):
            try:
                level = str(reader() or "")
            except Exception:      # pragma: no cover - defensive
                level = ""
        level = level or str(getattr(s, "read_level", "") or "")
        chars = by_id.get(str(getattr(s, "source_id", "") or ""), 0)
        if not chars:
            chars = len(str(getattr(s, "snippet", "") or "").strip())
        if level in _EXTRACTED_LEVELS:
            count += 1
        elif level != "metadata" and chars >= _MIN_PASSAGE_CHARS:
            # Snippet bhi chalega, par tab jab wo itna bada ho ki usme ek poori
            # claim ho. Sirf title/metadata wale source kabhi nahi ginte.
            count += 1
    return count


def _patent_split(pack) -> tuple:
    """
    (patent_sources, science_sources) — pack ke andar se, andaaze se nahi.

    Naye pack ke paas apne helper hain (`patent_sources()`/`science_sources()`),
    par ye module purane/fake pack objects par bhi chalta hai (test aur purane
    run), isliye fallback mein `is_patent` / source_type dekh liya jaata hai.
    """
    sources = list(getattr(pack, "sources", None) or [])
    getter = getattr(pack, "patent_sources", None)
    science_getter = getattr(pack, "science_sources", None)
    if callable(getter) and callable(science_getter):
        try:
            return list(getter() or []), list(science_getter() or [])
        except Exception:      # pragma: no cover - defensive
            pass
    patents = [s for s in sources
               if bool(getattr(s, "is_patent", False))
               or str(getattr(getattr(s, "source_type", ""), "value",
                              getattr(s, "source_type", ""))) == "patent"]
    ids = {id(s) for s in patents}
    return patents, [s for s in sources if id(s) not in ids]


def _dedup_done(pack) -> bool:
    """Duplicates hataye gaye — retrieval filter se, andaaze se nahi."""
    info = dict(getattr(pack, "retrieval_filter", None) or {})
    if info.get("deduplicated"):
        return True
    # Purane run/fake pack: agar candidates ki ginti likhi hai to dedup chala tha
    # (rank() dedup ke BAAD hi ye number likhta hai).
    return bool(info.get("candidates"))


@dataclass
class GateResult:
    """Kaun shart poori hui, kaun nahi — sab likha hua, chhupa hua kuch nahi."""
    checks: List[Dict] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str, ok: str = "") -> None:
        """
        `detail` = shart TOOTNE ki wajah. Pass hone par wahi line likhna
        confusing tha ("Sirf 5 independent origin mile, chahiye 3" — jabki wo
        pass tha), isliye pass ke liye alag chhoti line jaati hai.
        """
        self.checks.append({"condition": name, "passed": bool(passed),
                            "detail": (ok or "shart poori hui") if passed
                            else detail})

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c["passed"] for c in self.checks)

    @property
    def unmet(self) -> List[Dict]:
        return [c for c in self.checks if not c["passed"]]

    @property
    def unmet_reasons(self) -> List[str]:
        return [c["detail"] for c in self.unmet]

    def note(self) -> str:
        if self.passed:
            return ("Consensus ka andaaza retrieved sources tak seemit hai. Ek hi "
                    "info ki copies ko alag evidence nahi gina gaya, lekin ye "
                    "poore literature ka survey bhi nahi hai.")
        lines = [CONSENSUS_UNAVAILABLE,
                 "Wajah — ye shartein poori nahi hui:"]
        lines += [f"- {reason}" for reason in self.unmet_reasons]
        lines.append("Retrieved links ka dher scientific consensus nahi hota, "
                     "isliye koi sehmati-level nahi banaya gaya.")
        return "\n".join(lines)

    def to_dict(self) -> Dict:
        return {
            "passed": self.passed,
            "checks": [dict(c) for c in self.checks],
            "unmet": [c["condition"] for c in self.unmet],
            "unmet_reasons": list(self.unmet_reasons),
        }


def evaluate(pack, contradictions: Optional[Sequence] = None,
             contradiction_analysis_done: Optional[bool] = None,
             reasoning_complete: Optional[bool] = None,
             opposition_searched: Optional[bool] = None,
             queries: Optional[Iterable] = None,
             independent_sources: Optional[int] = None) -> GateResult:
    """
    Chhe shart check karo. `contradictions=None` ka matlab "analysis chala hi
    nahi" hai; khaali list ka matlab "chala, kuch mila nahi" — dono alag hain.

    Pack mein patent hone par ek SAATVI shart bhi judti hai ("patent ke alawa
    kaafi scientific sources") — dekho module docstring.
    """
    result = GateResult()
    sources = list(getattr(pack, "sources", None) or [])

    # 1. relevance kaafi ooncha
    avg = float(getattr(pack, "avg_relevance", 0.0) or 0.0)
    strong = len([s for s in sources
                  if float(getattr(s, "relevance_score", 0.0) or 0.0)
                  >= STRONG_RELEVANCE])
    result.add(
        "source_relevance",
        avg >= MIN_AVG_RELEVANCE and strong >= MIN_STRONG_SOURCES,
        f"Sources ka topic match kaafi nahi tha (average {avg:.2f}, chahiye "
        f"{MIN_AVG_RELEVANCE:.2f}; majboot match wale {strong} source, chahiye "
        f"{MIN_STRONG_SOURCES}).",
        ok=f"Topic match theek hai (average {avg:.2f}, majboot match wale {strong}).",
    )

    # 2. claim-level evidence extraction
    extracted = _extracted_count(pack)
    result.add(
        "claim_level_extraction",
        extracted >= MIN_EXTRACTED,
        f"Sirf {extracted} source ka asli text (abstract/full text) nikala gaya, "
        f"chahiye {MIN_EXTRACTED} — title aur metadata se sehmati nahi naapi ja "
        f"sakti.",
        ok=f"{extracted} source ka asli text (abstract/full text) padha gaya.",
    )

    # 3. support AUR opposition, dono ki search
    if opposition_searched is None:
        pool = list(queries or []) or list(
            getattr(pack, "search_queries", None) or [])
        opposition_searched = opposition_in_queries(pool)
    result.add(
        "support_and_opposition_search",
        bool(opposition_searched),
        "Sirf support-side search hui — criticism / contradictory findings wali "
        "query chali hi nahi, isliye 'sab sehmat hain' kehna galat hoga.",
        ok="Support aur opposition — dono taraf ki search chali.",
    )

    # 4. duplicates hataye gaye
    result.add(
        "duplicates_removed",
        _dedup_done(pack),
        "Duplicate sources hataye gaye hain — iska record hi nahi hai, isliye "
        "ek hi baat ki copies sehmati jaisi dikh sakti hain.",
        ok="Duplicate/copy sources hata diye gaye the.",
    )

    # 5. kaafi independent sources
    if independent_sources is None:
        independent_sources = int(getattr(pack, "independent_source_count", 0) or 0)
    result.add(
        "independent_sources",
        independent_sources >= MIN_INDEPENDENT,
        f"Sirf {independent_sources} independent origin mile, chahiye "
        f"{MIN_INDEPENDENT}.",
        ok=f"{independent_sources} alag-alag independent origin mile.",
    )

    # 6. reasoning + contradiction analysis poora
    if contradiction_analysis_done is None:
        contradiction_analysis_done = contradictions is not None
    if reasoning_complete is None:
        reasoning_complete = bool(getattr(pack, "reasoning_complete", False))
    if not contradiction_analysis_done:
        detail = ("Contradiction analysis chali hi nahi, isliye opposition kitni "
                  "hai ye pata nahi.")
    else:
        done = int(getattr(pack, "reasoning_done", 0) or 0)
        planned = int(getattr(pack, "reasoning_planned", 0) or 0)
        detail = (f"Reasoning analysis adhoora raha ({done}/{planned} pass), "
                  f"isliye sehmati ka faisla nahi ho sakta.")
    result.add("analysis_complete",
               bool(contradiction_analysis_done) and bool(reasoning_complete),
               detail,
               ok="Contradiction + reasoning analysis dono poore hue.")

    # 7. (SIRF patent wale pack par) patent ke alawa kaafi scientific sources
    patent_sources, science = _patent_split(pack)
    if patent_sources:
        result.add(
            "science_beyond_patents",
            len(science) >= MIN_SCIENCE_SOURCES,
            f"Is pack mein {len(patent_sources)} patent hain par patent ke alawa "
            f"sirf {len(science)} source, chahiye {MIN_SCIENCE_SOURCES}. Patent "
            f"legal dawa hai, experiment ka nateeja nahi — patent ginti se "
            f"'sehmati' nahi banti.",
            ok=(f"Patent ke alawa {len(science)} scientific source hain "
                f"({len(patent_sources)} patent sirf context ke liye)."),
        )
    return result
