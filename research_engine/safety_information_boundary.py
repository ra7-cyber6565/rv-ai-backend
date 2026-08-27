"""Warn-and-explain boundary for illegal / high-risk informational topics.

This layer deliberately does *not* weaken application security and does not turn
``safe_to_proceed`` into permission for unrestricted instructions.  It keeps the
research lane open for useful context while sealing the model/output contract:

* illegal/dangerous subject matter may be researched and explained;
* legality is not inferred merely from a keyword;
* contextual, historical, defensive and harm-reduction information stays visible;
* operational wrongdoing / serious-harm enablement remains out of scope;
* the final human-facing report gets a deterministic warning block.

The module is pure Python and performs no network/model call at install time.
"""
from __future__ import annotations

import sys
from typing import Dict

from safety.checks import check_safety, prepend_safety_notice, safety_prompt_appendix


def _boundary_active(safety: Dict) -> bool:
    return bool(safety_prompt_appendix(safety or {}))


def install() -> None:
    """Install planner + prompt + report wrappers exactly once."""
    from . import planner as planner_mod
    from . import specialist_domains as specialist_mod

    if getattr(planner_mod, "_safety_information_boundary_installed", False):
        return

    # 1) Put the deterministic safety decision into the normal plan so every
    # downstream consumer sees the same machine-readable boundary.
    original_connector_plan = planner_mod.ResearchPlanner.connector_plan

    def connector_plan(self, cls, config, question=""):
        plan = original_connector_plan(self, cls, config, question)
        text = question or (cls.get("question") if isinstance(cls, dict) else "") or ""
        plan["safety_information_boundary"] = check_safety(text)
        return plan

    planner_mod.ResearchPlanner.connector_plan = connector_plan

    # 2) Add the safety policy to reasoning/synthesis prompts.  The normal
    # specialist evidence boundary remains intact; this only appends a second,
    # narrower instruction about what may be explained versus operationalized.
    original_prompt_block = specialist_mod.prompt_block

    def prompt_block(plan):
        base = original_prompt_block(plan)
        boundary = ((plan or {}).get("connectors") or {}).get(
            "safety_information_boundary") or {}
        appendix = safety_prompt_appendix(boundary)
        if not appendix:
            return base
        return (base.rstrip() + "\n\n" + appendix).strip() if base else appendix

    specialist_mod.prompt_block = prompt_block

    # 3) Preserve the boundary in the structured evidence-lane report even when
    # no esoteric/specialist profile is active.  This is metadata/policy only;
    # it does not upgrade evidence or truth state.
    original_build_report = specialist_mod.build_evidence_lane_report

    def build_evidence_lane_report(question, plan, pack):
        report = original_build_report(question, plan, pack)
        report = dict(report or {})
        boundary = ((plan or {}).get("connectors") or {}).get(
            "safety_information_boundary") or check_safety(question)
        if _boundary_active(boundary):
            report["safety_information_boundary"] = boundary
        return report

    specialist_mod.build_evidence_lane_report = build_evidence_lane_report

    # 4) Human-facing warning is deterministic.  We do not rely on the model to
    # remember it.  A non-specialist illegal/high-risk question can therefore
    # still show the warning even though the ordinary evidence-lane renderer
    # would otherwise return an empty string.
    original_render_report = specialist_mod.render_evidence_lane_report

    def render_evidence_lane_report(report):
        base = original_render_report(report)
        boundary = (report or {}).get("safety_information_boundary") or {}
        if not _boundary_active(boundary):
            return base
        notice = prepend_safety_notice("", boundary).strip()
        block = f"## Safety / legal boundary\n{notice}" if notice else ""
        if base and block:
            return f"{block}\n\n{base}"
        return block or base

    specialist_mod.render_evidence_lane_report = render_evidence_lane_report

    # If a synthesizer module happened to load before this installer, update its
    # already-bound alias too.  In the normal lazy-import path this is a no-op.
    loaded = sys.modules.get("research_engine.synthesizer")
    if loaded is not None:
        setattr(loaded, "render_evidence_lane_report", render_evidence_lane_report)
    loaded_claude = sys.modules.get("research_engine.synthesizer_claude")
    if loaded_claude is not None:
        setattr(loaded_claude, "specialist_prompt_block", prompt_block)

    planner_mod._safety_information_boundary_installed = True


__all__ = ["install"]
