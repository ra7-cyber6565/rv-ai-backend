"""
Claim label honesty — "[ESTABLISHED]" sirf tab jab full text padha gaya ho.

Kyun ye file bani (2026-08-20, live MAXIMUM run ke baad):
Us report mein ek CACC claim par `[ESTABLISHED]` label tha, aur usi report ke
neeche likha tha "0/14 full-text fetch successful". Yaani label ne kaha "ye
established fact hai", par system ne us paper ka ek shabd bhi poora nahi padha
tha — sirf abstract/snippet dekha tha. Ye chhupa hua jhooth hai, aur intel ka
rule saaf hai:

    Snippet/abstract-only evidence  →  SOURCE-REPORTED   (source ye keh raha hai)
    Full text + claim verification →  ESTABLISHED        (humne khud dekha)

Ye module do cheezein deta hai:
  1. `LABEL_RULE_PROMPT` — Gemini ko yahi rule pehle se bata dena (behtar hai ki
     wo galti hi na kare).
  2. `downgrade(text, pack)` — DETERMINISTIC safety net. Model bhool jaaye, to
     yahan har `[ESTABLISHED]` line ke [S#] ka asli `reading_level()` dekha
     jaata hai aur label khud-ba-khud neeche kar diya jaata hai. Ye Gemini par
     bharosa nahi karta — regex + pack ke asli numbers par chalta hai, isliye
     quota khatam hone par bhi kaam karta hai.

Kuch upgrade NAHI hota: agar model ne khud `[SOURCE-REPORTED]` likha hai to use
`[ESTABLISHED]` banane ka koi raasta nahi hai. Honesty ek taraf hi jhukti hai.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .models import EvidencePack

ESTABLISHED = "ESTABLISHED"
SOURCE_REPORTED = "SOURCE-REPORTED"
UNVERIFIED = "UNVERIFIED"

# "[ESTABLISHED]" / "[ESTABLISHED FACT]" / "[FACT]" / "[STRONG EVIDENCE]" —
# ye chaar hi labels "humne verify kiya" ka dava karte hain, isliye inhi par
# gate lagta hai. [EVIDENCE]/[INFERENCE]/[HYPOTHESIS] pehle se hi honest hain.
_STRONG_LABEL_RE = re.compile(
    r"\[\s*(ESTABLISHED(?:\s+FACT)?|FACT|STRONG\s+EVIDENCE)\s*\]",
    re.IGNORECASE)
_SID_RE = re.compile(r"\[\s*S\s*(\d{1,3})[^\]]*\]", re.IGNORECASE)
_NO_SOURCE_RE = re.compile(r"\[\s*NO[\s\-]?SOURCE\s*\]", re.IGNORECASE)

_FULL = "full_text"


def _cited_ids(line: str) -> List[str]:
    """Line ke andar ke [S#] ids — "[S1][S4]" aur "[S1, S4]" dono chalte hain."""
    out: List[str] = []
    for num in _SID_RE.findall(line or ""):
        sid = f"S{int(num)}"
        if sid not in out:
            out.append(sid)
    return out


def line_verdict(line: str, pack: Optional[EvidencePack],
                 check_entailment: bool = False) -> Tuple[str, str]:
    """
    Ek line ke liye faisla: (naya_label, wajah).

    - koi valid [S#] nahi → UNVERIFIED (source ke bina "established" impossible)
    - kam se kam ek cited source ka reading_level() == "full_text" → ESTABLISHED
    - warna → SOURCE-REPORTED

    `check_entailment=True` (§13 / point 7) ek EXTRA sharti gate laga deta hai:
    full text padha gaya ho, par us text mein claim ka support hi na dikhe, to
    label phir bhi ESTABLISHED nahi rehta. Ye OPT-IN hai kyunki entailment ek
    deterministic proxy hai (claim_verification.check_c) — pipeline jaan-boojh
    kar isse on karta hai, aur jahan support check HO HI NA SAKE wahan gate chup
    rehta hai (sirf saaf FAIL par girata hai).
    """
    ids = _cited_ids(line)
    if pack is not None:
        records = [pack.by_id(sid) for sid in ids]
        records = [r for r in records if r is not None]
    else:
        records = []

    if not records:
        if _NO_SOURCE_RE.search(line or ""):
            return UNVERIFIED, "is line par koi source nahi hai ([NO-SOURCE])"
        if ids:
            return UNVERIFIED, ("cite kiye gaye " + ", ".join(ids)
                                + " evidence pack mein nahi mile")
        return UNVERIFIED, "is line par koi [S#] citation nahi hai"

    levels = {}
    for record in records:
        try:
            level = record.reading_level()
        except Exception:                      # noqa: BLE001 — kabhi crash na kare
            level = "metadata"
        levels[record.source_id] = level

    full = [sid for sid, level in levels.items() if level == _FULL]
    if full:
        if check_entailment and _entailment_blocked(line, pack):
            return SOURCE_REPORTED, (
                f"full text to padha gaya ({', '.join(full)}), par us text mein "
                f"is claim ka support nahi dikha")
        return ESTABLISHED, f"full text padha gaya: {', '.join(full)}"
    detail = ", ".join(f"{sid}={level}" for sid, level in levels.items())
    return SOURCE_REPORTED, f"full text nahi padha gaya ({detail})"


def _entailment_blocked(line: str, pack: Optional[EvidencePack]) -> bool:
    """claim_verification ka gate — import lazy, aur fail hone par chup (False)."""
    try:
        from .claim_verification import entailment_blocked
        return bool(entailment_blocked(line, pack))
    except Exception:                          # pragma: no cover - defensive
        return False


def downgrade(text: str, pack: Optional[EvidencePack] = None,
              check_entailment: bool = False) -> Tuple[str, Dict]:
    """
    Answer text mein har "verified" dave ka label asli read-level se match karao.

    Returns `(naya_text, report)`. Report mein:
        checked          — kitni lines par strong label tha
        downgraded       — kitni neeche ki gayi
        to_source_reported / to_unverified — ginti
        entailment_blocked — kitni lines full text ke BAAVJOOD giri (support hi
                             nahi mila) — sirf `check_entailment=True` par
        details          — max 8 chhoti lines (user ko dikhane ke liye)
        note             — ek line ka human-readable summary ("" agar sab theek)
    Text kabhi nahi kaata jaata — sirf label badalta hai, taaki content na khoye.
    """
    body = text or ""
    report: Dict = {"checked": 0, "downgraded": 0, "to_source_reported": 0,
                    "to_unverified": 0, "entailment_blocked": 0,
                    "details": [], "note": ""}
    if not body.strip():
        return body, report

    out_lines: List[str] = []
    for raw in body.splitlines():
        if not _STRONG_LABEL_RE.search(raw):
            out_lines.append(raw)
            continue
        report["checked"] += 1
        verdict, why = line_verdict(raw, pack, check_entailment=check_entailment)
        if verdict == ESTABLISHED:
            out_lines.append(raw)
            continue
        new_line = _STRONG_LABEL_RE.sub(f"[{verdict}]", raw)
        out_lines.append(new_line)
        report["downgraded"] += 1
        if verdict == SOURCE_REPORTED:
            report["to_source_reported"] += 1
        else:
            report["to_unverified"] += 1
        if "support nahi dikha" in why:
            report["entailment_blocked"] += 1
        if len(report["details"]) < 8:
            snippet = re.sub(r"^[#\s\-\*\d\.]+", "", new_line).strip()
            report["details"].append(f"{snippet[:150]} — {why}")

    if report["downgraded"]:
        bits = []
        if report["to_source_reported"]:
            bits.append(f"{report['to_source_reported']} claim SOURCE-REPORTED")
        if report["to_unverified"]:
            bits.append(f"{report['to_unverified']} claim UNVERIFIED")
        report["note"] = (
            f"{report['downgraded']}/{report['checked']} 'established' dave "
            f"neeche kiye gaye (" + ", ".join(bits) + ") — kyunki un sources ka "
            f"poora text nahi padha gaya, sirf abstract/snippet mila.")
        if report["entailment_blocked"]:
            report["note"] += (
                f" Inme {report['entailment_blocked']} jagah poora text to padha "
                f"gaya tha, par us text mein claim ka support nahi mila.")
    return "\n".join(out_lines), report


def merge_reports(strict: Optional[Dict], depth: Optional[Dict]) -> Dict:
    """
    Label gate DO pass ka hai — dono ka hisaab ek jagah.

    Kyun zaroori hai (cross-domain benchmark, 2026-08-21): pehle strict pass
    (`claim_verification.enforce_strict_labels`) chalta hai, jo "poora text
    padha par support nahi mila" wali line ko `[UNVERIFIED]` kar deta hai.
    Uske BAAD depth pass (`downgrade()`) chalta hai — aur use us line par koi
    strong label milta hi nahi, kyunki wo pehle hi gir chuki hai. Nateeja:
    answer mein downgrade saaf dikhta tha, par machine-readable
    `label_report` `checked: 0, downgraded: 0` bolta tha. Yaani engine ne kaam
    kiya lekin apna hisaab kam karke bataya — audit ke liye ye jhooth hai.

    Isliye ab dono pass ka total milta hai. `strict_unverified` alag se rehta
    hai taaki pata rahe ki kaunsa pass ne giraya.
    """
    depth = dict(depth or {})
    strict = dict(strict or {})
    out: Dict = {
        "checked": 0, "downgraded": 0, "to_source_reported": 0,
        "to_unverified": 0, "entailment_blocked": 0, "strict_unverified": 0,
        "details": [], "note": "",
    }
    out.update({k: v for k, v in depth.items() if k in out})
    s_checked = int(strict.get("checked") or 0)
    s_unver = int(strict.get("to_unverified") or 0)
    # Strict pass pehle chala tha, isliye usne jitni lines dekhi wo depth pass
    # ki ginti se kam nahi ho sakti — total wahi jo zyada hai.
    out["checked"] = max(int(out.get("checked") or 0), s_checked)
    out["downgraded"] = int(out.get("downgraded") or 0) + s_unver
    out["to_unverified"] = int(out.get("to_unverified") or 0) + s_unver
    out["strict_unverified"] = s_unver
    details = list(out.get("details") or [])
    for line in (strict.get("details") or []):
        if len(details) >= 8:
            break
        details.append(f"{line} — poora text mila par claim ka support nahi")
    out["details"] = details
    notes = [n for n in (strict.get("note"), depth.get("note")) if n]
    out["note"] = " ".join(notes)
    return out


def human_note(report: Optional[Dict]) -> str:
    """
    Audit section ke liye normal bhasha wali line (raw log nahi).

    intel ka rule: user ko "[FAIL] label gate" nahi dikhna chahiye — use ye
    dikhna chahiye ki iska matlab kya hai.
    """
    r = report or {}
    checked = int(r.get("checked") or 0)
    if not checked:
        return ("Answer mein 'established fact' type ka koi strong dava nahi tha, "
                "isliye yahan kuch downgrade karne ki zaroorat nahi padi.")
    down = int(r.get("downgraded") or 0)
    if not down:
        return (f"{checked} strong dave check kiye gaye aur sabke peeche kam se kam "
                f"ek aisa source tha jiska poora text padha gaya — isliye inhe "
                f"'established' rehne diya gaya.")
    return (f"{down} jagah label neeche karna pada. Matlab simple hai: wahan par "
            f"baat 'source ye keh raha hai' (SOURCE-REPORTED) ke level par hai, "
            f"'humne khud poora paper padh kar confirm kiya' (ESTABLISHED) ke "
            f"level par nahi. Jahan poora text mila, wahan label waisa hi raha.")


# ── prompt block ─────────────────────────────────────────────────────────────
LABEL_RULE_PROMPT = """# LABEL RULE (intel ka rule — todne par label khud neeche kar diya jayega)
- `[ESTABLISHED]` sirf us baat par jiska POORA TEXT padha gaya hai (source list
  mein us source par "read: full_text" likha hoga) aur claim wahan se seedha
  verify hota hai.
- Agar sirf abstract/snippet/metadata mila hai, to label `[SOURCE-REPORTED]`
  likho — matlab "source ye report karta hai", "ye confirmed fact hai" nahi.
- Kisi bhi source se support na ho to `[NO-SOURCE]` + `[INFERENCE]` ya
  `[HYPOTHESIS]`.
- Ye guess ka kaam nahi hai: source block mein har source ka read level diya
  gaya hai, wahi dekho.
"""
