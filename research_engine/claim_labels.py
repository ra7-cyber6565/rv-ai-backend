"""Claim-label honesty gate.

Compatibility + production rule:
- default helper behaviour remains depth/citation-only for old tests/callers;
- the production orchestrator passes ``check_entailment=True``;
- in that strict path, full-text access alone is NOT enough: the same cited
  source must pass citation + relevance + support + depth + quality (A-E).

No label is ever upgraded here.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .citation import labelled_claim_spans
from .models import EvidencePack
from .quality_signals import WEAK_METHODOLOGY

ESTABLISHED = "ESTABLISHED"
SOURCE_REPORTED = "SOURCE-REPORTED"
UNVERIFIED = "UNVERIFIED"

# ── Kitab/recording ka kathan ≠ experiment ka proof ──────────────────────────
# Patent ke liye ye rule pehle se yahan hai (legal dawa ≠ proof). Naapa hua
# chhed: archive.org par POORI padhi gayi 1901 ki theosophy kitab ka
# metaphysical dawa "[ESTABLISHED]" reh jaata tha, sirf isliye ki archive.org
# `relevance._TIER_3` host list mein hai → quality 0.530, aur
# `evidence_verification_legacy._quality_state` 0.45 se upar ko True kehta hai.
# Wahi kitab 2015 ki ho to quality 0.580 — yaani umr ka sawaal hi nahi tha,
# HOST ka tha. Usi kitab ko example-press.com par rakho to quality 0.430 par
# gir jaati thi: yaani ESTABLISHED milna ya na milna hosting ka ittefaaq tha,
# kisi epistemic wajah ka nateeja nahi. Isliye faisla source ke apne
# refereeing signal par rakha gaya hai, host par nahi.
STATEMENT_ONLY_TYPES: Tuple[str, ...] = ("book", "transcript")
REASON_STATEMENT_ONLY = "book_statement_not_experimental_proof"

STATEMENT_ONLY_KNOWN_LIMIT = """Likhi hui seema (chhupayi nahi):
1. Door sirf `book` aur `transcript` source_type par lagta hai. `web`,
   `document`, `dataset`, `encyclopedia`, `paper` par NAHI — kyunki CME /
   Federal Reserve / BIS jaisi sansthagat page `web` hote hain aur unka apna
   kathan hi primary record hota hai (trading contract wahi maangta hai).
   Naapa gaya: aisa CME page is door ke baad bhi ESTABLISHED de sakta hai.
2. Chhoot (escape) sirf 4 naapne-layak signal par milti hai: peer_reviewed is
   True, DOI mojood, methodology_rank > WEAK_METHODOLOGY (yaani asli study
   design, `opinion`/`narrative_review`/`qualitative` nahi), ya
   is_primary is True. Ek peer-reviewed + DOI wala academic monograph isliye
   ESTABLISHED de sakta hai — ye jaan-boojh kar rakha gaya hai.
3. Kisi kitab ke MAZMOON par koi faisla nahi hota. Koi "occult/spiritual
   shabd" list NAHI banayi gayi — wahi purani galti thi. Ek 1901 ki science
   kitab bhi SOURCE-REPORTED hogi, aur ye theek hai: uska dawa "kitab ye
   kehti hai" hai, "ye sabit ho chuka hai" nahi.
4. Dawa answer se HATTA nahi hai. Label ESTABLISHED se SOURCE-REPORTED hota
   hai, citation waisi hi rehti hai — kuch chhupta ya girta nahi.
