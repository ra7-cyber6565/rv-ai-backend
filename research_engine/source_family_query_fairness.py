"""Fair, auditable search scheduling for explicit specialist source families.

Long multi-domain prompts can activate many specialist profiles at once.  The
legacy specialist query builder flattened every profile's seeds and then took
only the first four.  That is deterministic, but unfair: early profiles can
consume the entire per-round budget while later CIA/declassified, allegation,
traditional-text or measured-frequency families never receive a dedicated
query.

This module keeps the same bounded four-query budget.  For multi-profile
questions it rotates *source-family* lanes across rounds so every explicitly
requested family gets a dedicated search opportunity before lanes repeat.
Facet queries continue to cover subject breadth separately.  It also gives
archives and books anchors from the profile that requested them instead of the
first ~200 characters of a giant prompt.

Search plans are not evidence.  Nothing here marks a source relevant, verified
or true, and all existing fail-closed lane/quality gates remain authoritative.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Tuple

_INSTALLED = False

_LANE_SUFFIX: Dict[str, str] = {
    "empirical_science": "empirical study systematic review experiment replication limitations",
    "scholarly_interpretation": "scholarly review criticism interpretation historiography",
    "primary_historical_text": "primary text original source historical context provenance",
    "traditional_belief_text": "traditional text primary source historical scholarship criticism",
    "official_document_record": "official declassified archive original document provenance",
    "allegation_or_conspiracy_claim": "allegation evidence corroboration counterevidence alternative explanation",
    "measured_frequency_evidence": "hertz measurement signal amplitude exposure outcome placebo",
    "secondary_context": "independent context criticism source provenance",
}


def _unique(values: Iterable[str], limit: int = 100) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        clean = " ".join(str(value or "").split()).strip()
        key = clean.casefold()
        if not clean or key in seen:
            continue
        seen.add(key)
        out.append(clean)
        if len(out) >= max(1, int(limit)):
            break
    return out


def _active_profiles(sd, question: str):
    return list(sd.detect_profiles(question or ""))


def _lane_owners(sd, question: str) -> List[Tuple[str, object]]:
    """One deterministic owner profile for each requested source family."""
    profiles = _active_profiles(sd, question)
    owners: List[Tuple[str, object]] = []
    seen = set()
    for profile in profiles:
        for lane in profile.source_lanes:
            if lane in seen or lane == "app_original_hypothesis":
                continue
            seen.add(lane)
            owners.append((lane, profile))
    return owners


def _anchor_for(profile, lane: str, round_no: int) -> str:
    seeds = list(getattr(profile, "search_seeds", ()) or ())
    if seeds:
        # When a lane repeats in later rounds, vary the underlying profile seed
        # rather than issuing the same query again.
        seed = seeds[(max(1, int(round_no or 1)) - 1) % len(seeds)]
    else:
        seed = str(getattr(profile, "label", "") or "")
    suffix = _LANE_SUFFIX.get(lane, "independent evidence criticism limitations")
    return f"{seed} {suffix}".strip()


def source_family_schedule(question: str, rounds: int = 5,
                           per_round: int = 4) -> Dict:
    """Return the bounded lane schedule used by multi-profile research.

    The first pass through the schedule is lane-fair: with the current seven
    specialist source families, all receive a dedicated query by round two at
    four queries/round.  Later rounds vary seeds and repeat for counter/search
    depth rather than silently starving later profiles.
    """
    from . import specialist_domains as sd

    owners = _lane_owners(sd, question)
    lanes = [lane for lane, _ in owners]
    rows: List[Dict] = []
    if not owners:
        return {
            "active": False,
            "required_lanes": [],
            "scheduled_lanes": [],
            "coverage_complete": True,
            "rounds": [],
            "note": "No specialist source-family schedule required.",
        }

    width = max(1, int(per_round or 4))
    total_rounds = max(1, int(rounds or 5))
    for round_no in range(1, total_rounds + 1):
        start = ((round_no - 1) * width) % len(owners)
        picked = [owners[(start + offset) % len(owners)]
                  for offset in range(min(width, len(owners)))]
        queries = []
        for lane, profile in picked:
            query = sd._bounded(_anchor_for(profile, lane, round_no))
            queries.append({
                "lane": lane,
                "profile_key": profile.key,
                "query": query,
                "verified": False,
            })
        rows.append({"round": round_no, "queries": queries})

    scheduled = _unique(
        item["lane"] for row in rows for item in row["queries"],
        limit=100,
    )
    missing = [lane for lane in lanes if lane not in set(scheduled)]
    return {
        "active": True,
        "required_lanes": lanes,
        "scheduled_lanes": scheduled,
        "missing_scheduled_lanes": missing,
        "coverage_complete": not missing,
        "rounds": rows,
        "verified": False,
        "note": (
            "Search-opportunity audit only; a scheduled lane is not evidence and "
            "does not count as covered until qualifying sources reach the evidence pack."
        ),
    }


def _round_queries(sd, original, question: str, base_query: str,
                   round_no: int = 1, limit: int = 4) -> List[str]:
    profiles = _active_profiles(sd, question)
    if len(profiles) <= 1:
        return original(question, base_query, round_no=round_no, limit=limit)

    schedule = source_family_schedule(
        question,
        rounds=max(5, int(round_no or 1)),
        per_round=max(1, int(limit or 4)),
    )
    rows = schedule.get("rounds") or []
    index = max(1, int(round_no or 1)) - 1
    if not rows:
        return original(question, base_query, round_no=round_no, limit=limit)
    row = rows[index % len(rows)]
    return _unique(
        (str(item.get("query") or "") for item in row.get("queries") or []),
        limit=max(1, int(limit or 4)),
    )


def _archive_queries(sd, original, question: str, base_query: str,
                     limit: int = 3) -> List[str]:
    profiles = [p for p in _active_profiles(sd, question)
                if getattr(p, "archive_family", "")]
    if not profiles:
        return original(question, base_query, limit=limit)

    # Build the archive anchor from the profile that actually requested archival
    # evidence.  This avoids a giant prompt's opening neuroscience paragraph
    # becoming the query sent to CIA/NARA/FBI archives.
    anchors: List[str] = []
    for profile in profiles:
        hits = [signal for signal in profile.signals if sd.phrase_hit(question, signal)]
        seed = " ".join(hits[:4]).strip()
        if not seed:
            seed = (profile.search_seeds[0] if profile.search_seeds else profile.label)
        anchors.append(seed)
    anchor = sd._bounded(" ".join(_unique(anchors, limit=4)))
    return _unique(
        (sd._bounded(f"{site} {anchor}") for site in sd._ARCHIVE_SITES),
        limit=max(1, int(limit or 3)),
    )


def _build_plan(sd, original, question: str, base_query: str) -> Dict:
    plan = dict(original(question, base_query) or {})
    profiles = _active_profiles(sd, question)
    if len(profiles) <= 1:
        return plan

    schedule = source_family_schedule(question, rounds=5, per_round=4)
    plan["source_family_query_schedule"] = schedule

    # Give every book-requiring profile at least one bounded catalogue/full-text
    # lead.  Existing multilingual/public-domain queries stay first and are not
    # removed.
    extra_books: List[str] = []
    for profile in profiles:
        if not getattr(profile, "requires_books", False):
            continue
        seed = profile.search_seeds[0] if profile.search_seeds else profile.label
        extra_books.append(sd._bounded(
            f"{seed} primary text book original source scholarly criticism"))
    plan["book_queries"] = _unique(
        [*(plan.get("book_queries") or []), *extra_books],
        limit=12,
    )
    # Recompute archive queries through the profile-scoped wrapper.
    plan["official_archive_queries"] = sd.official_archive_queries(
        question, base_query, limit=3)
    return plan


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from . import specialist_domains as sd

    if getattr(sd, "_SOURCE_FAMILY_QUERY_FAIRNESS_INSTALLED", False):
        return

    original_queries = sd.specialist_queries
    original_archive = sd.official_archive_queries
    original_build = sd.build_specialist_plan

    def specialist_queries(question: str, base_query: str, round_no: int = 1,
                           limit: int = 4) -> List[str]:
        return _round_queries(
            sd, original_queries, question, base_query,
            round_no=round_no, limit=limit,
        )

    def official_archive_queries(question: str, base_query: str,
                                 limit: int = 3) -> List[str]:
        return _archive_queries(
            sd, original_archive, question, base_query, limit=limit)

    def build_specialist_plan(question: str, base_query: str) -> Dict:
        return _build_plan(sd, original_build, question, base_query)

    # Patch the source module first.  Planner may already be imported by an
    # earlier install hook, so patch its bound module globals as well.
    sd.specialist_queries = specialist_queries
    sd.official_archive_queries = official_archive_queries
    sd.build_specialist_plan = build_specialist_plan
    sd._SOURCE_FAMILY_QUERY_FAIRNESS_INSTALLED = True

    try:
        from . import planner as planner_mod
        planner_mod.specialist_queries = specialist_queries
        planner_mod.build_specialist_plan = build_specialist_plan
    except Exception:
        # planner is lazy in normal package imports; when it loads later it will
        # bind the already-patched specialist_domains functions.
        pass


__all__ = ["install", "source_family_schedule"]
