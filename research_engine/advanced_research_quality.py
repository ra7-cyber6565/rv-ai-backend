"""Advanced research-quality hardening for long, multi-domain questions.

This module addresses failures exposed by the Grand Unified Human Agency stress
run without hard-coding that benchmark's answer.  It is deterministic and
model-free.  The rules are intentionally fail-closed:

* a broad mention (for example ``cosmology``) cannot activate an unrelated
  single-domain evidence benchmark such as the dark-matter axis pack;
* long questions are treated as a set of distinct research facets, and evidence
  axes are generated from those facets rather than from one dominant keyword;
* a source must align to at least one *distinctive* facet, not merely share words
  such as ``attention``, ``model``, ``claims`` or ``strong``;
* contradiction detection requires two sources to align to the same facet and
  share a proposition anchor before lexical polarity is allowed to create a
  contradiction;
* structured-answer coverage requires substantive content under a requested
  heading, not merely the heading text;
* app-original hypotheses cannot receive MODERATE confidence from one cited
  source plus an uncalibrated numeric prediction.

The layer never upgrades truth/evidence/confidence.  It can reject irrelevant
material, downgrade confidence, or make answer completeness stricter.
"""
from __future__ import annotations

import re
from typing import Dict, List, Sequence, Tuple

from . import evidence_axes as axes_mod
from . import facets as facets_mod
from .query_builder import is_generic_word

_INSTALLED = False

# A curated domain pack must have a decisive subject anchor.  Broad neighbouring
# words are deliberately excluded.  This prevents a single mention of cosmology
# inside a 16-domain human-agency prompt from turning the entire run into the
# dark-matter benchmark.
_DECISIVE_DOMAIN = {
    "dark_matter": re.compile(
        r"\b(?:dark matter|missing mass|rotation curves?|modified gravity|mond|"
        r"primordial black holes?|\bpbh\b|dark photon|\bwimps?\b|non[- ]baryonic matter)\b",
        re.IGNORECASE,
    ),
    "clinical": re.compile(
        r"\b(?:clinical trial|patients?|treatment|therapy|drug|vaccine|dose|dosage|"
        r"diagnosis|disease|placebo)\b",
        re.IGNORECASE,
    ),
    "climate": re.compile(
        r"\b(?:climate change|global warming|greenhouse gases?|sea level rise|"
        r"carbon dioxide|anthropogenic warming|climate attribution)\b",
        re.IGNORECASE,
    ),
    "superconductivity": re.compile(
        r"\b(?:superconduct(?:or|ing|ivity)?|meissner|zero resistance|critical temperature|lk-99)\b",
        re.IGNORECASE,
    ),
}

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{2,}")
_CITATION_OR_EPISTEMIC_RE = re.compile(
    r"(?:\[S\d+\]|SOURCE[- ]REPORTED|ESTABLISHED|EVIDENCE|INFERENCE|SPECULATION|"
    r"UNKNOWN|UNVERIFIED|INSUFFICIENT|counter[- ]evidence|limitation|mechanism|"
    r"strongest evidence|strongest criticism)",
    re.IGNORECASE,
)
_NUMERIC_PREDICTION_RE = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s?%|\bn\s*=\s*\d+|\b\d{2,}\s+(?:people|workers|"
    r"participants|subjects|patients|years?|months?|days?|hours?))",
    re.IGNORECASE,
)


def _multi_facet(question: str) -> bool:
    try:
        return len(facets_mod.build(question or "")) >= 4
    except Exception:
        return False


def _contains_term(text: str, term: str) -> bool:
    low = (text or "").casefold()
    needle = (term or "").casefold().strip()
    if not needle:
        return False
    if " " in needle or "-" in needle:
        return needle in low
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", low))


def _source_text(source) -> str:
    return " ".join(
        str(x or "") for x in (
            getattr(source, "title", ""),
            getattr(source, "snippet", ""),
            getattr(source, "venue", ""),
            getattr(source, "publisher", ""),
        )
    )


