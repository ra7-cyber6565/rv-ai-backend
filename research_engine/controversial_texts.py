"""Relevance-driven banned/controversial-text research lane.

The user wants the engine to consider relevant banned, censored, suppressed or
controversial books instead of silently ignoring them.  This module adds that
capability without creating a hand-maintained list of titles and without
changing the project's copyright/access boundary.

Important epistemic rules:

* banned/censored status is historical/legal metadata, NOT evidence that a text
  is true, false, dangerous, suppressed truth, or propaganda;
* original text is read only when the engine already has a legal/public route
  (caller-supplied copy, public domain, open licence, official public access);
* paywall/DRM/password/shadow-library bypass is never requested;
* if the original text is unavailable, reviews, criticism, scholarship and
  historical context may be used, but the answer must say the book itself was
  not read;
* claims made by a controversial text face the same evidence/contradiction
  checks as every other source.

The lane is deterministic and model-free.  It is explicit when the user asks
for banned/controversial texts, and can open automatically in MAXIMUM/MARATHON
for humanities/power questions with strong censorship/propaganda/ideology
signals.  It deliberately does NOT auto-open for ordinary medical/scientific
questions, where a sensational-text lane would pollute evidence retrieval.
"""
from __future__ import annotations

import re
import sys
from typing import Dict, Iterable, List, Sequence


# These are intent words, not a list of books/authors.  Unknown future works can
# therefore travel through the same lane.
_TEXT_NOUN_RE = re.compile(
    r"\b(?:book|books|text|texts|literature|writing|writings|kitab|kitaab|kitabe|"
    r"pustak|granth|manuscript|treatise)\b|(?:किताब|पुस्तक|ग्रंथ)",
    re.IGNORECASE,
)
_BAN_WORD_RE = re.compile(
    r"\b(?:ban(?:ned)?|banned|censor(?:ed|ship)?|prohibit(?:ed|ion)?|proscribed|"
    r"forbidden|suppressed|restricted|blacklisted|controversial|pratibandhit)\b|"
    r"(?:प्रतिबंधित|प्रतिबन्धित|सेंसर)",
    re.IGNORECASE,
)
_EXPLICIT_PHRASES = (
    "banned book", "banned books", "ban book", "ban books", "banned text",
    "banned texts", "censored book", "censored books", "censored text",
    "forbidden book", "forbidden books", "suppressed book", "suppressed books",
    "restricted book", "restricted books", "proscribed book", "proscribed books",
    "controversial book", "controversial books", "controversial text",
    "controversial texts", "pratibandhit kitab", "pratibandhit kitaab",
)

# Auto-discovery needs multiple context signals and high depth.  The list is of
# broad research contexts, never titles or authors.
_CONTEXT_PATTERNS = {
    "censorship": r"\bcensor(?:ed|ship)?\b|\bbook ban(?:ning|s)?\b",
    "propaganda": r"\bpropaganda\b|\binformation warfare\b",
    "ideology": r"\bideolog(?:y|ies|ical)\b",
    "political_power": r"\bpolitical power\b|\bpower network(?:s)?\b|\bauthoritarian\b|\btotalitarian\b",
    "secret_societies": r"\bsecret societ(?:y|ies)\b|\bfreemason(?:ry|s)?\b",
    "conspiracy": r"\bconspirac(?:y|ies)\b|\bnew world order\b",
    "religious_control": r"\breligious persecution\b|\bheresy\b|\bblasphemy\b",
    "revolution": r"\brevolution(?:ary)?\b|\bdissident(?:s)?\b",
    "colonial_control": r"\bcolonial(?:ism)?\b|\bimperial censorship\b",
    "occult_esoteric": r"\boccult\b|\besoteric\b|\bhermetic(?:ism)?\b",
}
_HUMANITIES_TYPES = {"historical", "sociological", "philosophical"}

