"""Regression tests for huge-PDF whole-document sparse sampling.

These tests are pure Python: no network, API key or PyMuPDF required.  They
protect against the subtle failure where a 3000-page PDF scan budget inspected
only pages 1..2500 and could never see important evidence near the end.
"""
from __future__ import annotations

from research_engine.processing import pdf_chunker


QUESTION = "room temperature superconductivity ambient pressure critical temperature"
RELEVANT = (
    "Room temperature superconductivity at ambient pressure remains an open "
    "materials-science problem. Critical temperature, Meissner effect and "
    "superconducting transport are discussed here. " * 5
)
IRRELEVANT = (
    "This page discusses agricultural crop surveys, rainfall and soil moisture "
    "statistics across several districts. " * 6
)


def test_sparse_indices_cover_beginning_middle_and_end_not_only_first_n():
    indices = pdf_chunker.sample_page_indices(3000, 100, head_pages=3, tail_pages=3)
    assert len(indices) == 100
    assert indices == sorted(set(indices))
    assert indices[:3] == [0, 1, 2]
    assert indices[-3:] == [2997, 2998, 2999]
    assert any(1400 <= i <= 1600 for i in indices), indices
    assert max(indices) > 2900
    assert indices != list(range(100)), "whole-document sample first-N-only nahi hona chahiye"


def test_sampling_returns_all_pages_when_budget_is_large_enough():
    assert pdf_chunker.sample_page_indices(8, 20) == list(range(8))
    assert pdf_chunker.sample_page_indices(8, 8) == list(range(8))
    assert pdf_chunker.sample_page_indices(0, 5) == []


def test_late_relevant_page_can_survive_sparse_selection_and_scope_is_honest():
    total = 3000
    indices = pdf_chunker.sample_page_indices(total, 120, head_pages=3, tail_pages=3)
    late_index = indices[-4]  # late interior sample, not one of the forced final 3 pages
    assert late_index > 2500

    pages = []
    for index in indices:
        pages.append({
            "page": index + 1,
            "text": RELEVANT if index == late_index else IRRELEVANT,
        })

    selected = pdf_chunker.select_pages(
        pages,
        QUESTION,
        file_name="huge_thesis.pdf",
        pages_total=total,
        max_pages_scanned=len(indices),
        max_keep_pages=8,
        sampling_mode="whole_document_sparse",
    )

    kept_pages = [chunk["page"] for chunk in selected.chunks]
    assert late_index + 1 in kept_pages, kept_pages
    assert selected.pages_scanned == len(indices)
    assert selected.pages_total == total
    assert selected.stopped_early is True
    assert selected.sampling_mode == "whole_document_sparse"
    note = selected.note().lower()
    assert "whole-document sparse sampling" in note
    assert "beginning, beech aur end" in note
    assert "first-n-only nahi" in note
    assert "3000" in note


def test_sparse_sampling_metadata_is_exposed_for_audit():
    selected = pdf_chunker.select_pages(
        [{"page": 1, "text": RELEVANT}, {"page": 500, "text": RELEVANT}],
        QUESTION,
        file_name="sample.pdf",
        pages_total=1000,
        max_pages_scanned=2,
        sampling_mode="whole_document_sparse",
    )
    data = selected.to_dict()
    assert data["sampling_mode"] == "whole_document_sparse"
    assert data["stopped_early"] is True
    assert data["pages_scanned"] == 2
    assert data["pages_total"] == 1000
