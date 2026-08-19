"""
red_team_mode.py — Spec Section 9 (Red Team Attack)

Red team mode ko orchestrate karta hai. Existing critic.py use karta hai,
bas framework provide karta hai ki kab aur kaise chalaye.

Ye module decide karta hai:
- Red team chalana chahiye ya nahi?
- Kitne Gemini calls available hain red team ke liye?
- Red team output ko final answer mein kaisa daalna hai?
"""
from __future__ import annotations

from typing import Dict, List, Optional
from .models import EvidencePack


class RedTeamOrchestrator:
    """
    Red team mode coordination (Spec Section 9, PASS 6).

    Red team ko call karne se pehle decide karte ho:
    1. Should we even run it? (budget + depth mode check)
    2. Kaunsa analysis red team karne chahiye?
    3. Output ko kaisa final answer mein integrate karein?
    """

    def should_run_red_team(self, depth_mode: str = "DEEP",
                           gemini_calls_available: int = 0,
                           gemini_calls_used: int = 0,
                           evidence_level: str = "") -> bool:
        """
        Red team tab chalega jab:
        1. Depth mode mein use_red_team=True ho
        2. Gemini calls budget bache hon
        3. Evidence contradictory ya weak ho (max payoff ke liye)
        """
        calls_remaining = gemini_calls_available - gemini_calls_used

        # QUICK: no red team
        if depth_mode == "QUICK":
            return False

        # DEEP/MAXIMUM: red team tab chalega jab calls bache hon
        if calls_remaining <= 0:
            return False

        # Priority: contradictory evidence ko red team se attack karo
        if evidence_level in ("MIXED", "WEAK"):
            return True

        # Otherwise: jab ek call bache ho to red team ko dedo
        return calls_remaining >= 1

    def red_team_prompt_suffix(self) -> str:
        """
        Red team prompt jo synthesizer ke saath attach hota hai.
        """
        return """
---
## RED TEAM ATTACK (Spec Section 9, PASS 6)

Upar jo analysis likha hai, ab uss par strongest critic ban:
- Sabse kamzor assumption kaunse hain?
- Kaun sa evidence sirf correlation dikha raha hai, causation suggest kar raha hai?
- Kaun sa single contradictory data point poore conclusion ko overturn kar sakta hai?
- Kaun sa alternative explanation same evidence ko explain kar sakta hai?

Output format:
## Red Team Critique
- (weaknesses)

## Counter-Evidence We Could Find
- (kya data point evidence ko challenge kar sakta hai)

## Strongest Alternative Explanation
- (dusra explanation jo same sources fit kare)
"""

    def integrate_red_team_into_final(self, final_answer: Dict,
                                     red_team_response: Optional[str] = None) -> Dict:
        """
        Red team output ko final answer structure mein merge karo.

        Final answer ke existing sections mein add karega:
        - "counter_evidence" section add/expand hoga
        - "weaknesses_acknowledged" section add hoga
        """
        if not red_team_response:
            return final_answer

        # Parse red team response (simple pattern matching)
        weaknesses = _extract_section(red_team_response, "weakness")
        counter_evidence = _extract_section(red_team_response, "counter-evidence|alternative")

        # Add to final answer
        if weaknesses:
            final_answer["weaknesses_acknowledged"] = weaknesses

        if counter_evidence:
            final_answer["counter_evidence_found"] = counter_evidence

        return final_answer


def _extract_section(text: str, pattern: str) -> List[str]:
    """
    Red team response se bullet points extract karo.
    """
    if not text:
        return []

    import re

    # Find section heading
    heading_re = re.compile(rf"^[#]*\s*({pattern}[^#]*?)(?=^[#]|$)",
                           re.IGNORECASE | re.MULTILINE | re.DOTALL)

    match = heading_re.search(text)
    if not match:
        return []

    section = match.group(1)

    # Extract bullets
    bullets = re.findall(r"^\s*[-*•]\s+(.{8,200})", section, re.MULTILINE)
    return bullets[:8]  # Max 8 items
