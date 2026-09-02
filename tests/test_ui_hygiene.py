"""#113 — UI ki gandagi ke khilaaf naap (Claude-owned).

Paanch asli defect jo shipped screen par dikh rahe the, aur unka naap:

1. `[object Object]` — backend ki kai list dict ki list hoti hai (contract ledger
   ka `mandatory_missing`, contradiction ke `sources`, claim ke `cited_ids`).
   Seedha `Array.join` karne par browser "[object Object]" chhaap deta tha.
2. Answer ke text mein `[Title](https://…)` aur khule URL sirf escape hote the,
   isliye click hi nahi hote the — "Sources" section toota dikhta tha.
3. "PARTIAL" ek hi screen par 5 baar chhap raha tha (state bar + neeche ki note +
   audit ki do line), jisse lagta tha kai alag cheezein PARTIAL hain.
4. `requested.py` ki line "ye floor abhi provisional hai (provisional)" — ek hi
   shabd do baar, asli wajah gayab.
5. Sirf punctuation wale source title ("—", "***") naam ki jagah chhap rahe the.

Do tarah ke test yahan hain:

* STATIC — shipped `web/index.html` ki poori line (indentation ke saath) pin ki
  gayi hai. Sirf naam pin karna kaafi nahi hota: pichhli baar substring pin
  `if False and …` mutant se bach gaya tha.
* BEHAVIOUR — shipped HTML ke `<script>` block asli mein **node** se chalte hain
  (DOM ka chhota stub), aur render kiya hua HTML naapa jaata hai. Isse "function
  maujood hai" aur "function sach mein sahi kaam karta hai" alag ginte hain.

Node na mile to ye behaviour test **SKIP** hote hain (pytest ke saath) ya saaf
awaaz mein FAIL (bina pytest wale runner mein) — chup-chaap pass kabhi nahi,
warna "test chala hi nahi" aur "test pass hua" ek jaise dikhne lagte hain.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web", "index.html")
NODE = shutil.which("node") or shutil.which("nodejs")

# DOM ka utna hi stub jitna shipped script ke top-level code ko chahiye.
_STUB = """
const location={origin:"https://rv.example"};
function EL(){return {classList:{add(){},toggle(){},remove(){},contains:()=>false},
  style:{},dataset:{},value:"",disabled:false,title:"",textContent:"",
  scrollTop:0,scrollHeight:0,innerHTML:"",
  addEventListener(){},removeEventListener(){},appendChild(){},remove(){},
  focus(){},closest:()=>null,contains:()=>false,
  querySelector:()=>EL(),querySelectorAll:()=>[]};}
const document={querySelector:()=>EL(),querySelectorAll:()=>[],
  createElement:()=>EL(),addEventListener(){},body:EL(),documentElement:EL()};
const window={addEventListener(){},location:location};
const localStorage={getItem:()=>null,setItem(){},removeItem(){}};
const fetch=async()=>({ok:false,status:0,json:async()=>({})});
const setTimeout=(fn)=>0, setInterval=()=>0, clearInterval=()=>0,
  clearTimeout=()=>0;
