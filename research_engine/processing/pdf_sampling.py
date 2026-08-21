"""Memory-safe whole-document page sampling for very large PDFs.

A hard page budget must not mean "read only the first N pages". Long theses,
standards and books often contain decisive results in later chapters. This
helper keeps opening/closing pages plus evenly distributed interior pages across
the *entire* document. It is pure Python, deterministic and zero-cost.
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
    """Return sorted 0-based indices spanning the whole document.

    If budget covers the PDF, return every page. Otherwise reserve a few opening
    and closing pages and place every remaining slot at an evenly spaced interior
    quantile. Rounding collisions are filled deterministically without ever
    dropping the reserved tail pages.
    """
    total = max(0, int(page_count or 0))
    budget = max(0, int(max_pages or 0))
    if total <= 0 or budget <= 0:
        return []
    if budget >= total:
        return list(range(total))

    budget = max(1, min(budget, total))
    selected: set[int] = set()

    head = min(max(0, int(head_pages or 0)), budget, total)
    selected.update(range(head))

    remaining = budget - len(selected)
    tail = min(max(0, int(tail_pages or 0)), remaining, total - len(selected))
    if tail:
        selected.update(range(total - tail, total))

    remaining = budget - len(selected)
    interior_start = head
    interior_end = max(interior_start, total - tail)  # exclusive
    interior_len = max(0, interior_end - interior_start)

    if remaining > 0 and interior_len > 0:
        # One quantile per remaining slot across the *whole* interior. This is
        # intentionally not an oversampled loop that stops early, because that
        # would bias all middle slots toward the first third of a long PDF.
        for slot in range(1, remaining + 1):
            fraction = slot / (remaining + 1)
            index = interior_start + int(round(fraction * max(0, interior_len - 1)))
            index = min(interior_end - 1, max(interior_start, index))
            selected.add(index)

    # Rounding can collide on tiny interiors. Fill from the interior first so
    # reserved beginning/end coverage is preserved; then use any page as a last
    # deterministic fallback.
    if len(selected) < budget:
        for index in range(interior_start, interior_end):
            selected.add(index)
            if len(selected) >= budget:
                break
    if len(selected) < budget:
        for index in range(total):
            selected.add(index)
            if len(selected) >= budget:
                break

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
        f"Safety budget ki wajah se {total} mein se {len(sampled)} pages inspect hue, "
        f"lekin first-N prefix nahi: sample poore document mein beginning, middle aur "
        f"end tak p.{first} se p.{last} range mein spread kiya gaya."
    )
