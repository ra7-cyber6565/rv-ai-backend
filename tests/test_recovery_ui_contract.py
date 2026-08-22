"""§21+§22 — UI ka contract: chhah tab, baarah stage, ek hi recovery banner.

Ye test browser nahi chalata. Ye `web/index.html` ke andar ka table backend ke
saath match karta hai, taaki UI aur backend chup-chaap alag na ho jaayein. Live
dark-matter run ki jo dikkatein yahan regression ban rahi hain:

  * answer ke section UI mein gayab ho jaate the (ya ek hi jagah chipak jaate the);
  * job khatam hote hi "research process" wala text screen se ud jaata tha;
  * recovery ka footer do baar chhap gaya tha;
  * "koi contradiction nahi mila" ko "check ho gaya, sab theek hai" padha jaata tha;
  * app ke idea ko "naya" bataya jaata tha jabki prior-art search hui hi nahi thi.

Poora offline: koi network, koi model, koi browser.

Chalane ka tareeka (repo root = backend/):
    PYTHONPATH=. python3 tests/test_recovery_ui_contract.py
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.answer_order import CANONICAL_SECTIONS, LAB_HEADING  # noqa: E402
from utils.progress_tracker import STAGES                                # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PAGE = os.path.join(_ROOT, "web", "index.html")


def _html() -> str:
    with open(_PAGE, encoding="utf-8") as handle:
        return handle.read()


def _script() -> str:
    blocks = re.findall(r"<script[^>]*>(.*?)</script>", _html(), re.S)
    assert blocks, "index.html mein koi <script> block nahi mila"
    return "\n".join(blocks)


def _body(name: str, script: str | None = None) -> str:
    """Ek JS function ka source nikalo (brace-count se, nested braces ke saath)."""
    text = script if script is not None else _script()
    start = text.find("function %s(" % name)
    assert start != -1, "JS function %s nahi mila" % name
    open_at = text.find("{", start)
    depth, index = 0, open_at
    while index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[open_at:index + 1]
        index += 1
    raise AssertionError("%s ka body band nahi hua" % name)


def _js_sections(script: str) -> list:
    block = re.search(r"const SECTIONS=\[(.*?);", script, re.S)
    assert block, "JS mein SECTIONS table nahi mila"
    rows = re.findall(r'\["([^"]+)","([^"]*)",\[([^\]]*)\]\]', block.group(1))
    assert rows, "SECTIONS table ki rows parse nahi hui"
    return [(key, name, tuple(re.findall(r'"([^"]*)"', aliases)))
            for key, name, aliases in rows]


def _js_tab_sections(script: str) -> dict:
    block = re.search(r"const TAB_SECTIONS=\{(.*?)\};", script, re.S)
    assert block, "JS mein TAB_SECTIONS nahi mila"
    return {tab: re.findall(r'"([^"]*)"', body)
            for tab, body in re.findall(r"(\w+):\[([^\]]*)\]", block.group(1))}


def _js_tab_names(script: str) -> dict:
    block = re.search(r"const TAB_NAMES=\{(.*?)\};", script, re.S)
    assert block, "JS mein TAB_NAMES nahi mila"
    return dict(re.findall(r'(\w+):"([^"]*)"', block.group(1)))


def _js_stages(script: str) -> list:
    block = re.search(r"const STAGES=\[(.*?)\];", script, re.S)
    assert block, "JS mein STAGES list nahi mili"
    return re.findall(r'"([^"]*)"', block.group(1))


# --- §12/§21: answer ka table backend se mirror hona chahiye ----------------

def test_js_section_table_mirrors_backend_answer_order():
    rows = _js_sections(_script())
    assert [r[0] for r in rows] == [r[0] for r in CANONICAL_SECTIONS]
    assert [r[1] for r in rows] == [r[1] for r in CANONICAL_SECTIONS]
    for js_row, py_row in zip(rows, CANONICAL_SECTIONS):
        assert list(js_row[2]) == list(py_row[3]), js_row[0]


def test_lab_heading_is_word_for_word_the_same_in_the_ui():
    rows = {r[0]: r[1] for r in _js_sections(_script())}
    assert rows["original_lab"] == LAB_HEADING
    assert LAB_HEADING in _html()


def test_every_canonical_section_lands_in_exactly_one_tab():
    tabs = _js_tab_sections(_script())
    placed = [key for keys in tabs.values() for key in keys]
    assert sorted(placed) == sorted(r[0] for r in CANONICAL_SECTIONS)
    assert len(placed) == len(set(placed)), "ek section do tab mein hai"


def test_six_tabs_exist_and_process_tab_holds_no_answer_section():
    script = _script()
    names = _js_tab_names(script)
    assert set(names) == {"answer", "evidence", "lab", "sources", "process", "audit"}
    assert "process" not in _js_tab_sections(script)
    body = _body("renderResearch", script)
    order = re.search(r'const order=\[(.*?)\];', body)
    assert order and re.findall(r'"([^"]*)"', order.group(1)) == [
        "answer", "evidence", "lab", "sources", "process", "audit"]


def test_unrecognised_heading_is_shown_not_dropped():
    body = _body("renderResearch")
    assert "!known.includes(b.key)" in body
    assert "split.lead" in body, "bina heading wala text bhi dikhna chahiye"


def test_app_lab_is_never_merged_into_the_evidence_tab():
    tabs = _js_tab_sections(_script())
    assert tabs["lab"] == ["original_lab"]
    assert "original_lab" not in tabs["evidence"]
    assert "original_lab" not in tabs["answer"]


# --- §22: baarah stage, hamesha ---------------------------------------------

def test_js_stage_list_mirrors_progress_tracker():
    script = _script()
    assert _js_stages(script) == list(STAGES)
    labels = re.search(r"const STAGE_LABEL=\{(.*?)\};", script, re.S)
    assert labels
    for stage in STAGES:
        assert re.search(r"\b%s:" % re.escape(stage), labels.group(1)), stage


def test_progress_panel_always_draws_one_row_per_stage():
    body = _body("stageTable")
    assert "STAGES.map(" in body, "12 row hamesha STAGES se banni chahiye"
    assert "slice" not in body, "stage list kaat kar chhoti nahi ki ja sakti"


def test_unrecorded_stage_is_honest_not_silently_pending():
    body = _body("stageTable")
    assert "log ki sirf aakhri lines" in body      # trim hua -> pata nahi
    assert "ye stage chala hi nahi" in body        # run poora hua -> chala nahi
    assert "Abhi baaki hai" in body                # run chal rahi hai -> baaki


def test_process_record_survives_after_the_answer_is_painted():
    script = _script()
    render = _body("renderResearch", script)
    assert "processHtml(data)" in render, "job khatam hone par process ud jaata tha"
    process = _body("processHtml", script)
    assert "research_progress" in process
    assert "stageRowsHtml(p)" in process


def test_missing_snapshot_says_so_instead_of_showing_an_empty_panel():
    process = _body("processHtml")
    assert 'p.available!==true' in process
    assert "snapshot nahi aaya" in process


def test_removed_progress_renderer_has_no_dead_callers():
    assert "appendResearchProcess" not in _html()


def test_counters_are_labelled_and_never_called_evidence():
    body = _body("progressCounts")
    for part in ("sources", "documents", "full-text", "conflicts checked",
                 "reasoning calls"):
        assert part in body, part
    assert "evidence strength" not in body.lower()


# --- §22 recovery contract ---------------------------------------------------

def test_recovery_banner_is_built_exactly_once():
    script = _script()
    render = _body("renderResearch", script)
    assert render.count("recoveryHtml(") == 1
    assert _body("recoveryHtml", script).count('class="recov"') == 1


def test_recovery_is_never_presented_as_stronger_evidence():
    body = _body("recoveryHtml")
    assert "Recovery se evidence mazboot nahi hota" in body
    assert "recovery_used" in body and "recovered" in body


def test_duplicate_paragraphs_collapse_so_the_footer_prints_once():
    script = _script()
    assert "dedupeParas(" in _body("renderResearch", script)
    body = _body("dedupeParas", script)
    assert "new Set()" in body and "split(/\\n{2,}/)" in body


def test_warnings_are_deduped_in_the_audit_tab():
    body = _body("auditHtml")
    assert "!warn.includes(String(w))" in body


# --- §20 UI side: chaar state, koi guess nahi -------------------------------

def test_state_bar_reads_all_four_fields_by_name():
    body = _body("stateBarHtml")
    for field in ("job_status", "answer_state", "evidence_state", "novelty_state"):
        assert field in body, field
    assert "Job poora hona ≠ jawab poora hona" in body
    assert "conflicts" in body


def test_missing_state_record_is_reported_not_invented():
    body = _body("stateBarHtml")
    assert "record nahi mila" in body
    assert "khud se koi state guess nahi karta" in body


def test_absent_claim_check_is_not_read_as_a_clean_bill():
    body = _body("claimsHtml")
    assert "check chala hi nahi" in body
    assert "kuch galat nahi mila" in body


def test_absent_counter_search_is_not_read_as_no_contradiction():
    body = _body("contraHtml")
    assert "counter_search_performed" in body
    assert "dhoonda hi nahi" in body
    assert "chali ya nahi, pata nahi" in body


def test_hypothesis_card_keeps_novelty_tri_state_and_the_disclaimer():
    body = _body("labHtml")
    assert "novelty_search" in body
    for word in ('"chali"', '"nahi chali"', '"record nahi"'):
        assert word in body, word
    assert "established fact nahi" in body
    assert "Patle evidence par hypothesis banana jaan-boojh kar mana hai" in body


def test_source_card_shows_read_depth_and_the_patent_warning():
    body = _body("sourcesHtml")
    assert "access_depth" in body and "access_depth_note" in body
    assert "patent_evidence_note" in body
    assert "Kitna padha" in body


def test_answer_text_is_escaped_before_it_reaches_the_page():
    script = _script()
    assert "function esc(" in script and "function htmlText(" in script
    assert "esc(s).split" in script, "htmlText escape ke baad hi split kare"
    assert "rich(" in _body("sectionHtml", script)


def test_no_credential_names_or_values_are_printed_by_the_ui():
    page = _html()
    for marker in ("GEMINI_API_KEY", "USPTO_ODP_API_KEY", "api_key",
                   "Authorization", "Bearer "):
        assert marker not in page, marker


def main() -> int:
    failed = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_") or not callable(func):
            continue
        try:
            func()
        except AssertionError as exc:                  # noqa: PERF203
            failed += 1
            print("  [FAIL] %s -> %s" % (name, exc))
        except Exception as exc:                       # noqa: BLE001
            failed += 1
            print("  [ERROR] %s -> %s: %s" % (name, type(exc).__name__, exc))
        else:
            print("  [PASS] %s" % name)
    print("\n%s — %d failed" % ("FAIL" if failed else "ok", failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
