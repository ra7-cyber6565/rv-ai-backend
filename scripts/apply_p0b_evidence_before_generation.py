"""Guarded one-shot P0-B integration patcher.

Applies only small, exact anchors to the current post-#18 main architecture.
Every replacement must match exactly once; otherwise the script aborts before
writing that file.  No thresholds are changed.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ORCH = ROOT / "research_engine" / "orchestrator.py"
SYNTH = ROOT / "research_engine" / "synthesizer_claude.py"
QUALITY = ROOT / "research_engine" / "quality_producers.py"
FINAL_GATE = ROOT / "research_engine" / "final_quality_gate.py"
CLAIMS = ROOT / "research_engine" / "claim_verification.py"

EXPECTED_THRESHOLDS = {
    "_ENTAIL_SIM": "0.30",
    "_ENTAIL_SIM_WITH_NUM": "0.12",
    "_MIN_TEXT_CHARS": "120",
    "_MIN_RELEVANCE": "0.25",
    "_MIN_QUALITY": "0.35",
    "_LOW_QUALITY": "0.20",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exact anchor once, found {count}")
    if new in text:
        raise RuntimeError(f"{label}: replacement already present; refusing double apply")
    return text.replace(old, new, 1)


def threshold_snapshot() -> dict:
    text = read(CLAIMS)
    out = {}
    for name, expected in EXPECTED_THRESHOLDS.items():
        match = re.search(rf"^{re.escape(name)}\s*=\s*([^\s#]+)", text, re.MULTILINE)
        if not match:
            raise RuntimeError(f"threshold {name} missing")
        out[name] = match.group(1)
        if out[name] != expected:
            raise RuntimeError(
                f"threshold {name} is {out[name]}, expected {expected}; refusing patch"
            )
    return out


def patch_orchestrator(text: str) -> str:
    text = replace_once(
        text,
        "from .evidence import EvidenceEngine\nfrom .gemini_reasoning import GeminiReasoning, QuotaExhausted\n",
        "from .evidence import EvidenceEngine\n"
        "from .evidence_drafting import (\n"
        "    audit_claims_against_manifest, build_evidence_draft_manifest,\n"
        ")\n"
        "from .gemini_reasoning import GeminiReasoning, QuotaExhausted\n",
        "orchestrator import evidence_drafting",
    )

    text = replace_once(
        text,
        "               \"technical_details\": [], \"api_accounting\": {}}\n\n"
        "        # ── user ki EXPLICIT requests (planner ne rule-based nikaali hain) ────\n",
        "               \"technical_details\": [], \"api_accounting\": {}}\n\n"
        "        # P0-B — evidence exists BEFORE any model-generated factual prose.\n"
        "        # The private manifest retains source text only for runtime audit;\n"
        "        # the compact form exposes hashes/locators/counts without copying\n"
        "        # source passages into API diagnostics.\n"
        "        draft_manifest = build_evidence_draft_manifest(question, pack)\n"
        "        evidence_first_block = draft_manifest.prompt_block()\n"
        "        out[\"_evidence_first_manifest\"] = draft_manifest\n"
        "        out[\"evidence_first_manifest\"] = draft_manifest.to_dict()\n\n"
        "        # ── user ki EXPLICIT requests (planner ne rule-based nikaali hain) ────\n",
        "orchestrator manifest construction",
    )

    text = replace_once(
        text,
        "                prompt = brain.prompt_analysis(question, pack, plan)\n"
        "                if memory_note:\n"
        "                    prompt = f\"{memory_note}\\n\\n{prompt}\"\n"
        "                # EXPLICIT request ho to hypotheses PEHLI call mein hi maang lete\n",
        "                prompt = brain.prompt_analysis(question, pack, plan)\n"
        "                if memory_note:\n"
        "                    prompt = f\"{memory_note}\\n\\n{prompt}\"\n"
        "                # P0-B is appended LAST so broad source/context text cannot\n"
        "                # silently override the critical-claim preselection contract.\n"
        "                prompt = f\"{prompt}\\n\\n{evidence_first_block}\"\n"
        "                # EXPLICIT request ho to hypotheses PEHLI call mein hi maang lete\n",
        "orchestrator analysis prompt evidence-first block",
    )

    text = replace_once(
        text,
        "            else:\n"
        "                out[\"analysis\"] = brain.generate(\n"
        "                    brain.prompt_no_sources(question, plan), \"no-source answer\")\n",
        "            else:\n"
        "                no_source_prompt = brain.prompt_no_sources(question, plan)\n"
        "                no_source_prompt = f\"{no_source_prompt}\\n\\n{evidence_first_block}\"\n"
        "                out[\"analysis\"] = brain.generate(\n"
        "                    no_source_prompt, \"no-source answer\")\n",
        "orchestrator no-source prompt evidence-first block",
    )

    text = replace_once(
        text,
        "            prompt = self.synthesizer.prompt(question, out[\"analysis\"], critique_text,\n"
        "                                             out[\"hypothesis_raw\"], pack, plan,\n"
        "                                             memory_note)\n",
        "            prompt = self.synthesizer.prompt(question, out[\"analysis\"], critique_text,\n"
        "                                             out[\"hypothesis_raw\"], pack, plan,\n"
        "                                             memory_note,\n"
        "                                             evidence_first_block=evidence_first_block)\n",
        "orchestrator synthesis prompt evidence-first block",
    )

    text = replace_once(
        text,
        "        claim_checks = verify_claims(claim_source_text, pack).to_dict()\n"
        "        if claim_checks.get(\"overclaims\"):\n",
        "        claim_checks = verify_claims(claim_source_text, pack).to_dict()\n"
        "        evidence_first_audit = audit_claims_against_manifest(\n"
        "            claim_checks, passes.get(\"_evidence_first_manifest\"))\n"
        "        unmatched_preselected = int(\n"
        "            evidence_first_audit.get(\"critical_claims_preselected_span_unmatched\") or 0)\n"
        "        if unmatched_preselected:\n"
        "            warnings.append(\n"
        "                f\"{unmatched_preselected} same-source supported critical claim ka \"\n"
        "                \"canonical span drafting se pehle preselected evidence mein nahi tha; \"\n"
        "                \"verified/release gate fail-closed rahega.\")\n"
        "        if claim_checks.get(\"overclaims\"):\n",
        "orchestrator post-generation manifest audit",
    )

    text = replace_once(
        text,
        "        verification[\"claim_checks\"] = claim_checks\n"
        "        # point 11 — kitni hypotheses evidence ke hisaab se banayi ja sakti thi,\n",
        "        verification[\"claim_checks\"] = claim_checks\n"
        "        verification[\"evidence_first_audit\"] = evidence_first_audit\n"
        "        verification[\"evidence_first_manifest\"] = (\n"
        "            passes.get(\"evidence_first_manifest\") or {})\n"
        "        # point 11 — kitni hypotheses evidence ke hisaab se banayi ja sakti thi,\n",
        "orchestrator expose compact evidence-first audit",
    )

    text = replace_once(
        text,
        "            answer_text=annotated,\n"
        "            verification=claim_checks,\n"
        "            # §10 ka pehla hissa: counter-side search SACH mein chali ya nahi.\n",
        "            answer_text=annotated,\n"
        "            verification=claim_checks,\n"
        "            evidence_first_audit=evidence_first_audit,\n"
        "            # §10 ka pehla hissa: counter-side search SACH mein chali ya nahi.\n",
        "orchestrator quality context evidence-first audit",
    )
    return text


def patch_synthesizer(text: str) -> str:
    text = replace_once(
        text,
        "    def prompt(self, question: str, analysis: str, critique: str, hypothesis_text: str,\n"
        "               pack: EvidencePack, plan: Dict, memory_note: str = \"\") -> str:\n",
        "    def prompt(self, question: str, analysis: str, critique: str, hypothesis_text: str,\n"
        "               pack: EvidencePack, plan: Dict, memory_note: str = \"\",\n"
        "               evidence_first_block: str = \"\") -> str:\n",
        "synthesizer prompt signature",
    )
    text = replace_once(
        text,
        "        specialist_rules = specialist_prompt_block(plan)\n\n"
        "        return f\"\"\"Tum ek bahut acche teacher ho. Tumhara kaam research ka result\n",
        "        specialist_rules = specialist_prompt_block(plan)\n"
        "        evidence_first_prompt = (evidence_first_block or \"\").strip()\n\n"
        "        return f\"\"\"Tum ek bahut acche teacher ho. Tumhara kaam research ka result\n",
        "synthesizer evidence-first variable",
    )
    text = replace_once(
        text,
        "SOURCES (sirf inhi IDs se cite karo):\n"
        "{pack.to_prompt_block(max_chars_per_source=500)}\n\n"
        "{CITATION_INSTRUCTION}\n",
        "SOURCES (sirf inhi IDs se cite karo):\n"
        "{pack.to_prompt_block(max_chars_per_source=500)}\n\n"
        "{evidence_first_prompt}\n\n"
        "{CITATION_INSTRUCTION}\n",
        "synthesizer insert evidence-first prompt block",
    )
    return text


def patch_quality(text: str) -> str:
    text = replace_once(
        text,
        "    \"average_relevance\", \"critical_claim_spans_complete\",\n"
        "    \"critical_claims_same_source_ae_passed\", \"claim_verification_achievement\",\n",
        "    \"average_relevance\", \"critical_claim_spans_complete\",\n"
        "    \"critical_claims_same_source_ae_passed\", \"claim_verification_achievement\",\n"
        "    \"evidence_first_required\", \"critical_claim_preselection_complete\",\n"
        "    \"critical_claims_preselected_span_unmatched\", \"evidence_first_achievement\",\n",
        "quality tri-state evidence-first fields",
    )
    text = replace_once(
        text,
        "                    contradiction_rejections: Optional[Dict] = None,\n"
        "                    evidence_graph: Optional[bool] = None,\n"
        "                    axis_coverage: Optional[Sequence[Dict]] = None,\n"
        "                    floor: float = DIRECT_RELEVANCE_FLOOR) -> Dict:\n",
        "                    contradiction_rejections: Optional[Dict] = None,\n"
        "                    evidence_graph: Optional[bool] = None,\n"
        "                    axis_coverage: Optional[Sequence[Dict]] = None,\n"
        "                    evidence_first_audit: Optional[Dict] = None,\n"
        "                    floor: float = DIRECT_RELEVANCE_FLOOR) -> Dict:\n",
        "quality context signature evidence-first audit",
    )
    text = replace_once(
        text,
        "    vdict = _verification_dict(verification)\n"
        "    supporting = None\n",
        "    vdict = _verification_dict(verification)\n"
        "    evidence_first = (dict(evidence_first_audit)\n"
        "                      if isinstance(evidence_first_audit, dict) else None)\n"
        "    supporting = None\n",
        "quality context normalize evidence-first audit",
    )
    text = replace_once(
        text,
        "        \"critical_claim_evidence_spans\": (vdict or {}).get(\"critical_claim_spans\"),\n"
        "        \"critical_no_source_claims\": len([c for c in no_source if c[\"critical\"]]),\n",
        "        \"critical_claim_evidence_spans\": (vdict or {}).get(\"critical_claim_spans\"),\n"
        "        # P0-B — no raw evidence passage is copied into quality_context;\n"
        "        # hashes/locators/counts are sufficient for release audit.\n"
        "        \"evidence_first_required\": (evidence_first or {}).get(\"evidence_first_required\")\n"
        "            if evidence_first is not None else None,\n"
        "        \"preselected_evidence_spans_count\":\n"
        "            (evidence_first or {}).get(\"preselected_evidence_spans_count\")\n"
        "            if evidence_first is not None else None,\n"
        "        \"preselected_strong_eligible_spans\":\n"
        "            (evidence_first or {}).get(\"preselected_strong_eligible_spans\")\n"
        "            if evidence_first is not None else None,\n"
        "        \"critical_claims_preselected_span_matched\":\n"
        "            (evidence_first or {}).get(\"critical_claims_preselected_span_matched\")\n"
        "            if evidence_first is not None else None,\n"
        "        \"critical_claims_preselected_span_unmatched\":\n"
        "            (evidence_first or {}).get(\"critical_claims_preselected_span_unmatched\")\n"
        "            if evidence_first is not None else None,\n"
        "        \"critical_claim_preselection_complete\":\n"
        "            (evidence_first or {}).get(\"critical_claim_preselection_complete\")\n"
        "            if evidence_first is not None else None,\n"
        "        \"evidence_first_achievement\":\n"
        "            (evidence_first or {}).get(\"evidence_first_achievement\")\n"
        "            if evidence_first is not None else None,\n"
        "        \"evidence_first_claim_matches\":\n"
        "            list((evidence_first or {}).get(\"claim_matches\") or [])\n"
        "            if evidence_first is not None else None,\n"
        "        \"evidence_first_failures\":\n"
        "            list((evidence_first or {}).get(\"preselection_failures\") or [])\n"
        "            if evidence_first is not None else None,\n"
        "        \"critical_no_source_claims\": len([c for c in no_source if c[\"critical\"]]),\n",
        "quality context evidence-first fields",
    )
    return text


def patch_final_gate(text: str) -> str:
    old = (
        "        no_source_count = _as_int(\n"
        "            quality_context.get(\"critical_no_source_claims\"),\n"
        "            len(NO_SOURCE_RE.findall(answer)),\n"
        "        )\n"
    )
    new = (
        "        # P0-B — post-hoc citation fitting is not release-safe. Legacy\n"
        "        # callers remain compatible when the field is absent/None; the\n"
        "        # current orchestrator explicitly sets it True and must then\n"
        "        # provide a complete preselection audit. Zero supported critical\n"
        "        # claims are handled separately by P0-A's non-vacuous achievement.\n"
        "        evidence_first_required = quality_context.get(\"evidence_first_required\") is True\n"
        "        if evidence_first_required:\n"
        "            preselection_flag = quality_context.get(\"critical_claim_preselection_complete\")\n"
        "            preselection_unmatched = _as_int(\n"
        "                quality_context.get(\"critical_claims_preselected_span_unmatched\"))\n"
        "            preselection_ok = (preselection_flag is not None\n"
        "                               and _as_bool(preselection_flag)\n"
        "                               and preselection_unmatched == 0)\n"
        "        else:\n"
        "            preselection_unmatched = 0\n"
        "            preselection_ok = True\n"
        "        state.check(\"critical_claims_preselected_before_generation\", preselection_ok)\n"
        "        if not preselection_ok:\n"
        "            state.issue(\n"
        "                \"CRITICAL_CLAIM_NOT_PRESELECTED\",\n"
        "                \"claim_citation\",\n"
        "                \"critical\",\n"
        "                \"A supported critical claim used evidence that was not in the pre-draft manifest.\",\n"
        "                deduction=8,\n"
        "                hard_cap=60,\n"
        "                details={\"unmatched\": preselection_unmatched},\n"
        "            )\n\n"
        "        no_source_count = _as_int(\n"
        "            quality_context.get(\"critical_no_source_claims\"),\n"
        "            len(NO_SOURCE_RE.findall(answer)),\n"
        "        )\n"
    )
    return replace_once(text, old, new, "final gate preselection enforcement")


def main() -> None:
    before = threshold_snapshot()
    originals = {
        ORCH: read(ORCH),
        SYNTH: read(SYNTH),
        QUALITY: read(QUALITY),
        FINAL_GATE: read(FINAL_GATE),
    }
    patched = {
        ORCH: patch_orchestrator(originals[ORCH]),
        SYNTH: patch_synthesizer(originals[SYNTH]),
        QUALITY: patch_quality(originals[QUALITY]),
        FINAL_GATE: patch_final_gate(originals[FINAL_GATE]),
    }

    # All guards ran before the first write: a stale/partial architecture cannot
    # leave half the integration applied.
    for path, content in patched.items():
        path.write_text(content, encoding="utf-8", newline="\n")

    after = threshold_snapshot()
    if before != after or after != EXPECTED_THRESHOLDS:
        raise RuntimeError(f"threshold drift detected: before={before}, after={after}")

    # Structural postconditions; behavioral tests still decide correctness.
    orch = read(ORCH)
    synth = read(SYNTH)
    quality = read(QUALITY)
    gate = read(FINAL_GATE)
    required = {
        "manifest built before reasoning": "build_evidence_draft_manifest(question, pack)" in orch,
        "analysis prompt constrained": "{prompt}\\n\\n{evidence_first_block}" in orch,
        "synthesis prompt constrained": "evidence_first_block=evidence_first_block" in orch,
        "post-generation audit": "audit_claims_against_manifest" in orch,
        "quality audit wired": "evidence_first_audit=evidence_first_audit" in orch,
        "synthesizer prompt accepts block": "evidence_first_block: str = \"\"" in synth,
        "quality context exposes audit": "critical_claim_preselection_complete" in quality,
        "release gate fail-closed": "CRITICAL_CLAIM_NOT_PRESELECTED" in gate,
    }
    missing = [name for name, ok in required.items() if not ok]
    if missing:
        raise RuntimeError("postcondition failed: " + ", ".join(missing))

    print("P0-B evidence-before-generation integration applied safely to 4 files.")
    print("Thresholds unchanged:", after)
    for name in required:
        print(f"[OK] {name}")


if __name__ == "__main__":
    main()
