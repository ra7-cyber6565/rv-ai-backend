from typing import Dict, List

MEDICAL_KEYWORDS = [
    "dawa", "ilaj", "treatment", "dose", "medicine", "diagnosis",
    "bimari ka ilaj", "dawai", "cancer treatment", "surgery", "symptom",
    "doctor se puchho", "medical advice", "prescription", "drug dosage"
]

DANGEROUS_KEYWORDS = [
    "bomb", "weapon", "explosive", "poison banane", "hack karne",
    "virus banane", "malware", "ransom", "attack karna", "nuke",
    "chemical weapon", "bioweapon", "smuggling", "terrorist",
    "fraud karna", "scam karna", "chori karna", "drugs banana"
]

# Generic legal-risk intent.  This is deliberately a warning trigger, not a
# truth classifier: the presence of one of these words does NOT prove that the
# described act is illegal in the user's jurisdiction.
LEGAL_RISK_KEYWORDS = [
    "illegal", "inlegal", "unlawful", "crime", "criminal", "banned by law",
    "kanoon ke khilaf", "kanun ke khilaf", "gair kanooni", "gairkanuni",
    "अवैध", "गैरकानूनी"
]

FINANCIAL_KEYWORDS = [
    "invest karo", "stock tip", "guaranteed return", "share kharido",
    "financial advice", "trading advice", "loan lelo"
]

_WARN_AND_EXPLAIN = "WARN_AND_EXPLAIN"


def _high_risk_flag() -> Dict:
    return {
        "category": "HIGH_RISK",
        "response_mode": _WARN_AND_EXPLAIN,
        "show_warning": True,
        "allow_contextual_explanation": True,
        "actionable_wrongdoing_allowed": False,
        "note": (
            "High-risk/illegal topic ko sirf topic hone ki wajah se hide nahi kiya "
            "jayega. App context, history, kanooni/ethical risk, consequences aur "
            "defensive information samjha sakta hai; lekin operational harmful "
            "instructions restrict rahengi."
        ),
    }


def _legal_risk_flag() -> Dict:
    return {
        "category": "LEGAL_RISK",
        "response_mode": _WARN_AND_EXPLAIN,
        "show_warning": True,
        "allow_contextual_explanation": True,
        "actionable_wrongdoing_allowed": False,
        "note": (
            "Is sawaal mein legal-risk language hai. App topic ko explain karega, "
            "par jurisdiction-specific legality ko bina reliable source ke assume "
            "nahi karega aur wrongdoing ko execute/evade karne ke steps nahi dega."
        ),
    }


def _has_category(flags: List[Dict], category: str) -> bool:
    return any(str(f.get("category") or "").upper() == category for f in flags)


def check_safety(question: str) -> Dict:
    """
    Safety layer: research ko blanket-block nahi karta.

    Important distinction:
    - illegal/high-risk SUBJECT ko discuss/explain karna allowed path hai;
    - harmful/illegal ACT ko execute, optimize, evade detection, procure inputs,
      troubleshoot ya scale karne ki operational guidance allowed path nahi hai.

    Is function ka ``safe_to_proceed=True`` ka matlab sirf itna hai ki app
    bounded research/explanation continue kar sakta hai. Iska matlab unrestricted
    instructions dena nahi hai.
    """
    q_lower = (question or "").lower()
    flags: List[Dict] = []

    if any(kw in q_lower for kw in MEDICAL_KEYWORDS):
        flags.append({
            "category": "MEDICAL",
            "note": "Ye medical topic hai. Answer mein clearly likha jayega: 'Ye research-based information hai, doctor se consult karo.'"
        })

    if any(kw in q_lower for kw in DANGEROUS_KEYWORDS):
        flags.append(_high_risk_flag())

    if any(kw in q_lower for kw in LEGAL_RISK_KEYWORDS):
        flags.append(_legal_risk_flag())

    if any(kw in q_lower for kw in FINANCIAL_KEYWORDS):
        flags.append({
            "category": "FINANCIAL",
            "note": "Ye financial topic hai. Answer mein clearly likha jayega: 'Ye research hai, financial advisor se consult karo.'"
        })

    bounded = _has_category(flags, "HIGH_RISK") or _has_category(flags, "LEGAL_RISK")
    return {
        "flags": flags,
        "safe_to_proceed": True,
        "flag_count": len(flags),
        "response_mode": _WARN_AND_EXPLAIN if bounded else "NORMAL",
        "allow_contextual_explanation": True,
        "actionable_wrongdoing_allowed": False if bounded else None,
    }


def safety_prompt_appendix(safety: Dict) -> str:
    """Deterministic model boundary for illegal/high-risk informational queries."""
    safety = safety or {}
    flags = list(safety.get("flags") or [])
    bounded = _has_category(flags, "HIGH_RISK") or _has_category(flags, "LEGAL_RISK")
    if not bounded:
        return ""
    return """
SAFETY / LEGAL INFORMATION BOUNDARY — MUST FOLLOW:
- Do NOT hide or refuse the whole subject merely because it concerns something illegal, regulated, dangerous, controversial, or criminal.
- You MAY explain: what it is; historical/social context; why it can be illegal or dangerous; legal/ethical consequences; high-level mechanisms; warning signs; prevention; defensive/security analysis; harm reduction; and lawful alternatives.
- Do NOT provide operational instructions that materially enable wrongdoing or serious harm: no step-by-step execution, recipes, exploit chains, exact attack parameters, weapon/drug construction, procurement lists for harmful use, evasion/detection-bypass methods, optimization, scaling, or troubleshooting of an illegal/harmful act.
- If legality depends on jurisdiction or current law, say that and require reliable current legal sources before making a definitive legal claim.
- Keep useful non-operational information instead of deleting the topic. Clearly warn the user that acting on illegal/harmful parts can be unlawful or dangerous.
""".strip()


def prepend_safety_notice(answer: str, safety: Dict) -> str:
    """Put a visible warning on the final answer without hiding useful context."""
    text = str(answer or "")
    appendix = safety_prompt_appendix(safety)
    if not appendix:
        return text
    notice = (
        "> ⚠️ **Safety / legal warning:** Ye topic illegal, regulated ya high-risk ho "
        "sakta hai. Neeche context/research samjhayi ja sakti hai, lekin ise crime, "
        "harm, detection-bypass ya kisi illegal act ko execute/optimize karne ke liye "
        "use na karein. Exact legality jurisdiction aur current law par depend kar sakti hai."
    )
    if text.startswith(notice):
        return text
    return f"{notice}\n\n{text}" if text else notice