def _facet_alignment(question: str, source) -> Dict:
    """Best distinctive facet alignment for a source.

    Two rare/exact terms are normally required.  One strong specialist term or
    one safe multi-word phrase can stand alone.  Generic/process words never
    satisfy the gate by themselves.
    """
    facet_pack = facets_mod.build(question or "")
    if not facet_pack:
        return {"required": False, "ok": None, "key": "", "label": "",
                "distinctive": [], "strong": [], "phrase": "", "score": 0}
    text = _source_text(source)
    best: Dict = {"required": True, "ok": False, "key": "", "label": "",
                  "distinctive": [], "strong": [], "phrase": "", "score": 0}
    for facet in facet_pack:
        exact = [t for t in facet.terms if _contains_term(text, t)]
        distinctive = [
            t for t in exact
            if facet.df_of(t) <= 2
            and not is_generic_word(t)
            and not facets_mod.is_discourse_word(t)
        ]
        strong = [t for t in exact if t in set(facet.strong or ())]
        phrase = next(
            (p for p in facet.phrases
             if len(p.split()) >= 2 and facets_mod.is_query_safe_phrase(p)
             and _contains_term(text, p)),
            "",
        )
        ok = len(set(distinctive)) >= 2 or bool(strong) or bool(phrase)
        score = len(set(distinctive)) + (3 * len(set(strong))) + (3 if phrase else 0)
        if score > int(best.get("score", 0)):
            best = {
                "required": True,
                "ok": bool(ok),
                "key": facet.key,
                "label": facet.label,
                "distinctive": sorted(set(distinctive)),
                "strong": sorted(set(strong)),
                "phrase": phrase,
                "score": score,
            }
    return best


def _facet_axes(question: str, limit: int) -> List[axes_mod.Axis]:
    facets = list(facets_mod.build(question or ""))
    if not facets:
        return []
    # Replication and counter-evidence are global quality axes and must survive
    # the limit.  Every other slot is assigned to a user-question facet.
    global_axes = [a for a in axes_mod._GENERIC_AXES
                   if a.axis_id in {"replication", "counter_evidence"}]
    room = max(1, int(limit or 18) - len(global_axes))
    out: List[axes_mod.Axis] = []
    for facet in facets[:room]:
        ordered = list(dict.fromkeys(list(facet.strong) + list(facet.terms)))
        terms = tuple(ordered[:10])
        if not terms:
            continue
        out.append(axes_mod.Axis(
            axis_id=f"facet_{facet.key}",
            label=f"question facet — {facet.label[:100]}",
            terms=terms,
            query=facet.query(limit=6),
            mandatory=True,
            why=("long multi-domain question ka ye alag requested research facet hai; "
                 "sirf kisi doosre facet ke sources se ise covered nahi maana ja sakta"),
        ))
    return (out + global_axes)[: max(1, int(limit or 18))]


def _substantive_coverage(original_coverage, structured_mod, question: str,
                          answer: str) -> Dict:
    base = dict(original_coverage(question, answer))
    if not base.get("required"):
        return base
    outline = structured_mod.extract_outline(question)
    body = str(answer or "")
    folded = body.casefold()
    surface_missing: List[str] = []
    substantive_missing: List[str] = []
    details: List[Dict] = []

    positions: List[Tuple[int, Dict]] = []
    for item in outline:
        title = str(item.get("title") or "").strip().casefold()
        label = str(item.get("label") or "").strip().casefold()
        candidates = [p for p in (folded.find(label), folded.find(title)) if p >= 0]
        pos = min(candidates) if candidates else -1
        positions.append((pos, item))

    for pos, item in positions:
        target = str(item.get("label") or item.get("title") or "")
        if pos < 0:
            surface_missing.append(target)
            substantive_missing.append(target)
            details.append({"label": target, "surface": False,
                            "substantive": False, "words": 0,
                            "epistemic_signal": False})
            continue
        later = [p for p, _ in positions if p > pos]
        end = min(later) if later else min(len(body), pos + 5000)
        section = body[pos:end]
        words = _WORD_RE.findall(section)
        epistemic = bool(_CITATION_OR_EPISTEMIC_RE.search(section))
        # A heading plus one sentence is not a delivered research section.  A
        # substantial section must both explain something and expose its
        # evidence/uncertainty status.
        substantive = len(words) >= 28 and epistemic
        if not substantive:
            substantive_missing.append(target)
        details.append({"label": target, "surface": True,
                        "substantive": substantive, "words": len(words),
                        "epistemic_signal": epistemic})

    base["surface_complete"] = not surface_missing
    base["surface_missing"] = surface_missing
    base["substantive_missing"] = substantive_missing
    base["section_checks"] = details
    base["items_covered"] = sum(1 for row in details if row["substantive"])
    base["missing"] = substantive_missing
    base["complete"] = not substantive_missing
    base["note"] = (
        "semantic delivery audit: requested heading + substantive explanation + "
        "evidence/uncertainty signal required; not a truth-verification score"
    )
    return base


