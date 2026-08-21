"""Memory-safe whole-document page sampling for very large PDFs.

A hard page budget must not mean "read only the first N pages".  Long theses,
standards and books often contain decisive results in later chapters.  This
helper keeps the first/last pages plus an evenly distributed sample across the
entire document.  It is pure Python and deterministic, so it is easy to test
without PyMuPDF or network access.
"""
from __future__ import annotations

from typing import List


def spread_page_indices(
    page_count: int,
    max_pages: int,
    *,
    head_pages: int = 3,
    tail_pages: int = 3,
) -> List[int]:
    """Return sorted 0-based indices covering the whole document.

    If the budget can read the whole PDF, every page is returned. Otherwise:
    - preserve a few opening pages (abstract/TOC/introduction),
    - preserve a few closing pages (conclusion/appendix references),
    - distribute the remaining budget across the middle.

    The returned list never exceeds ``max_pages`` and contains no duplicates.
    """
    total = max(0, int(page_count or 0))
    budget = max(0, int(max_pages or 0))
    if total <= 0 or budget <= 0:
        return []
    if budget >= total:
        return list(range(total))
    if budget == 1:
        return [0]

    selected: set[int] = {0, total - 1}

    for index in range(min(total, max(0, int(head_pages)))):
        if len(selected) >= budget:
            break
        selected.add(index)

    for offset in range(max(0, int(tail_pages))):
        if len(selected) >= budget:
            break
        selected.add(total - 1 - offset)

    remaining = budget - len(selected)
    if remaining > 0:
        # Create more candidate points than needed so rounding collisions near
        # the ends do not leave the budget half-empty.
        slots = max(remaining * 3, remaining + 2)
        for step in range(1, slots + 1):
            if len(selected) >= budget:
                break
            fraction = step / (slots + 1)
            index = int(round(fraction * (total - 1)))
            if 0 <= index < total:
                selected.add(index)

    # Extremely small/awkward ranges can still produce rounding collisions.
    # Fill remaining slots from evenly separated regions, then sequentially as
    # a final deterministic fallback.
    if len(selected) < budget:
        stride = total / float(budget)
        for step in range(budget):
            if len(selected) >= budget:
                break
            index = min(total - 1, int((step + 0.5) * stride))
            selected.add(index)

    if len(selected) < budget:
        for index in range(total):
            if len(selected) >= budget:
                break
            selected.add(index)

    return sorted(selected)[:budget]


def sampling_note(page_count: int, sampled: List[int]) -> str:
    total = max(0, int(page_count or 0))
    if not sampled or total <= 0:
        return ""
    if len(sampled) >= total:
        return f"{total}/{total} pages scan budget mein aaye."
    first = sampled[0] + 1
    last = sampled[-1] + 1
    return (
        f"Safety budget ki wajah se {total} mein se {len(sampled)} pages scan hue, "
        f"lekin sirf shuruaati prefix nahi: sample poore document mein p.{first} "
        f"se p.{last} tak spread kiya gaya."
    )