POLICY_PROMPT = """CONTROVERSIAL / BANNED TEXT RULES (mandatory):
- BANNED STATUS ≠ TRUTH SIGNAL. A text being banned, censored, controversial or suppressed does not make its claims true or false.
- Separate four things: (1) what the text claims, (2) documented banning/censorship history, (3) independent evidence, and (4) strongest scholarly criticism/alternative explanation.
- Use only legally accessible material. Never imply that paywall/DRM/password/access controls were bypassed.
- If the original book/text was not actually accessed, say so explicitly; summaries/reviews are not the book itself.
- Propaganda, extremist or manipulative material is an object of analysis, not an authority to imitate or endorse.
- Apply the SAME citation, relevance, contradiction and evidence-strength gates used for ordinary sources. Do not infer a coordinated conspiracy merely from censorship.
"""


def _clean(text: object, limit: int = 180) -> str:
    return " ".join(str(text or "").split())[:limit].strip()


def _dedupe(items: Iterable[str], limit: int = 4) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items or []:
        text = _clean(item, 220)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _explicit_intent(question: str) -> tuple[bool, List[str]]:
    low = _clean(question, 4000).casefold()
    hits = [phrase for phrase in _EXPLICIT_PHRASES if phrase in low]
    # General form catches e.g. "prohibited literature" or Devanagari wording.
    if _BAN_WORD_RE.search(low) and _TEXT_NOUN_RE.search(low):
        hits.append("ban/censorship word + text noun")
    return bool(hits), _dedupe(hits, limit=5)


def _context_hits(question: str) -> List[str]:
    text = _clean(question, 5000)
    return [name for name, pattern in _CONTEXT_PATTERNS.items()
            if re.search(pattern, text, re.IGNORECASE)]


def build_lane(
    question: str,
    base_query: str = "",
    *,
    question_types: Sequence[str] = (),
    high_depth: bool = False,
) -> Dict:
    """Build a bounded search plan; this object is NEVER evidence itself."""
    explicit, explicit_hits = _explicit_intent(question)
    context = _context_hits(question)
    types = {str(item or "").strip().casefold() for item in question_types or ()}
    humanities = bool(types & _HUMANITIES_TYPES)

    # Automatic lane is intentionally conservative: high depth + humanities
    # context + at least two independent controversy/power signals.  Explicit
    # user intent always wins regardless of depth.
    auto = bool(high_depth and humanities and len(context) >= 2)
    active = bool(explicit or auto)
    mode = "explicit" if explicit else ("automatic_relevance" if auto else "inactive")

    base = _clean(base_query or question, 150)
    works: List[str] = []
    if explicit:
        try:
            from . import classics
            works = _dedupe(classics.work_candidates(question, limit=4), limit=4)
        except Exception:
            works = []

    subject = works[0] if works else base
    catalog_queries: List[str] = []
    review_queries: List[str] = []
    primary_queries: List[str] = []
    if active and subject:
        catalog_queries = _dedupe([
            f"{subject} banned censored controversial books primary sources",
            f"{subject} suppressed prohibited literature bibliography historical context",
        ], limit=2)
        review_queries = _dedupe([
            f"{subject} scholarly criticism censorship history evidence",
            f"{subject} controversial texts academic review strongest criticism context",
        ], limit=2)
        # Actual-text query is only useful when a concrete work candidate exists.
        # The existing classic/copyright layer makes the final access decision.
        if works:
            primary_queries = _dedupe([
                f"{work} full text public domain open license" for work in works[:2]
            ], limit=2)

    return {
        "active": active,
        "mode": mode,
        "explicit": explicit,
        "automatic_relevance": auto,
        "explicit_signals": explicit_hits,
        "context_signals": context,
        "works": works,
        "catalog_queries": catalog_queries,
        "review_queries": review_queries,
        "primary_queries": primary_queries,
        "legal_access_only": True,
        "no_paywall_drm_password_bypass": True,
        "banned_status_is_truth_signal": False,
        "same_evidence_standard": True,
        "original_unavailable_must_say_not_read": True,
        "verified": False,
        "evidence_status": "search_plan_only__banned_or_controversial_status_is_not_evidence",
        "note": (
            "Relevant controversial/banned-text lane active: legal original text when available; "
            "otherwise scholarship/reviews/context, with ordinary evidence gates."
            if active else
            "No explicit or high-confidence relevance signal; controversial-text lane not opened."
        ),
    }