def _confidence_cap(original, hypothesis_mod, h, gate=None, contradictions=None,
                    counter_search_performed=None, calculations_done=None):
    rec = original(
        h, gate=gate, contradictions=contradictions,
        counter_search_performed=counter_search_performed,
        calculations_done=calculations_done,
    )
    facts = len(getattr(h, "facts_used", []) or [])
    numeric_blob = " ".join(str(x or "") for x in (
        getattr(h, "statement", ""), getattr(h, "prediction_text", ""),
        getattr(h, "experiment", ""), getattr(h, "how_to_test", "")))
    uncalibrated_numeric = bool(_NUMERIC_PREDICTION_RE.search(numeric_blob)) \
        and calculations_done is not True

    if facts < 2 and "THIN_EVIDENCE" not in rec.reason_codes:
        rec.reason_codes.append("THIN_EVIDENCE")
    if uncalibrated_numeric and "NO_CALCULATION" not in rec.reason_codes:
        rec.reason_codes.append("NO_CALCULATION")

    struct = getattr(h, "experiment_struct", None)
    plan_weak = struct is None or not getattr(struct, "is_usable", False)
    if facts == 0 or uncalibrated_numeric:
        rec.band = hypothesis_mod.CONF_VERY_LOW
    elif facts < 2 or plan_weak:
        if rec.band == hypothesis_mod.CONF_MODERATE:
            rec.band = hypothesis_mod.CONF_LOW

    reasons = [hypothesis_mod.CONF_REASON_CODES.get(c, c)
               for c in rec.reason_codes]
    extra = ""
    if uncalibrated_numeric:
        extra = ("; numeric prediction/sample/effect size mila par uska calibrated "
                 "calculation nahi hua")
    rec.why = (f"Band {rec.band} — " + "; ".join(reasons[:5]) + extra
               + ". Untested app hypothesis par ye proof/probability nahi hai.")
    return rec


