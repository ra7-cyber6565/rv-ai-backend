"""Domain FOCUS guard — "ek shabd se poora sawaal kisi field ka nahi ban jaata".

Naapa hua defect (2026-08-24, intel ke do mega-question par):

  Q1 (349 token, consciousness/Hermeticism/Jung/attention/CIA/game theory):
      `domain.detect` → `engineering` (strict), sirf ek shabd "vibration" ki
      wajah se — aur wo shabd sawaal me *spiritual claim* ke context me tha
      ("'frequency/vibration' jaise claims ko physics se alag karke test karo").
      Nateeja: search intent "vibration based condition monitoring bearing", aur
      gearbox ka paper sabse ooncha relevance (0.473) jabki Jung/attention
      residue/CIA/conspiracy-psychology ke sahi papers 0.000.

  Q2 (1617 token, "Grand Unified" sawaal, 16 section):
      `economics` (strict) — sirf "market" + "economic" par. `strict` matlab
      anchor-less source HARD REJECT, isliye 15 me se 13 bilkul sahi sources
      ka score 0.000 aur `rank()` sirf 2 bachaata.

`domain_detection_guard` isi bimari ka ek khaas roop (superconductivity ke 4
weak trigger) sambhalta hai. Ye parat usi soch ko GENERAL banati hai, bina
kisi naye keyword ki list ke — faisla teen naape ja sakne wale paimane par
hota hai:

  1. SIGNALS  — kitne ALAG-ALAG pakke nishaan mile: distinct trigger +
                distinct *exclusive* anchor (shared anchor jaise "model",
                "energy", "capacity" nahi ginte, kyunki wo profile khud "ye
                doosre field bhi bolte hain" keh kar mark karta hai).
  2. RIVALS   — kitne DOOSRE field ke trigger bhi usi sawaal me mile. Do-teen
                rival ka matlab hai sawaal multi-domain hai, ek field ka nahi.
  3. LENGTH   — sawaal kitna lamba hai. 400-1600 token ke sawaal me kisi ek
                field ka ek-do shabd aana ittefaq hai, poora sawaal us field
                ka hone ka saboot nahi.

Demote karne ka matlab **GENERIC** hai (`strict=False`): koi hard reject nahi,
routing band nahi — sirf "is sawaal ka koi ek field nahi hai" maan liya jaata
hai. Isse ulti galti (kisi asli field ke sawaal ko generic bana dena) ki keemat
sirf itni hai ki field ke ready-made branch queries nahi chalti; jabki galat
strict field ki keemat naapi ja chuki hai — 13/15 sahi source ka 0.000.

Chhote, focused sawaal (jo har purane benchmark me hain) is parat se bilkul
achhoote hain: unme ya to signals kaafi hote hain, ya sawaal `_INCIDENTAL_MIN`
se chhota hota hai.
"""
from __future__ import annotations

from typing import Dict, List, Set

from . import domain as _domain

# Ek se zyada nishaan na hon to sawaal itna bada hona chahiye ki "ek shabd
# ittefaq se aa gaya" kehna waajib ho. 40 token se chhote sawaal me ek anchor
# hi poora topic ho sakta hai ("LK-99 ka Tc kitna hai?").
_INCIDENTAL_MIN_TOKENS = 40
# Multi-domain essay-sawaal ki chhat. Ise itna ooncha rakha gaya hai ki normal
# research sawaal (jo 30-90 token ke hote hain) is raaste par aa hi na sake.
_LONG_QUESTION_TOKENS = 120
# Lambe sawaal me itne se kam alag nishaan = field ka dawa kamzor hai.
_WEAK_SIGNALS_IN_LONG = 3
# Itne doosre field ke trigger bhi mile = sawaal ek field ka nahi hai.
_MULTI_DOMAIN_RIVALS = 2

_INSTALLED_FLAG = "_focus_guard_installed"
_PREVIOUS = None


def _signals(question: str, profile) -> Dict[str, List[str]]:
    bag: Set[str] = _domain.stems(question or "")
    triggers = _domain.matched(profile.triggers, bag)
    shared = {a.casefold() for a in getattr(profile, "shared_anchors", ())}
    anchors = [a for a in _domain.matched(profile.anchors, bag)
               if a.casefold() not in shared]
    return {"triggers": triggers, "exclusive_anchors": anchors}


def _distinct(signals: Dict[str, List[str]]) -> int:
    seen = {s.casefold() for s in signals["triggers"]}
    seen |= {s.casefold() for s in signals["exclusive_anchors"]}
    return len(seen)


def _rival_domains(question: str, chosen) -> int:
    bag: Set[str] = _domain.stems(question or "")
    count = 0
    for prof in _domain.PROFILES:
        if prof.key == chosen.key:
            continue
        if prof.trigger_hits(bag):
            count += 1
    return count


def focus_verdict(question: str, plan) -> Dict:
    """Kya is plan ka field-dawa naape gaye paimanon par tikta hai?"""
    text = question or ""
    token_count = len(_domain.tokens(text))
    if not plan.is_known:
        return {"demote": False, "reason": "koi field profile match hi nahi hua",
                "signals": 0, "rivals": 0, "tokens": token_count}

    signals = _signals(text, plan.profile)
    distinct = _distinct(signals)
    rivals = _rival_domains(text, plan.profile)
    detail = {"signals": distinct, "rivals": rivals, "tokens": token_count,
              "matched_triggers": signals["triggers"],
              "matched_exclusive_anchors": signals["exclusive_anchors"],
              "domain": plan.key}

    if distinct <= 1 and token_count >= _INCIDENTAL_MIN_TOKENS:
        only = ", ".join(signals["triggers"] or signals["exclusive_anchors"]) or "—"
        detail.update(demote=True, reason=(
            f"{token_count}-token sawaal me '{plan.key}' ka sirf ek nishaan "
            f"({only}) mila — ek shabd se poora sawaal is field ka nahi ban jaata"))
        return detail

    if (token_count >= _LONG_QUESTION_TOKENS
            and distinct <= _WEAK_SIGNALS_IN_LONG
            and rivals >= _MULTI_DOMAIN_RIVALS):
        detail.update(demote=True, reason=(
            f"{token_count}-token sawaal, '{plan.key}' ke sirf {distinct} "
            f"nishaan aur {rivals} doosre field ke trigger bhi mile — ye "
            f"multi-domain sawaal hai, ek field ka nahi"))
        return detail

    detail.update(demote=False, reason=(
        f"'{plan.key}' ka dawa tikta hai ({distinct} nishaan, {rivals} rival, "
        f"{token_count} token)"))
    return detail


def guarded_detect(question: str):
    plan = _PREVIOUS(question) if _PREVIOUS else _domain.detect(question)
    verdict = focus_verdict(question, plan)
    if not verdict.get("demote"):
        return plan
    rivals = (plan.profile,) + tuple(plan.rivals[:2])
    return _domain.DomainPlan(
        question=question,
        profile=_domain.GENERIC,
        confidence=0,
        rivals=rivals,
        focus_keys=(),
    )


def install() -> None:
    global _PREVIOUS
    if getattr(_domain, _INSTALLED_FLAG, False):
        return
    _PREVIOUS = _domain.detect
    _domain.detect = guarded_detect
    try:
        _domain.anchor_terms.cache_clear()
    except Exception:
        pass
    setattr(_domain, _INSTALLED_FLAG, True)


install()