def _merge(first: Sequence[str], second: Sequence[str], limit: int = 4) -> List[str]:
    return _dedupe([*(first or []), *(second or [])], limit=limit)


def install() -> None:
    """Install a small compatibility wrapper around the existing planner.

    This avoids editing Claude-owned discovery/evidence modules.  The wrapper
    only ADDS bounded search directions and a synthesis policy; it cannot mark a
    source relevant, verified, full-text-read, or true.
    """
    from . import planner as planner_mod
    from . import specialist_domains as specialist_mod

    if getattr(planner_mod, "_controversial_text_lane_installed", False):
        return

    original_connector_plan = planner_mod.ResearchPlanner.connector_plan

    def connector_plan(self, cls, config, question=""):
        plan = original_connector_plan(self, cls, config, question)
        high_depth = str(getattr(config, "name", "")).upper() in {"MAXIMUM", "MARATHON"}
        lane = build_lane(
            question or cls.get("question") or "",
            self.clean_query(question or cls.get("question") or ""),
            question_types=cls.get("all_detected_types", cls.get("question_types", [])),
            high_depth=high_depth,
        )
        plan["controversial_text_lane"] = lane
        if not lane.get("active"):
            return plan

        # Explicit user request may open the book tier even in a shallow mode;
        # automatic discovery only happens in high depth by construction.
        wanted_books = ["internet_archive", "open_library"]
        if high_depth:
            wanted_books.append("google_books")
        plan["books"] = _merge(plan.get("books", []), wanted_books, limit=6)

        # Put controversial-lane queries first because SourceDiscovery applies a
        # strict bounded cap.  Existing specialist/classic directions remain.
        plan["book_queries"] = _merge(
            lane.get("catalog_queries", []), plan.get("book_queries", []), limit=4
        )
        plan["summary_queries"] = _merge(
            lane.get("review_queries", []), plan.get("summary_queries", []), limit=4
        )

        # If a concrete work was detected, let the existing legal classic-text
        # connectors attempt it.  Their copyright stance remains the authority.
        if lane.get("primary_queries"):
            plan["classic_queries"] = _merge(
                lane.get("primary_queries", []), plan.get("classic_queries", []), limit=4
            )
            if not plan.get("classics"):
                try:
                    from .connectors.classic_connector import wikisource_langs
                    plan["classics"] = [
                        "wikisource" if code == "en" else f"wikisource_{code}"
                        for code in wikisource_langs()
                    ]
                except Exception:
                    # Discovery will still use book + review lanes; never pretend
                    # the original text was searched if the connector is absent.
                    plan["classics"] = []
        return plan

    planner_mod.ResearchPlanner.connector_plan = connector_plan

    # Synthesis rule: controversial source status is contextual metadata, never
    # an epistemic shortcut.  Patch the function before synthesizer_claude binds
    # it; if that module was already imported, update its bound alias too.
    original_prompt_block = specialist_mod.prompt_block

    def prompt_block(plan):
        base = original_prompt_block(plan)
        lane = ((plan or {}).get("connectors") or {}).get("controversial_text_lane") or {}
        if not lane.get("active"):
            return base
        return (base.rstrip() + "\n\n" + POLICY_PROMPT).strip()

    specialist_mod.prompt_block = prompt_block
    loaded = sys.modules.get("research_engine.synthesizer_claude")
    if loaded is not None:
        setattr(loaded, "specialist_prompt_block", prompt_block)

    planner_mod._controversial_text_lane_installed = True


__all__ = ["POLICY_PROMPT", "build_lane", "install"]
