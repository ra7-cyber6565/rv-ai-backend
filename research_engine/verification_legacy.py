"""
VerificationEngine — Spec Section 11 (Verification & Validation)

Spec ka rule: "untested result ko proven result mat batana."

Isliye ye engine sirf wahi verify karta hai jo *computationally* verify ho sakta
hai, aur baaki sab ko honestly "REQUIRES PHYSICAL TEST" ya "UNVERIFIABLE" mark
karta hai. Koi Gemini call nahi — sab local math/logic hai (free + deterministic).

Verification levels:
    COMPUTATIONALLY VERIFIED  — math/logic check pass hui
    SOURCE GROUNDED           — claims sources se cite hui aur IDs valid hain
    LOGICALLY CONSISTENT      — koi internal contradiction nahi mili
    REQUIRES PHYSICAL TEST    — lab/clinical test ke bina prove nahi ho sakta
    UNVERIFIABLE HERE         — is system ke dayre se bahar
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .models import EvidencePack, SourceType

# 12 + 8 = 20   |   45 × 3 = 135
_ARITH_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*([+\-*x×/])\s*(\d[\d,]*(?:\.\d+)?)\s*=\s*(\d[\d,]*(?:\.\d+)?)"
)
# 30% of 200 = 60   |   30% ka 200 = 60
_PCT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*%\s*(?:of|ka|se)\s*(\d[\d,]*(?:\.\d+)?)\s*(?:=|is|hai|hota hai)\s*"
    r"(\d[\d,]*(?:\.\d+)?)",
    re.IGNORECASE,
)
_PROOF_WORDS = re.compile(
    r"\b(proven|proved|clinically proven|guaranteed|cure|100% effective|"
    r"definitely works|sabit ho gaya|pakka ilaj)\b", re.IGNORECASE)

_PHYSICAL_HINTS = ("synthesis", "molecule", "compound", "drug", "dose", "in vivo",
                   "in vitro", "clinical trial", "reaction", "material", "battery",
                   "device", "prototype", "cell line", "patient")

# ── Spec Section 11: statistics-presence audit ────────────────────────────────
# Ye patterns SIRF ye detect karte hain ki kisi source ke AVAILABLE text
# (title + snippet/abstract) mein statistical reporting DIKHTI hai ya nahi.
# Ye correctness check NAHI hai (numbers verify nahi hote) aur koi statistic
# INVENT nahi karta. Snippet mein na dikhna = "yahan nahi dikha", NA ki
# "paper mein nahi hai" — kyunki poora text shayad padha hi na gaya ho.
_STAT_PATTERNS = {
    "p_value": re.compile(
        r"\bp[-\s]?values?\b|\bp\s*[<>=≤≥]\s*0?\.\d+", re.IGNORECASE),
    "confidence_interval": re.compile(
        r"\bconfidence intervals?\b|\b\d{2}\s*%\s*c\.?\s*i\.?\b|\bci\s*[:=]\s*[\[\d.\-]",
        re.IGNORECASE),
    "sample_size": re.compile(
        r"\bn\s*=\s*\d+|\bsample size\b|\b\d[\d,]*\s+"
        r"(?:participants|subjects|respondents|patients|observations)\b",
        re.IGNORECASE),
    "effect_size": re.compile(
        r"\bodds ratios?\b|\bhazard ratios?\b|\brelative risk\b|\beffect sizes?\b|"
        r"\bcohen'?s\s*d\b|\b(?:or|hr|rr)\s*=\s*\d", re.IGNORECASE),
}

# Simulation / backtest / forecast jaisi baat — ye engine inhe KHUD nahi chalata,
# isliye aise natije ko "run karke verify kiya" nahi maana ja sakta.
_SIMULATION_HINTS = re.compile(
    r"\bsimulat(?:e|ed|es|ion|ions|ing)\b|\bmonte[-\s]?carlo\b|"
    r"\bback[-\s]?test(?:s|ed|ing)?\b|\bforecast(?:s|ed|ing)?\b|"
    r"\bprojection(?:s)?\b|\bextrapolat(?:e|ed|es|ion|ing)\b", re.IGNORECASE)


def _num(text: str) -> float:
    return float(text.replace(",", ""))


@dataclass
class Check:
    name: str
    passed: Optional[bool]      # None = check nahi ho saka
    detail: str = ""

    def to_dict(self) -> Dict:
        return {"check": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class VerificationReport:
    status: str = "UNVERIFIABLE HERE"
    checks: List[Check] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    required_tests: List[str] = field(default_factory=list)
    # Spec Section 11 — dataset/statistics awareness
    statistics: Dict = field(default_factory=dict)          # kaunse source mein stats DIKHE
    data_for_verification: List[str] = field(default_factory=list)  # raw datasets user khud check kare
    limits: List[str] = field(default_factory=list)         # simulation/backtest jaisi honest seemayein

    def to_dict(self) -> Dict:
        return {
            "status": self.status,
            "checks": [c.to_dict() for c in self.checks],
            "warnings": self.warnings,
            "required_tests": self.required_tests,
            "statistics": self.statistics,
            "data_for_verification": self.data_for_verification,
            "limits": self.limits,
            "note": "Verification sirf computational/logical level pe hui hai. "
                    "Physical, clinical ya lab verification ye system nahi kar sakta. "
                    "Statistics sirf presence ke liye dekhe gaye — verify ya invent "
                    "nahi kiye gaye.",
        }


class VerificationEngine:
    # ── lazy imports (optional dependencies) ─────────────────────────────────
    def _sympy(self):
        """Sympy for algebraic expression validation."""
        try:
            import sympy
            return sympy
        except ImportError:
            return None

    def _scipy_stats(self):
        """Scipy.stats for statistical validation."""
        try:
            from scipy import stats
            return stats
        except ImportError:
            return None

    # ── 1. arithmetic ────────────────────────────────────────────────────────
    def check_math(self, text: str) -> List[Check]:
        checks: List[Check] = []

        for a, op, b, claimed in _ARITH_RE.findall(text or ""):
            try:
                x, y, expected_claim = _num(a), _num(b), _num(claimed)
            except ValueError:
                continue
            if op in ("*", "x", "×"):
                actual = x * y
            elif op == "+":
                actual = x + y
            elif op == "-":
                actual = x - y
            else:
                if y == 0:
                    checks.append(Check(f"{a} / {b}", False, "division by zero"))
                    continue
                actual = x / y
            ok = abs(actual - expected_claim) <= max(0.01, abs(actual) * 0.001)
            checks.append(Check(
                name=f"{a} {op} {b} = {claimed}",
                passed=ok,
                detail="sahi" if ok else f"asli jawab {actual:g} hona chahiye",
            ))

        for pct, base, claimed in _PCT_RE.findall(text or ""):
            try:
                actual = _num(pct) / 100.0 * _num(base)
                expected_claim = _num(claimed)
            except ValueError:
                continue
            ok = abs(actual - expected_claim) <= max(0.01, abs(actual) * 0.01)
            checks.append(Check(
                name=f"{pct}% of {base} = {claimed}",
                passed=ok,
                detail="sahi" if ok else f"asli jawab {actual:g} hona chahiye",
            ))

        return checks

    # ── 1b. algebraic expressions (advanced — uses sympy) ────────────────────
    def check_algebra(self, text: str) -> List[Check]:
        """
        Extract and verify algebraic equations using sympy.
        Example: "2x + 5 = 15, therefore x = 5"
        """
        checks: List[Check] = []
        sympy = self._sympy()
        if not sympy:
            return checks  # Silently skip if sympy not installed

        # Pattern: "equation, therefore x = value" or "solving ... gives x = value"
        equation_pattern = re.compile(
            r"([a-z]\s*[+\-*/]\s*\d+(?:\s*[+\-*/]\s*\d+)?)\s*=\s*(\d+).*?"
            r"(?:therefore|thus|so|gives|yields)\s*([a-z])\s*=\s*(\d+)",
            re.IGNORECASE
        )

        try:
            for match in equation_pattern.finditer(text or ""):
                expr_str, result_str, var_name, solution_str = match.groups()
                var = sympy.Symbol(var_name)
                try:
                    # Parse equation
                    lhs = sympy.sympify(expr_str.replace(var_name, str(var)))
                    rhs = sympy.sympify(result_str)
                    equation = sympy.Eq(lhs, rhs)

                    # Solve
                    solutions = sympy.solve(equation, var)
                    claimed_solution = float(solution_str)

                    if solutions:
                        actual = float(solutions[0])
                        ok = abs(actual - claimed_solution) < 0.01
                        checks.append(Check(
                            name=f"Solve {expr_str} = {result_str} for {var_name}",
                            passed=ok,
                            detail=f"sahi" if ok else f"{var_name} = {actual:g} hona chahiye"
                        ))
                except Exception:
                    continue  # Parse error — skip silently
        except Exception:
            pass  # Sympy unavailable or other error

        return checks

    # ── 1c. statistical claim validation (advanced — uses scipy) ─────────────
    def check_statistical_claims(self, text: str) -> List[Check]:
        """
        Validate basic statistical claims like:
        - "mean of [data] is X"
        - "standard deviation is Y"
        - "p-value < 0.05 indicates significance"
        """
        checks: List[Check] = []
        stats = self._scipy_stats()
        if not stats:
            return checks

        # Pattern: "data: [1,2,3,4,5], mean = X"
        data_mean_pattern = re.compile(
            r"(?:data|values|sample)[:=\s]+\[([0-9,.\s]+)\].*?"
            r"(?:mean|average)[:=\s]+(\d+(?:\.\d+)?)",
            re.IGNORECASE
        )

        try:
            import numpy as np
            for match in data_mean_pattern.finditer(text or ""):
                data_str, claimed_mean_str = match.groups()
                try:
                    data = [float(x.strip()) for x in data_str.split(',') if x.strip()]
                    if len(data) < 2:
                        continue
                    actual_mean = np.mean(data)
                    claimed_mean = float(claimed_mean_str)
                    ok = abs(actual_mean - claimed_mean) < 0.01
                    checks.append(Check(
                        name=f"Mean of {len(data)} values",
                        passed=ok,
                        detail=f"sahi ({actual_mean:.2f})" if ok else f"asli mean {actual_mean:.2f} hai"
                    ))
                except (ValueError, TypeError):
                    continue
        except ImportError:
            pass  # numpy not available

        # Pattern: "p-value = 0.03 is significant at α = 0.05"
        pvalue_pattern = re.compile(
            r"p[-\s]?value\s*=\s*(0\.\d+).*?"
            r"(?:significant|not significant).*?"
            r"(?:α|alpha)\s*=\s*(0\.\d+)",
            re.IGNORECASE
        )

        for match in pvalue_pattern.finditer(text or ""):
            p_str, alpha_str = match.groups()
            try:
                p_value = float(p_str)
                alpha = float(alpha_str)
                is_significant = p_value < alpha

                # Check if text claims correct significance
                context = match.group(0).lower()
                claims_significant = "significant" in context and "not significant" not in context

                ok = is_significant == claims_significant
                checks.append(Check(
                    name=f"p = {p_value} vs α = {alpha}",
                    passed=ok,
                    detail=("sahi — " + ("significant" if is_significant else "not significant"))
                           if ok else f"galat — actually {'significant' if is_significant else 'not significant'}"
                ))
            except ValueError:
                continue

        return checks

    # ── 2. overclaim detection (Spec Section 11) ──────────────────────────────
    def check_overclaims(self, text: str, has_hypothesis: bool) -> List[str]:
        warnings: List[str] = []
        hits = {m.group(0).lower() for m in _PROOF_WORDS.finditer(text or "")}
        if hits:
            warnings.append(
                "Answer mein strong proof-language mili (" + ", ".join(sorted(hits)[:4]) +
                ") — jab tak koi source is claim ko support na kare, ye overclaim hai.")
        if has_hypothesis and re.search(r"\bproven\b|\bsabit\b", text or "", re.IGNORECASE):
            warnings.append(
                "Hypothesis ke saath 'proven' shabd use hua — hypothesis untested hoti hai.")
        return warnings

    # ── 3. internal consistency ───────────────────────────────────────────────
    def check_consistency(self, text: str) -> Check:
        """Same metric ke liye ek hi answer mein do bahut alag numbers?"""
        percentages = [float(p) for p in re.findall(r"(\d{1,3}(?:\.\d+)?)\s?%", text or "")
                       if 0 <= float(p) <= 100]
        if len(percentages) < 2:
            return Check("internal numeric consistency", None,
                         "compare karne layak numbers nahi mile")
        spread = max(percentages) - min(percentages)
        if spread >= 60:
            return Check("internal numeric consistency", False,
                         f"answer mein {min(percentages):g}% se {max(percentages):g}% tak "
                         f"ka farq hai — check karo ki ye alag-alag cheezein hain")
        return Check("internal numeric consistency", True,
                     f"numbers ka range theek hai ({min(percentages):g}%–{max(percentages):g}%)")

    # ── 4. experiment design (jab physical test chahiye) ─────────────────────
    def experiment_design(self, statement: str, field_hint: str = "") -> str:
        return (
            f"Is claim ko test karne ke liye kya chahiye — '{statement[:120]}':\n"
            f"  1. Measurable outcome: kya exactly maapa jaayega (unit ke saath)\n"
            f"  2. Control group / baseline: kis se compare hoga\n"
            f"  3. Sample size aur duration: kitne subjects/trials, kitne samay tak\n"
            f"  4. Falsification condition: kaun sa result is claim ko GALAT sabit karega\n"
            f"  5. Required setup: {field_hint or 'lab/field resources'} — "
            f"ye software se nahi ho sakta\n"
            f"  6. Ethics/safety clearance: agar human/animal ya chemical involved hai"
        )

    def needs_physical_test(self, text: str) -> bool:
        low = (text or "").lower()
        return any(h in low for h in _PHYSICAL_HINTS)

    # ── 5. statistics-presence audit (Spec Section 11) ────────────────────────
    def audit_statistics(self, pack: EvidencePack) -> Dict:
        """
        Har source ke AVAILABLE text (title + snippet/abstract) mein dekho ki
        statistical reporting — p-value, confidence interval, sample size,
        effect size — DIKHTI hai ya nahi.

        Ye JAAN-BOOJH KAR sirf presence/absence hai:
            * numbers ki sahi-galat JANCH nahi hoti (wo alag baat hai),
            * koi statistic INVENT nahi hota (jo nahi likha, wo nahi likha),
            * snippet mein na dikhna iska matlab NAHI ki paper mein nahi hai —
              ho sakta hai humne poora text hi na padha ho.
        """
        markers = {k: 0 for k in _STAT_PATTERNS}
        per_source: List[Dict] = []
        sources_with_stats = 0
        for s in pack.sources:
            text = f"{s.title or ''} {s.snippet or ''}"
            found = [k for k, rx in _STAT_PATTERNS.items() if rx.search(text)]
            if found:
                sources_with_stats += 1
                for k in found:
                    markers[k] += 1
                per_source.append({"source_id": s.source_id, "markers": found})

        checked = len(pack.sources)
        if checked == 0:
            note = "Koi source nahi tha, isliye statistics audit nahi hua."
        else:
            note = (f"{sources_with_stats}/{checked} sources ke available text "
                    f"(snippet/abstract) mein statistical reporting dikhi. Baaki mein "
                    f"nahi dikhi — iska matlab ye NAHI ki paper mein statistics nahi "
                    f"hain (poora text na padha gaya ho). Ye numbers verify ya invent "
                    f"nahi kiye gaye, sirf maujoodgi dekhi gayi.")
            if sources_with_stats == 0:
                note += (" Kisi bhi source ke available text mein explicit statistics "
                         "nahi dikhe — quantitative claims ko extra saavdhani se lo.")
        return {
            "sources_checked": checked,
            "sources_with_statistics": sources_with_stats,
            "markers_found": markers,
            "per_source": per_source,
            "note": note,
        }

    # ── 6. datasets available for verification (Spec Section 11) ──────────────
    def data_for_verification(self, pack: EvidencePack) -> List[str]:
        """
        Dataset-type sources ko "verification ke liye available data" ki tarah
        list karo — user in raw datasets se numbers KHUD check kar sakta hai.
        Ye ye DAAVA nahi karta ki system ne verify kar liya; sirf wo raasta
        deta hai jise user ya reviewer aage badha sake.
        """
        lines: List[str] = []
        for s in pack.sources:
            if s.source_type != SourceType.DATASET:
                continue
            tag = f"[{s.source_id}] " if s.source_id else ""
            via = f" (via {s.connector})" if s.connector else ""
            url = f" — {s.url}" if s.url else ""
            lines.append(f"{tag}{s.title or 'dataset'}{via}{url}")
        return lines

    # ── 7. honest limits on simulation / backtesting (Spec Section 11) ────────
    def simulation_limits(self, answer: str) -> List[str]:
        """
        Agar jawab mein simulation/backtest/forecast jaisi baat hai to saaf
        likho ki ye engine wo KHUD nahi chalata — aise natije unvalidated hain.
        """
        limits: List[str] = []
        if _SIMULATION_HINTS.search(answer or ""):
            limits.append(
                "Jawab mein simulation/backtest/forecast jaisi baat hai. Ye engine "
                "koi simulation, backtest ya numerical forecast KHUD nahi chalata — "
                "aise natije ke liye alag computational validation chahiye. Inhe "
                "'run karke verify kiya gaya' mat samjho.")
        return limits

    # ── main ─────────────────────────────────────────────────────────────────
    def verify(self, answer: str, pack: EvidencePack,
               citation_ok: bool = True, ungrounded_count: int = 0,
               hypotheses: Optional[List[Dict]] = None,
               cited_ids: Optional[List[str]] = None) -> VerificationReport:
        report = VerificationReport()
        hypotheses = hypotheses or []

        # 1. All computational checks (basic math, algebra, statistics)
        math_checks = self.check_math(answer)
        algebra_checks = self.check_algebra(answer)
        stat_checks = self.check_statistical_claims(answer)

        report.checks.extend(math_checks)
        report.checks.extend(algebra_checks)
        report.checks.extend(stat_checks)
        report.checks.append(self.check_consistency(answer))

        # Flag computation failures
        all_comp_checks = math_checks + algebra_checks + stat_checks
        if any(c.passed is False for c in all_comp_checks):
            report.warnings.append(
                f"{sum(1 for c in all_comp_checks if c.passed is False)} computational "
                f"check(s) fail hui — answer mein calculation/logic error hai.")
        if any(c.passed is True for c in all_comp_checks):
            report.status = "COMPUTATIONALLY VERIFIED (partial)"

        report.checks.append(Check(
            name="citation validity",
            passed=citation_ok,
            detail="sab cited IDs evidence pack mein maujood hain" if citation_ok
                   else "kuch citations evidence pack se match nahi hue",
        ))
        report.checks.append(Check(
            name="claims grounded in sources",
            passed=ungrounded_count == 0,
            detail="har factual claim pe source hai" if ungrounded_count == 0
                   else f"{ungrounded_count} factual claim bina source ke hain",
        ))

        report.warnings.extend(self.check_overclaims(answer, bool(hypotheses)))

        # Spec Section 11 — dataset/statistics awareness (sab local, deterministic)
        report.statistics = self.audit_statistics(pack)
        report.data_for_verification = self.data_for_verification(pack)
        report.limits.extend(self.simulation_limits(answer))

        # Spec Section 11 — retracted source ka verification flag. Ye cosmetic
        # nahi hai: agar jawab kisi retracted kaam par tika hai to wo claim ab
        # bharosemand nahi. cited_ids diya ho to precise (cite hua ya nahi),
        # warna sirf maujoodgi ka honest warning.
        retracted = pack.retracted_sources()
        if retracted:
            retracted_ids = [s.source_id for s in retracted if s.source_id]
            if cited_ids is None:
                report.warnings.append(
                    f"{len(retracted)} source par retraction/withdrawal signal hai "
                    f"({', '.join(retracted_ids) or 'id nahi'}) — inhe evidence ki "
                    f"tarah use nahi karna chahiye.")
            else:
                cited_retracted = sorted(set(retracted_ids) & set(cited_ids))
                if cited_retracted:
                    report.checks.append(Check(
                        "cited sources retraction-free", False,
                        f"{len(cited_retracted)} CITED source par retraction signal hai "
                        f"({', '.join(cited_retracted)}) — ye claim bharosemand nahi"))
                    report.warnings.append(
                        f"Jawab mein cite kiya gaya {len(cited_retracted)} source "
                        f"retracted/withdrawn hai ({', '.join(cited_retracted)}). "
                        f"Retracted kaam evidence nahi hota — ispe tika claim dobara "
                        f"dekhna chahiye.")
                else:
                    report.checks.append(Check(
                        "cited sources retraction-free", True,
                        f"{len(retracted)} retracted source mila par jawab mein cite "
                        f"nahi hua"))

        for h in hypotheses:
            statement = h.get("statement", "")
            if not statement:
                continue
            if self.needs_physical_test(f"{statement} {h.get('how_to_test', '')}"):
                report.required_tests.append(
                    self.experiment_design(statement, "lab/clinical setup"))

        # ── final status ─────────────────────────────────────────────────────
        math_failed = [c for c in math_checks if c.passed is False]
        consistency = next((c for c in report.checks
                            if c.name == "internal numeric consistency"), None)

        if math_failed:
            report.status = "MATH ERROR FOUND"
        elif report.required_tests:
            report.status = "REQUIRES PHYSICAL TEST"
        elif math_checks and all(c.passed for c in math_checks):
            report.status = "COMPUTATIONALLY VERIFIED"
        elif citation_ok and ungrounded_count == 0 and pack.sources:
            report.status = "SOURCE GROUNDED"
        elif consistency and consistency.passed:
            report.status = "LOGICALLY CONSISTENT"
        else:
            report.status = "UNVERIFIABLE HERE"

        return report