def _quality_prompt_appendix(question: str) -> str:
    if not _multi_facet(question):
        return ""
    return """
# ADVANCED MULTI-FACET RESEARCH QUALITY CONTRACT
- Is question ko ek single topic mat samjho. Har requested facet ko alag evidence lane samjho; ek facet ka source doosre facet ko cover nahi karta.
- Keyword analogy mana hai: software `attention`, mathematical `model/strong/empirical`, ya engineering `strategic` ko human attention/model/strategy ka evidence tab tak mat banao jab tak underlying proposition wahi na ho.
- Contradiction tabhi report karo jab dono sources SAME proposition/population/exposure-or-mechanism/outcome par opposite result dete hon. Sirf positive/negative words opposite hona contradiction nahi.
- Jahan user scientific + historical + official/declassified + traditional/spiritual + books/controversial material maangta hai, source-family diversity preserve karo. Zero-count lane ko scientific papers se substitute mat karo; UNKNOWN/MISSING likho.
- Mathematical/optimization model tabhi do jab formula, defined variables, units/dimensions (ya explicitly dimensionless), inputs with provenance, assumptions, uncertainty/sensitivity aur reproducible calculation ho. Inme se kuch missing ho to numeric result mat invent karo; `NOT COMPUTED / INSUFFICIENT CALIBRATION` likho.
- Causal/second-order chain ke har arrow ko separately label karo: evidence-supported / inference / speculative / unknown. Ek weak link poori chain ko established nahi banata.
- APP-ORIGINAL HYPOTHESIS me mechanism ke har unsupported step ko [INFERENCE] ya [NO-SOURCE] mark karo. Arbitrary effect size, sample size, power-law, timescale ya percentage ko evidence/calculation ke bina confidence badhane ke liye use mat karo.
- Heading likh dena coverage nahi hai: har requested section ke neeche substantive answer + evidence/uncertainty status do.
""".strip()


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # 1) Evidence axes: decisive domain activation + facet-wise axes.
    original_axis_set_for = axes_mod.axis_set_for
    original_axes_for = axes_mod.axes_for

    def guarded_axis_set_for(question: str):
        key, axes = original_axis_set_for(question)
        decisive = _DECISIVE_DOMAIN.get(key)
        if decisive is not None and not decisive.search(question or ""):
            return "generic", ()
        return key, axes

    def guarded_axes_for(question: str, limit: int = 18):
        if _multi_facet(question):
            built = _facet_axes(question, limit)
            if built:
                return built
        return original_axes_for(question, limit=limit)

    axes_mod.axis_set_for = guarded_axis_set_for
    axes_mod.axes_for = guarded_axes_for

    # 2) Relevance: long-question source admission requires distinctive facet
    # alignment.  We deliberately do not require an RCT-style proposition test
    # for books/history/traditional texts; only facet identity is mandatory.
    from . import relevance as relevance_mod
    original_prop = relevance_mod.RelevanceEngine.proposition_check
    original_score = relevance_mod.RelevanceEngine.score_relevance

    def guarded_prop(self, s, query, *args, **kwargs):
        out = original_prop(self, s, query, *args, **kwargs)
        if not _multi_facet(query):
            return out
        align = _facet_alignment(query, s)
        out["facet_alignment"] = align
        if align.get("ok") is False:
            out["tests_proposition"] = False
            out["why"] = (
                "long multi-domain question ke kisi distinctive facet se source "
                "align nahi karta; generic keyword overlap proposition evidence nahi")
        return out

    def guarded_score(self, s, query):
        score = original_score(self, s, query)
        if not _multi_facet(query):
            return score
        try:
            from .models import SourceType
            if s.source_type == SourceType.DOCUMENT:
                return score
        except Exception:
            pass
        align = _facet_alignment(query, s)
        parts = dict(getattr(s, "relevance_parts", {}) or {})
        parts["facet_alignment"] = align
        if align.get("ok") is False:
            detail = (
                "long multi-domain question me source kisi distinctive requested "
                "facet se align nahi karta; generic/ambiguous keyword match rejected")
            s.rejected_reason = detail
            rejections = list(parts.get("rejections") or [])
            if not any(r.get("code") == relevance_mod.REJECT_NO_PROPOSITION
                       for r in rejections if isinstance(r, dict)):
                rejections.append({"code": relevance_mod.REJECT_NO_PROPOSITION,
                                   "dimension": "facet_alignment",
                                   "why": relevance_mod.REJECT_CODE_WHY[
                                       relevance_mod.REJECT_NO_PROPOSITION],
                                   "detail": detail})
            parts.update({"hard_rejected": True, "reason": detail,
                          "reject_code": relevance_mod.REJECT_NO_PROPOSITION,
                          "reject_dimension": "facet_alignment",
                          "tests_proposition": False, "final": 0.0,
                          "rejections": rejections})
            s.relevance_parts = parts
            return 0.0
        parts["facet_alignment"] = align
        s.relevance_parts = parts
        return score

    relevance_mod.RelevanceEngine.proposition_check = guarded_prop
    relevance_mod.RelevanceEngine.score_relevance = guarded_score

    # 3) Contradictions: same facet + shared distinctive proposition required.
    from . import contradiction as contradiction_mod
    original_norm = contradiction_mod.ContradictionEngine._normalized_proposition

    def guarded_norm(self, a, b, question):
        if not _multi_facet(question):
            return original_norm(self, a, b, question)
        aa = _facet_alignment(question, a)
        bb = _facet_alignment(question, b)
        if not aa.get("ok") or not bb.get("ok") or aa.get("key") != bb.get("key"):
            return ""
        shared = sorted(set(aa.get("distinctive") or []) &
                        set(bb.get("distinctive") or []))
        shared_strong = sorted(set(aa.get("strong") or []) &
                               set(bb.get("strong") or []))
        same_phrase = aa.get("phrase") and aa.get("phrase") == bb.get("phrase")
        if len(shared) < 2 and not shared_strong and not same_phrase:
            return ""
        anchors = shared_strong + [x for x in shared if x not in shared_strong]
        if same_phrase and aa.get("phrase") not in anchors:
            anchors.insert(0, aa.get("phrase"))
        anchors = anchors[:4]
        return (f"Same question facet ({aa.get('label', '')[:80]}): "
                f"{' / '.join(anchors)} par opposing result")

    contradiction_mod.ContradictionEngine._normalized_proposition = guarded_norm

    # 4) Structured coverage: bind the stricter audit into the already-installed
    # final result gate as well as the source module.
    from . import structured_answer as structured_mod
    from . import result_coverage_gate as result_gate
    original_coverage = structured_mod.coverage

    def guarded_coverage(question: str, answer: str):
        return _substantive_coverage(original_coverage, structured_mod,
                                     question, answer)

    structured_mod.coverage = guarded_coverage
    result_gate.structured_coverage = guarded_coverage

    # 5) Hypothesis confidence: one-source / arbitrary-numeric hypotheses cannot
    # be MODERATE merely because their prose has a mechanism and contradiction.
    from . import hypothesis as hypothesis_mod
    original_confidence = hypothesis_mod.HypothesisEngine._confidence

    def guarded_confidence(h, gate=None, contradictions=None,
                           counter_search_performed=None,
                           calculations_done=None):
        return _confidence_cap(
            original_confidence, hypothesis_mod, h, gate=gate,
            contradictions=contradictions,
            counter_search_performed=counter_search_performed,
            calculations_done=calculations_done,
        )

    hypothesis_mod.HypothesisEngine._confidence = staticmethod(guarded_confidence)

    # 6) Synthesis generation contract: improve generation, not only validation.
    from . import synthesizer as synthesizer_mod
    original_prompt = synthesizer_mod.FinalSynthesizer.prompt

    def guarded_prompt(self, question, analysis, critique, hypothesis_text,
                       pack, plan, memory_note="", evidence_first_block=""):
        prompt = original_prompt(
            self, question, analysis, critique, hypothesis_text, pack, plan,
            memory_note, evidence_first_block)
        appendix = _quality_prompt_appendix(question)
        if not appendix:
            return prompt
        return f"{prompt.rstrip()}\n\n{appendix}"

    synthesizer_mod.FinalSynthesizer.prompt = guarded_prompt
