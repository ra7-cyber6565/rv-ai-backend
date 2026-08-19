from typing import Dict

MEDICAL_KEYWORDS = [
    "dawa", "ilaj", "treatment", "dose", "medicine", "diagnosis",
    "bimari ka ilaj", "dawai", "cancer treatment", "surgery", "symptom",
    "doctor se puchho", "medical advice", "prescription", "drug dosage"
]

DANGEROUS_KEYWORDS = [
    "bomb", "weapon", "explosive", "poison banane", "hack karne",
    "virus banane", "malware", "ransom", "attack karna", "nuke",
    "chemical weapon", "bioweapon", "smuggling", "terrorist"
]

FINANCIAL_KEYWORDS = [
    "invest karo", "stock tip", "guaranteed return", "share kharido",
    "financial advice", "trading advice", "loan lelo"
]


def check_safety(question: str) -> Dict:
    """
    Blueprint Section — Safety Layer.
    Blocking nahi karta — sirf FLAG karta hai taaki final answer mein
    appropriate disclaimer/caution add ho sake.
    """
    q_lower = question.lower()
    flags = []

    if any(kw in q_lower for kw in MEDICAL_KEYWORDS):
        flags.append({
            "category": "MEDICAL",
            "note": "Ye medical topic hai. Answer mein clearly likha jayega: 'Ye research-based information hai, doctor se consult karo.'"
        })

    if any(kw in q_lower for kw in DANGEROUS_KEYWORDS):
        flags.append({
            "category": "HIGH_RISK",
            "note": "Ye sawal high-risk category mein aata hai. Operational/harmful instructions restrict ki jayengi."
        })

    if any(kw in q_lower for kw in FINANCIAL_KEYWORDS):
        flags.append({
            "category": "FINANCIAL",
            "note": "Ye financial topic hai. Answer mein clearly likha jayega: 'Ye research hai, financial advisor se consult karo.'"
        })

    return {
        "flags": flags,
        "safe_to_proceed": True,
        "flag_count": len(flags)
    }