"""


def _html() -> str:
    with open(WEB, "r", encoding="utf-8") as handle:
        return handle.read()


def _scripts() -> str:
    """Shipped page ke saare `<script>` block ka JS (yahi browser chalata hai)."""
    return "\n".join(m.group(1) for m in
                     re.finditer(r"<script[^>]*>([\s\S]*?)</script>", _html()))


def _need_node() -> None:
    """Node na ho to SKIP (pytest) ya saaf FAIL — chup-chaap pass nahi."""
    if NODE:
        return
    try:
        import pytest  # noqa: PLC0415
    except ModuleNotFoundError:
        raise RuntimeError(
            "node nahi mila, isliye shipped UI ka behaviour test CHALA HI NAHI. "
            "Ye pass nahi hai — node install karke dobara chalao.") from None
    pytest.skip("node nahi mila — shipped UI ka behaviour test nahi chal sakta")


def _js(exprs, payload=None):
    """`exprs` ke naam->JS expression ko shipped page ke andar chalao.

    Lautata hai naam->string. Payload `PAY` naam se JS mein pahunchta hai.
    """
    _need_node()
    lines = ["const PAY=" + json.dumps(payload if payload is not None else {}) + ";"]
    lines.append("const OUT={};")
    for name, code in exprs.items():
        lines.append("OUT[" + json.dumps(name) + "]=String(" + code + ");")
    lines.append("process.stdout.write(JSON.stringify(OUT));")
    program = _STUB + "\n" + _scripts() + "\n" + "\n".join(lines) + "\n"
    folder = tempfile.mkdtemp(prefix="ui_hygiene_")
    path = os.path.join(folder, "run.js")
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(program)
        done = subprocess.run([NODE, path], capture_output=True, text=True,
                             timeout=90)
        assert done.returncode == 0, ("shipped UI ka JS node par chala nahi: "
                                     + (done.stderr or "").strip()[-800:])
        return json.loads(done.stdout)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _count(text: str, needle: str) -> int:
    return len(re.findall(re.escape(needle), text))


# ── STATIC: shipped page ki poori line pin ───────────────────────────────────

def test_label_helpers_read_backend_field_names_not_object_tostring():
    text = _html()
    assert 'const LABEL_KEYS=["what","key","label","title","name","id","reason","note","query"];' in text
    assert ('  for(const k of LABEL_KEYS){const v=item[k];if(v!==null&&v!==undefined'
            '&&typeof v!=="object"&&String(v).trim())return String(v).trim();}') in text
    # Naam na mile to record ka JSON — "[object Object]" kabhi nahi.
    assert '  try{const j=JSON.stringify(item);return (j&&j!=="{}"&&j!=="[]")?j.slice(0,160):"";}catch(_){return "";}' in text
    assert "function joinLabels(list,limit){return labelList(list,limit).join(\", \");}" in text


def test_dict_lists_go_through_joinlabels_and_never_raw_join():
    text = _html()
    assert 'esc(joinLabels(c.cited_ids,20))' in text
    assert 'Sources: \'+esc(joinLabels(c.sources,20))' in text
    assert '" (missing: "+joinLabels(led.mandatory_missing)+")"' in text
    assert 'Gate repairs: "+joinLabels(data.quality_repairs)' in text
    # Regression target: seedha join hi "[object Object]" banata tha.
    for banned in ("c.cited_ids.join", "c.sources.join",
                   "led.mandatory_missing.join", "data.quality_repairs.join"):
        assert banned not in text, banned


def test_linkify_is_one_pass_and_validates_scheme_after_unescaping():
    text = _html()
    assert (r"""const LINK_RE=/\[([^\]\n<>]{1,200})\]\((https?:\/\/[^\s<>"')]{1,600})\)|(https?:\/\/[^\s<>"')]{1,600})/g;""") in text
    assert (r"""function anchorHtml(labelHtml,escapedUrl){const raw=unesc(escapedUrl);if(/["'\s<>]/.test(raw))return "";const href=safeHttpUrl(raw);""") in text
    assert 'function linkify(html){return String(html??"").replace(LINK_RE,(whole,label,mdUrl,bare)=>{' in text
    assert '  if(mdUrl){const md=anchorHtml(label,mdUrl);return md||whole;}' in text
    assert '  const raw=String(bare||""),clean=raw.replace(/[.,;:!?]+$/,""),tail=raw.slice(clean.length);' in text
    assert 'function rich(text){return linkify(htmlText(text)' in text


def test_unesc_decodes_amp_last_so_double_escaping_cannot_smuggle_a_tag():
    line = [ln for ln in _html().splitlines() if ln.startswith("function unesc(")]
    assert len(line) == 1, "unesc ek hi jagah honi chahiye"
    body = line[0]
    # `&amp;` sabse aakhir mein — warna "&amp;lt;" decode hoke "<" ban jaata.
    assert body.index("&lt;") < body.index("&amp;")
    assert body.index("&quot;") < body.index("&amp;")
    assert body.index("&#39;") < body.index("&amp;")


def test_source_title_and_status_note_are_wired_into_render():
    text = _html()
    assert r'function hasWordChar(s){return /[\p{L}\p{N}]/u.test(String(s??""));}' in text
    assert 'function sourceTitle(s){const t=String((s&&s.title)||"").trim();if(hasWordChar(t))return t;' in text
    assert '  const u=safeHttpUrl((s&&s.url)||"");return hasWordChar(u)?u:"Source";}' in text
    # Kram: scheme check pehle (safeHttpUrl), escape uske baad.
    assert 'const href=safeHttpUrl(s.url),url=href?esc(href):"",title=esc(sourceTitle(s))' in text
    assert '  const sNote=statusNote(data);if(sNote)note(el,sNote);' in text


def test_audit_merges_equal_status_and_ledger_into_one_named_line():
    text = _html()
    assert ('  if(status&&ledState&&status.toUpperCase()===ledState.toUpperCase())'
            'bits.push("Run status + contract ledger: "+status+why+missing);') in text
    assert ('  else{if(status)bits.push("Run status: "+status+why);'
            'if(ledState)bits.push("Contract ledger: "+ledState+missing);}') in text


# ── BEHAVIOUR: shipped script asli mein chalta hai (node), phir HTML naapte hain ─

def _partial_payload():
    """Ek asli-jaisa PARTIAL result: dict wali list, punctuation title, links."""
    return {
        "status": "PARTIAL",
        "status_reason": "zaroori section adhoora raha",
        "evidence_level": "UNCONFIRMED",
        "answer": "## SOURCES\n- [Nature retraction](https://www.nature.com/articles/x)"
                  "\n- https://arxiv.org/abs/2305.15423\n",
        "contract_ledger": {
            "result_state": "PARTIAL",
            "mandatory_missing": [
                {"key": "average_relevance", "what": "Average relevance ≥ 0.65",
                 "got": "0.31", "ok": False, "mandatory": True},
                {"key": "evidence_axes", "what": "Evidence axes covered",
                 "got": "2/6", "ok": False, "mandatory": True},
            ],
        },
        "quality_gate": {"verified_allowed": False},
        "quality_repairs": ["answer_status_downgraded_to_partial"],
        "research_state": {
            "job_status": "FINISHED", "answer_state": "PARTIAL",
            "evidence_state": "WEAK", "novelty_state": "NOVELTY UNVERIFIED",
            "reasons": {"answer_state": "zaroori section adhoora raha"},
        },
        "contradictions": [{"type": "numeric", "severity": "high",
                            "summary": "Tc 294 K vs 250 K",
                            "sources": [{"id": "S1", "title": "Nature 2023"},
                                        {"id": "S2", "title": "arXiv preprint"}]}],
        "verification": {"claim_checks": {"claims": [
            {"result": "PARTIALLY SUPPORTED", "claim": "Tc 294 K par dawa",
             "cited_ids": [{"id": "S1"}, "S2"]}]}},
        "sources": [
            {"title": "—", "url": "https://www.nature.com/articles/x",
             "access_depth": "full text"},
            {"title": "mera-note.pdf", "url": "", "source_type": "document",
             "connector": "user_pdf"},
            {"title": "***", "url": "javascript:alert(1)"},
        ],
        "warnings": [],
    }


def test_dict_lists_render_readable_labels_not_object_object():
    out = _js({
        "audit": "auditHtml(splitAnswer(PAY.answer||''),PAY)",
        "contra": "contraHtml(PAY)",
        "claims": "claimsHtml(PAY)",
    }, _partial_payload())
    joined = "".join(out.values())
    assert "[object Object]" not in joined
    assert "Average relevance ≥ 0.65" in out["audit"]
    assert "Evidence axes covered" in out["audit"]
    assert "Sources: Nature 2023, arXiv preprint" in out["contra"]
    assert "Cited: S1, S2" in out["claims"]


def test_answer_links_become_clickable_anchors_without_leaving_markdown_junk():
    out = _js({"src": "sourcesHtml(splitAnswer(PAY.answer||''),PAY)"},
              _partial_payload())
    html = out["src"]
    assert '<a target="_blank" rel="noopener noreferrer nofollow" ' \
           'href="https://www.nature.com/articles/x">Nature retraction</a>' in html
    assert "](http" not in html, "markdown ka kachra screen par nahi rehna chahiye"
    assert 'href="https://arxiv.org/abs/2305.15423"' in html


def test_unsafe_schemes_and_injection_attempts_never_become_anchors():
    """Sirf http/https anchor bante hain; baaki inert text rehte hain."""
    sample = ('[bad](javascript:alert(1)) [d](data:text/html,<script>alert(1)</script>) '
              '[q](https://a.com/x" onmouseover="alert(1)) <img src=x onerror=alert(1)>')
    out = _js({"r": "rich(PAY.s)"}, {"s": sample})
    html = out["r"]
    # javascript:/data: waale markdown link jaise the waise hi text mein pade
    # rehte hain — anchor nahi bante (link "kaam nahi kar raha" dikhna hi sach hai).
    assert 'href="javascript:' not in html
    assert 'href="data:' not in html
    assert "[bad](javascript:alert(1))" in html
    assert "[d](data:text/html," in html
    # Tag aur attribute injection escape hoke text ban jaate hain.
    assert "<script" not in html
    assert "<img" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert 'onmouseover="' not in html
    # Quote wali koshish se sirf ek (bekaar par be-zarar) anchor banta hai.
    assert _count(html, "<a ") == 1, html


def test_linkify_never_nests_an_anchor_inside_another():
    sample = "[https://a.org/x](https://b.org/y) aur https://c.org/z"
    out = _js({"r": "rich(PAY.s)"}, {"s": sample})
    html = out["r"]
    assert _count(html, "<a ") == 2, html
    assert _count(html, "</a>") == 2, html
    assert "<a " not in html[html.index("<a ") + 3:html.index("</a>")]
    assert 'href="https://b.org/y">https://a.org/x</a>' in html


def test_bare_url_keeps_trailing_punctuation_outside_the_link():
    out = _js({"r": "rich(PAY.s)"},
              {"s": "dekho https://a.org/p. aur (https://b.org/q) bas."})
    html = out["r"]
    assert 'href="https://a.org/p"' in html
    assert "https://a.org/p</a>." in html
    assert 'href="https://b.org/q"' in html
    assert "https://b.org/q</a>)" in html


def test_long_label_lists_say_how_many_were_hidden():
    """Cap lagti hai to ginti bolti hai — chup-chaap kaat dena jhooth hai."""
    items = [{"what": "item-" + str(n)} for n in range(11)]
    out = _js({"j": "joinLabels(PAY.items,3)", "k": "joinLabels(PAY.items,20)"},
              {"items": items})
    assert out["j"] == "item-0, item-1, item-2, +8 aur", out["j"]
    assert out["k"].endswith("item-10")
    assert " aur" not in out["k"]


def test_quote_carrying_url_is_refused_but_a_normal_query_url_still_links():
    """Guard sirf khatre ko rokta hai, kaam ke link ko nahi (app kamzor nahi hua)."""
    bad = _js({"r": "rich(PAY.s)"}, {"s": '[t](https://a.org/b"onmouseover=x) end'})
    assert "<a " not in bad["r"]
    assert "&quot;onmouseover=x" in bad["r"]
    good = _js({"r": "rich(PAY.s)"}, {"s": "[t](https://a.org/b?q=1&c=2) end"})
    assert 'href="https://a.org/b?q=1&amp;c=2">t</a>' in good["r"]


def test_punctuation_only_titles_fall_back_and_unsafe_urls_stay_unlinked():
    payload = {"sources": [
        {"title": "—", "url": "https://ok.org/a", "access_depth": "full text"},
        {"title": "***", "url": "javascript:alert(1)"},
        {"title": "  ", "url": ""},
        {"title": "Nature 2023", "url": "https://ok.org/b"},
    ], "answer": ""}
    out = _js({"src": "sourcesHtml(splitAnswer(PAY.answer||''),PAY)"}, payload)
    html = out["src"]
    # "—" naam nahi hai: saaf URL dikhti hai (aur wahi anchor bhi hai).
    assert '<a target="_blank" rel="noopener noreferrer nofollow" ' \
           'href="https://ok.org/a">https://ok.org/a</a>' in html
    # "***" + javascript: — na naam, na anchor. Sirf imaandaar "Source".
    assert "<strong>Source</strong>" in html
    assert _count(html, "<strong>Source</strong>") == 2
    assert "javascript:" not in html
    assert "***" not in html
    assert "<strong>Nature 2023</strong>" in html or ">Nature 2023</a>" in html
    assert "[object Object]" not in html


def test_user_supplied_document_never_gets_a_link_even_if_payload_has_a_url():
    payload = {"sources": [{"title": "mera-note.pdf", "url": "https://x.org/leak",
                            "source_type": "document", "connector": "user_pdf"}],
               "answer": ""}
    out = _js({"src": "sourcesHtml(splitAnswer(PAY.answer||''),PAY)"}, payload)
    html = out["src"]
    assert "<strong>mera-note.pdf</strong>" in html
    assert "<a " not in html
    assert "https://x.org/leak" not in html
    assert "Tumhara diya document" in html


def test_status_note_stays_quiet_when_state_bar_already_says_the_same_thing():
    """Defect 3: PARTIAL ek hi screen par baar-baar na chhape."""
    same = _partial_payload()
    out = _js({"note": "statusNote(PAY)", "bar": "stateBarHtml(PAY.research_state)"},
              same)
    assert out["note"] == "", out["note"]
    # Chhupaya nahi: wahi baat state bar mein apni wajah ke saath maujood hai.
    assert "PARTIAL" in out["bar"]
    assert "zaroori section adhoora raha" in out["bar"]


def test_status_note_speaks_when_reason_or_label_is_actually_different():
    """Ulta rasta: farq ho to note dabti nahi (chuppi = jaankari ka nuksaan)."""
    other_reason = _partial_payload()
    other_reason["status_reason"] = "search budget khatam ho gaya"
    out = _js({"note": "statusNote(PAY)"}, other_reason)
    assert out["note"] == "Run status: PARTIAL — search budget khatam ho gaya"

    other_label = _partial_payload()
    other_label["research_state"]["answer_state"] = "COMPLETE"
    out2 = _js({"note": "statusNote(PAY)"}, other_label)
    assert out2["note"].startswith("Run status: PARTIAL")

    no_state = _partial_payload()
    no_state.pop("research_state")
    out3 = _js({"note": "statusNote(PAY)"}, no_state)
    assert out3["note"].startswith("Run status: PARTIAL")

    complete = _partial_payload()
    complete["status"] = "COMPLETE"
    out4 = _js({"note": "statusNote(PAY)"}, complete)
    assert out4["note"] == ""


def test_audit_says_both_names_once_when_status_and_ledger_agree():
    out = _js({"audit": "auditHtml(splitAnswer(PAY.answer||''),PAY)",
               "note": "statusNote(PAY)",
               "bar": "stateBarHtml(PAY.research_state)"}, _partial_payload())
    audit = out["audit"]
    assert "Run status + contract ledger: PARTIAL" in audit
    # Ek hi line — par dono naap ke naam usi line par (farq chhupa nahi).
    assert _count(audit, "Run status") == 1
    assert "contract ledger" in audit
    assert _count(audit, "PARTIAL") == 1, audit
    # Poore screen par PARTIAL ki ginti: audit 1 + state bar 1. Pehle 5 thi.
    assert _count(audit + out["note"] + out["bar"], "PARTIAL") == 2


def test_audit_keeps_two_lines_when_status_and_ledger_disagree():
    """Ulta rasta: barabar na hon to merge nahi — warna asli farq gayab ho jaata."""
    split = _partial_payload()
    split["contract_ledger"]["result_state"] = "INSUFFICIENT_EVIDENCE"
    out = _js({"audit": "auditHtml(splitAnswer(PAY.answer||''),PAY)"}, split)
    audit = out["audit"]
    assert "Run status + contract ledger" not in audit
    assert "Run status: PARTIAL — zaroori section adhoora raha" in audit
    assert "Contract ledger: INSUFFICIENT_EVIDENCE" in audit
    assert "Average relevance ≥ 0.65" in audit


def test_shipped_page_keeps_its_earlier_link_safety_locks():
    """#113 ke chakkar mein pehle ke jeete hue taale toote nahi — kuch hataya nahi."""
    text = _html()
    assert "function safeHttpUrl" in text
    assert 'u.protocol==="http:"||u.protocol==="https:"' in text
    assert "href=safeHttpUrl(s.url)" in text
    assert 'url=href?esc(href):""' in text
    assert 'rel="noopener noreferrer nofollow"' in text
    assert "function htmlText(s){return esc(s)" in text
    assert "function answer(el,text){el.innerHTML=htmlText(text)" in text


# ── BACKEND: floor ka status do baar na chhape (defect 4) ────────────────────

def test_relevance_floor_note_gives_the_reason_not_the_word_again():
    from research_engine import requested

    note = requested.relevance_floor_note()
    assert note, "floor ki wajah gayab nahi honi chahiye"
    assert note != "provisional"
    assert "provisional" not in note.lower()
    assert "calibrate" in note.lower()
    # Poora status wahi rehta hai (contract mein jaata hai) — sirf report ki
    # line badli hai.
    assert requested.MIN_AVERAGE_RELEVANCE_STATUS.startswith("provisional")
    assert note in requested.MIN_AVERAGE_RELEVANCE_STATUS


def test_ledger_line_never_says_provisional_twice():
    from research_engine import requested

    led = requested.contract_ledger({"minimum_average_relevance": 0.65},
                                    {"average_relevance": 0.31})
    items = [i for i in led.get("items", [])
             if i.get("key") == "average_relevance"]
    assert len(items) == 1, led.get("items")
    why = str(items[0].get("why") or "")
    assert why.startswith("0.31 < 0.65")
    assert why.lower().count("provisional") == 1, why
    assert "(provisional)" not in why
    assert requested.relevance_floor_note() in why
    # Ledger ka faisla kamzor nahi hua: floor toota to item fail hi rehta hai.
    assert items[0].get("ok") is False
    assert items[0].get("mandatory") is True
    assert any(i.get("key") == "average_relevance"
               for i in led.get("mandatory_missing", []))


def test_floor_note_survives_a_status_without_an_em_dash():
    """Em-dash na ho to poora text jaata hai — wajah chupti nahi."""
    from research_engine import requested

    original = requested.MIN_AVERAGE_RELEVANCE_STATUS
    try:
        requested.MIN_AVERAGE_RELEVANCE_STATUS = "abhi calibrate nahi hua"
        assert requested.relevance_floor_note() == "abhi calibrate nahi hua"
    finally:
        requested.MIN_AVERAGE_RELEVANCE_STATUS = original
    assert requested.relevance_floor_note() in original