"""


def proof_signal(record) -> str:
    """Us signal ka NAAM jo is source ko strong label dene laayak banata hai.

    Khaali string = koi refereeing signal nahi mila. Naam wapas karte hain
    (bool nahi) taaki audit ki wajah mein likha ja sake ki chhoot kyu mili.
    """
    if record is None:
        return ""
    try:
        if getattr(record, "peer_reviewed", None) is True:
            return "peer_reviewed"
        if str(getattr(record, "doi", "") or "").strip():
            return "doi"
        rank = int(getattr(record, "methodology_rank", -1) or -1)
        if rank > WEAK_METHODOLOGY:
            return f"methodology:{str(getattr(record, 'methodology', '') or '').strip()}"
        if getattr(record, "is_primary", None) is True:
            return "primary_record"
    except Exception:  # pragma: no cover - defensive
        return ""
    return ""


def statement_only_source(record) -> bool:
    """True = ye source apna KATHAN de sakta hai, experiment ka proof nahi."""
    if record is None:
        return False
    try:
        if getattr(record, "is_patent", False):
            # Patent ka apna alag, purana door hai — precedence yahan tay hoti
            # hai. Naapa hua sach: aaj ke `models.SourceRecord` mein `is_patent`
            # khud `source_type == PATENT` se banta hai, isliye is line ka
            # SourceRecord par pahunchna mumkin nahi (redundant, chhupaya nahi).
            # Ye guard duck-typed record ke liye hai, jinhe ye helper accept
            # karta hai; test isi precedence ko pin karta hai.
            return False
        stype = getattr(record, "source_type", None)
        name = str(getattr(stype, "value", stype) or "").strip().lower()
    except Exception:  # pragma: no cover - defensive
        return False
    if name not in STATEMENT_ONLY_TYPES:
        return False
    return not proof_signal(record)


_STRONG_LABEL_RE = re.compile(
    r"\[\s*(ESTABLISHED(?:\s+FACT)?|FACT|STRONG\s+EVIDENCE)\s*\]",
    re.IGNORECASE,
)
_SID_RE = re.compile(r"\[\s*S\s*(\d{1,3})[^\]]*\]", re.IGNORECASE)
_NO_SOURCE_RE = re.compile(r"\[\s*NO[\s\-]?SOURCE\s*\]", re.IGNORECASE)
_FULL = "full_text"


def _cited_ids(line: str) -> List[str]:
    out: List[str] = []
    for num in _SID_RE.findall(line or ""):
        sid = f"S{int(num)}"
        if sid not in out:
            out.append(sid)
    return out


def _records(line: str, pack: Optional[EvidencePack]) -> List:
    if pack is None:
        return []
    rows = [pack.by_id(sid) for sid in _cited_ids(line)]
    return [row for row in rows if row is not None]


def _has_full_text_cite(line: str, pack: Optional[EvidencePack]) -> bool:
    """Whether a non-patent cited source can enter the strict A-E gate.

    A pure statement source (un-refereed book/recording) reads as "full text"
    but is not eligible for a strong label, so its downgrade must NOT be
    reported as "A-E chali aur fail hui" — wo eligibility ka faisla hai.
    """
    for record in _records(line, pack):
        try:
            if getattr(record, "is_patent", False):
                continue
            if statement_only_source(record):
                continue
            if record.reading_level() == _FULL:
                return True
        except Exception:  # pragma: no cover - defensive
            continue
    return False


def _allowed_row_passed(item, allowed_ids: List[str]) -> bool:
    """Kya A-E ki chaaron dimension ek ALLOWED source par ek saath paas hui?"""
    keys = ("relevance", "support", "depth", "quality")
    for row in list(getattr(item, "source_checks", None) or []):
        if str(row.get("source_id") or "") not in allowed_ids:
            continue
        if all(row.get(key) is True for key in keys):
            return True
    return False


def _ae_verdict(line: str, pack: Optional[EvidencePack],
                allowed_ids: Optional[List[str]] = None
                ) -> Tuple[Optional[bool], str]:
    """Cumulative same-source A-E result; None means context unavailable.

    ``allowed_ids`` (jab diya jaaye) ye pakka karta hai ki A-E paas karne wali
    ROW usi source ki ho jo strong label dene laayak hai. Iske bina ek mila-jula
    line ("[S1] kitab + [S2] paper") mein kitab ki row paas karke ESTABLISHED
    nikaal sakti thi.
    """
    if pack is None:
        return None, "claim-level A-E context available nahi tha"
    try:
        from .evidence_verification import EvidenceVerifier
        report = EvidenceVerifier().verify(line, pack)
    except Exception as exc:  # strong labels fail closed
        return False, f"claim-level A-E verification run nahi ho saki ({type(exc).__name__})"
    if not report.items:
        return False, "labelled factual claim A-E verifier ne parse nahi ki"
    item = report.items[0]
    if item.verdict == "verified_against_available_evidence":
        if allowed_ids is not None and not _allowed_row_passed(item, allowed_ids):
            return False, (
                "A-E us source par pass hui jo sirf apna KATHAN de sakta hai "
                "(kitab/recording), experiment ka proof nahi "
                f"({REASON_STATEMENT_ONLY})"
            )
        return True, (
            "same cited source ne citation+relevance+support+depth+quality A-E gate pass kiya"
        )
    return False, item.note or "claim-level A-E gate pass nahi hua"


def line_verdict(
    line: str,
    pack: Optional[EvidencePack],
    check_entailment: bool = False,
) -> Tuple[str, str]:
    """Return the strongest label allowed by depth, A-E, and patent rules.

    Patent claims are legal assertions rather than experimental proof. A
    patent-only line therefore stays SOURCE-REPORTED even when its claims or
    description were read. An un-refereed book or recording is treated the same
    way: reading it end to end proves what it SAYS, not that the statement is
    established (see ``STATEMENT_ONLY_KNOWN_LIMIT``). In the production strict
    path, a remaining source must independently pass the cumulative same-source
    A-E verification gate.
    """
    ids = _cited_ids(line)
    records = _records(line, pack)

    if not records:
        if _NO_SOURCE_RE.search(line or ""):
            return UNVERIFIED, "is line par koi source nahi hai ([NO-SOURCE])"
        if ids:
            return UNVERIFIED, (
                "cite kiye gaye " + ", ".join(ids) + " evidence pack mein nahi mile"
            )
        return UNVERIFIED, "is line par koi [S#] citation nahi hai"

    levels = {}
    depths: Dict[str, str] = {}
    patent_ids: List[str] = []
    statement_ids: List[str] = []
    kinds: Dict[str, str] = {}
    for record in records:
        try:
            level = record.reading_level()
        except Exception:  # pragma: no cover
            level = "metadata"
        levels[record.source_id] = level
        # §9 — user ko dikhne wali wajah mein wahi 5 allowed access label jaate
        # hain jo models.py tay karta hai. "full text padha gaya" likh dena us
        # source ke liye jhooth tha jiske 30 mein se 18 page process hue the.
        try:
            depths[record.source_id] = record.access_depth()
        except Exception:                      # pragma: no cover - defensive
            depths[record.source_id] = ""
        if getattr(record, "is_patent", False):
            patent_ids.append(record.source_id)
        elif statement_only_source(record):
            statement_ids.append(record.source_id)
            stype = getattr(record, "source_type", None)
            kinds[record.source_id] = str(
                getattr(stype, "value", stype) or "source").strip().lower()

    def _depth_of(sid: str) -> str:
        return depths.get(sid) or levels.get(sid, "metadata")

    # Patent full text can provide prior-art context, never scientific proof.
    full = [sid for sid, level in levels.items()
            if level == _FULL and sid not in patent_ids]
    if not full:
        patent_full = [sid for sid in patent_ids if levels.get(sid) == _FULL]
        if patent_full and len(patent_ids) == len(levels):
            return SOURCE_REPORTED, (
                f"is line ka evidence sirf patent(s) hai ({', '.join(patent_full)}) — "
                "patent ke claims LEGAL dawe hain, experiment ka proof nahi")
        detail = ", ".join(f"{sid}: {_depth_of(sid)}" for sid in levels)
        if patent_ids:
            detail += f" (patent: {', '.join(patent_ids)} — legal dawa, proof nahi)"
        return SOURCE_REPORTED, f"poora text nahi mila — {detail}"

    # Bina-refereed kitab/recording: poora padh lena sirf ye sabit karta hai ki
    # wo TEXT kya KEHTA hai. Ye patent wale rule ka hi doosra roop hai.
    proof = [sid for sid in full if sid not in statement_ids]
    if not proof:
        kind = ", ".join(f"{sid} ({kinds.get(sid, 'source')})"
                         for sid in full if sid in statement_ids)
        return SOURCE_REPORTED, (
            f"is line ka evidence sirf bina-refereed {kind} hai — poora text "
            "padha gaya, par ye us kitab/recording ka KATHAN hai, experiment "
            f"ka proof nahi ({REASON_STATEMENT_ONLY})")

    shown = ", ".join(f"{sid}: {_depth_of(sid)}" for sid in proof)
    if not check_entailment:
        return ESTABLISHED, f"source ka text padha gaya — {shown}"

    eligible = [sid for sid in levels
                if sid not in patent_ids and sid not in statement_ids]
    verified, why = _ae_verdict(line, pack, allowed_ids=eligible)
    if verified is True:
        return ESTABLISHED, why
    if verified is None:
        # Strict check requested but context missing: strong label ko pass mat
        # karo. Unknown verification is not PASS.
        return UNVERIFIED, why
    return UNVERIFIED, f"source ka text mila ({shown}), lekin {why}"


def downgrade(
    text: str,
    pack: Optional[EvidencePack] = None,
    check_entailment: bool = False,
) -> Tuple[str, Dict]:
    """Strong user-facing labels ko deterministic evidence state se match karao."""
    body = text or ""
    report: Dict = {
        "checked": 0,
        "downgraded": 0,
        "to_source_reported": 0,
        "to_unverified": 0,
        "a_e_checked": 0,
        "a_e_failed": 0,
        # Compatibility name used by Claude's older tests. It now means a
        # full-text strong label was blocked by the stricter A-E gate; an
        # abstract/snippet depth downgrade is NOT counted here.
        "entailment_blocked": 0,
        # Kitni jagah strong label sirf isliye gira ki uska poora support ek
        # bina-refereed kitab/recording ka kathan tha. Ginti alag rakhi gayi
        # hai taaki audit mein A-E ki fail ke saath mix na ho.
        "statement_only": 0,
        "details": [],
        "note": "",
    }
    if not body.strip():
        return body, report

    lines = body.splitlines()
    spans = {start: (end, block) for start, end, block in labelled_claim_spans(body)}
    out_lines: List[str] = []
    index = 0
    while index < len(lines):
        span = spans.get(index)
        if span is None:
            out_lines.append(lines[index])
            index += 1
            continue

        end, block = span
        raw = lines[index]
        if not _STRONG_LABEL_RE.search(raw):
            out_lines.extend(lines[index:end])
            index = end
            continue

        report["checked"] += 1
        ae_attempted = bool(check_entailment and _has_full_text_cite(block, pack))
        verdict, why = line_verdict(block, pack, check_entailment=check_entailment)

        # A-E is a separate stage from access-depth gating. Do not report an
        # abstract/snippet downgrade as "A-E checked and failed" when the A-E
        # verifier was never actually reached.
        if ae_attempted:
            report["a_e_checked"] += 1
            if verdict != ESTABLISHED:
                report["a_e_failed"] += 1
                report["entailment_blocked"] += 1

        if verdict == ESTABLISHED:
            out_lines.extend(lines[index:end])
            index = end
            continue

        new_line = _STRONG_LABEL_RE.sub(f"[{verdict}]", raw)
        out_lines.append(new_line)
        out_lines.extend(lines[index + 1:end])
        report["downgraded"] += 1
        if REASON_STATEMENT_ONLY in (why or ""):
            report["statement_only"] += 1
        if verdict == SOURCE_REPORTED:
            report["to_source_reported"] += 1
        else:
            report["to_unverified"] += 1
        if len(report["details"]) < 8:
            new_block = "\n".join([new_line] + lines[index + 1:end])
            snippet = re.sub(r"^[#\s\-\*\d\.]+", "", new_block).strip()
            snippet = " ".join(snippet.split())
            report["details"].append(f"{snippet[:150]} — {why}")
        index = end

    if report["downgraded"]:
        bits = []
        if report["to_source_reported"]:
            bits.append(f"{report['to_source_reported']} claim SOURCE-REPORTED")
        if report["to_unverified"]:
            bits.append(f"{report['to_unverified']} claim UNVERIFIED")
        strict_reason = (
            "full text hone ke baad bhi same cited source par claim-level A-E support "
            "nahi mila"
            if report["a_e_failed"]
            else "source access depth strong label ke liye enough nahi thi"
        )
        if report["statement_only"]:
            strict_reason += (
                f"; inme {report['statement_only']} jagah poora support ek "
                "bina-refereed kitab/recording ka kathan tha (kathan ≠ proof)"
            )
        report["note"] = (
            f"{report['downgraded']}/{report['checked']} strong dave neeche kiye gaye "
            f"(" + ", ".join(bits) + f") — {strict_reason}."
        )
    return "\n".join(out_lines), report


def merge_reports(strict: Optional[Dict], depth: Optional[Dict]) -> Dict:
    """Merge the two sequential label gates without losing A-E accounting.

    ``enforce_strict_labels`` runs first. A line it turns into UNVERIFIED no
    longer contains a strong label when ``downgrade`` runs, so simply returning
    the second report under-counts real work. Claude's cross-domain benchmark
    caught that audit bug. This integration keeps that fix while preserving the
    stricter A-E counters introduced on this branch.

    The merge is deliberately conservative: strict downgrades are added once;
    checked is the maximum (same original answer, sequential passes), details are
    deduplicated, and A-E counters remain those of the depth/A-E pass rather than
    being invented from the older strict entailment proxy.
    """
    strict = dict(strict or {})
    depth = dict(depth or {})
    out: Dict = {
        "checked": int(depth.get("checked") or 0),
        "downgraded": int(depth.get("downgraded") or 0),
        "to_source_reported": int(depth.get("to_source_reported") or 0),
        "to_unverified": int(depth.get("to_unverified") or 0),
        "a_e_checked": int(depth.get("a_e_checked") or 0),
        "a_e_failed": int(depth.get("a_e_failed") or 0),
        "entailment_blocked": int(depth.get("entailment_blocked") or 0),
        "statement_only": int(depth.get("statement_only") or 0)
        + int(strict.get("statement_only") or 0),
        "strict_unverified": 0,
        "details": list(depth.get("details") or []),
        "note": str(depth.get("note") or "").strip(),
    }

    strict_checked = int(strict.get("checked") or 0)
    strict_unverified = int(strict.get("to_unverified") or 0)
    out["checked"] = max(out["checked"], strict_checked)
    out["downgraded"] += strict_unverified
    out["to_unverified"] += strict_unverified
    out["strict_unverified"] = strict_unverified

    seen = set(out["details"])
    for line in strict.get("details") or []:
        detail = f"{line} — poora text mila par strict support check fail hua"
        if detail in seen:
            continue
        if len(out["details"]) >= 8:
            break
        out["details"].append(detail)
        seen.add(detail)

    notes: List[str] = []
    for value in (strict.get("note"), depth.get("note")):
        clean = str(value or "").strip()
        if clean and clean not in notes:
            notes.append(clean)
    out["note"] = " ".join(notes)
    return out


def human_note(report: Optional[Dict]) -> str:
    """Audit section ke liye normal bhasha, raw PASS/FAIL log nahi."""
    r = report or {}
    checked = int(r.get("checked") or 0)
    if not checked:
        return (
            "Answer mein 'established fact' type ka koi strong dava nahi tha, "
            "isliye yahan kuch downgrade karne ki zaroorat nahi padi."
        )
    down = int(r.get("downgraded") or 0)
    if not down:
        if int(r.get("a_e_checked") or 0):
            return (
                f"{checked} strong dave check kiye gaye; required full-text access ke "
                "saath claim-level citation, relevance, support, depth aur source-quality "
                "gate bhi pass hua, isliye ESTABLISHED label reh saka."
            )
        return (
            f"{checked} strong dave depth-level check mein theek the. Claim-level A-E "
            "strict mode is helper call mein apply nahi hua tha."
        )
    extra = ""
    if int(r.get("statement_only") or 0):
        extra = (
            f" Inme {int(r['statement_only'])} dawa aisa tha jiska poora support ek "
            "bina-refereed kitab ya recording thi — poori kitab padh lene se bhi wo "
            "us kitab ka KATHAN rehta hai, sabit hui baat nahi; dawa hataya nahi "
            "gaya, sirf SOURCE-REPORTED kaha gaya."
        )
    return (
        f"{down} jagah ESTABLISHED strong label neeche karna pada. Jahan sirf "
        "abstract/snippet support hai wahan SOURCE-REPORTED hota hai; aur jahan "
        "strong claim ko same cited source par A-E support prove nahi hua wahan "
        "UNVERIFIED rakha jaata hai. Sirf full text khulna enough nahi hai." + extra
    )


LABEL_RULE_PROMPT = """# LABEL RULE (strict evidence honesty)
- `[ESTABLISHED]` / `[FACT]` / `[STRONG EVIDENCE]` sirf tab likho jab source
  block mein required `full_text` access ho AUR claim usi cited evidence se
  citation + relevance + support + depth + quality checks pass kar sake.
- Full text khul jaana apne aap claim ko verify nahi karta.
- Ek KITAB ya RECORDING (transcript) poori padh lene se bhi uska dawa
  `[ESTABLISHED]` nahi banta — wo us kitab ka KATHAN hai. Aisi line par
  `[SOURCE-REPORTED]` likho. Chhoot sirf tab jab usi source par
  peer-review, DOI, ya asli study design ka signal ho.
- Agar sirf abstract/snippet/metadata mila hai, `[SOURCE-REPORTED]` likho —
  matlab source ye report karta hai, confirmed fact nahi.
- Kisi source se support na ho to `[NO-SOURCE]` + `[INFERENCE]`, `[HYPOTHESIS]`
  ya `[UNVERIFIED]` use karo.
- Labels kabhi confidence decoration nahi hain; evidence state ka sach hain.
"""
