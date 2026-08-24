"""User ke apne document (local PDF / paste kiya explanation) ka poora contract.

Kahaan se aaya ye kaam: copyright book ki poori copy internet se nahi laayi ja
sakti, par agar user ke paas us book ka PDF, notes ya explanation PEHLE SE hai,
to research usko padhni chahiye — "ignore" nahi karna. Iske do hisse hain, aur
dono ka jhooth bolna aasaan hai:

  A. WEBSITE — file dene ka control asli endpoint par jaye, usi private session
     mein jaye jisme sawaal jaata hai, capability kabhi URL/localStorage mein na
     jaye, aur "process ho gayi par text nahi mila" ko success na kaha jaye.

  B. IMAANDAARI — user ke apne document CORROBORATION nahi hain. Ek hi book ke
     teen scan, ya summary + apne notes, "teen alag jagah" nahi hote. Unko
     PADHNA sach hai (aur wo answer mein poore label ke saath aate hain), par
     unse "VERIFIED" ya "sab sources sehmat hain" nahi banta.

Yahi (B) wala asli defect tha jo ye batch mein pakda gaya: purana
`deserves_strong = ((scholarly >= 2 or docs >= 2) and independent >= 3)` ka
matlab tha ki user khud teen file upload kar de to report "✅ STRONG" chhaap
deti, bina ek bhi bahari source ke — aur consensus gate unhi teen files ko
"3 independent origin" gin leta. Neeche ke test dono raaste band rakhte hain,
aur saath hi ye bhi saabit karte hain ki ACHHA evidence abhi bhi top label paa
sakta hai (warna hum bug ko "hamesha MIXED" se badal dete).

Koi network, koi Gemini, koi API key, koi fastapi import nahi — backend route ka
contract bhi file padh kar check hota hai, import karke nahi.

Chalao:  PYTHONPATH=. python3 tests/run_pytest_style_suites.py tests/test_user_documents.py
"""
from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_engine import consensus_gate                       # noqa: E402
from research_engine.citation import CitationEngine              # noqa: E402
from research_engine.evidence import EvidenceEngine              # noqa: E402
from research_engine.models import SourceRecord, SourceType       # noqa: E402

WEB = ROOT / "web" / "index.html"
ROUTES = ROOT / "api" / "routes.py"

QUESTION = "geeta ke karm-yog par kya likha hai aur usko aaj kaise samjha jaye"


def _web() -> str:
    return WEB.read_text(encoding="utf-8")


def _upload_js(text: str) -> str:
    """Sirf upload wala hissa — taaki baaki page ke literals se dhoka na ho."""
    start = text.index("async function uploadDoc")
    end = text.index('attach.addEventListener("click"', start)
    return text[start:end]


def _render_js(text: str) -> str:
    start = text.index("function sourcesHtml")
    end = text.index("async function submit", start)
    return text[start:end]


def _doc(name: str, page: int, body: str) -> SourceRecord:
    """Waisa hi record jaisa `EvidenceEngine.records_from_retrieval()` banata hai."""
    return SourceRecord(
        title=name, url="", snippet=body, connector="user_pdf",
        source_type=SourceType.DOCUMENT, locator=f"Page {page}",
        full_text_available=True, read_level="full_text",
    )


def _paper(title: str, url: str, doi: str, body: str) -> SourceRecord:
    return SourceRecord(title=title, url=url, snippet=body, connector="openalex",
                        source_type=SourceType.PAPER, doi=doi, peer_reviewed=True,
                        year=2024)


_LONG = ("karm-yog ka arth ye bataya gaya hai ki phal ki icchha chhod kar apna "
         "karm karo; yahi baat is hisse mein vistaar se samjhayi gayi hai aur "
         "iske saath uska sandarbh bhi diya gaya hai. ")

USER_DOCS = [
    _doc("geeta-explanation.pdf", 12, _LONG + "Pehli file ka hissa."),
    _doc("geeta-notes.txt", 1, _LONG + "Doosri file ka hissa."),
    _doc("geeta-summary.pdf", 4, _LONG + "Teesri file ka hissa."),
]

EXTERNAL = [
    _paper("Karma yoga in the Bhagavadgita: a philological study",
           "https://openalex.org/W101", "10.1/karma", _LONG + "Journal paper."),
    _paper("Detachment and action: comparative ethics of the Gita",
           "https://www.cambridge.org/core/article/gita-ethics", "10.1/ethics",
           _LONG + "University press chapter."),
    _paper("Reception history of the Gita in modern commentary",
           "https://openalex.org/W102", "10.1/reception", _LONG + "Review."),
]


def _pack(sources, planned: int = 3, done: int = 3, queries=None):
    """Ek pack jisme SIRF wahi gate baaki rahe jise test dekhna chahta hai.

    relevance/full-text/reasoning ke apne alag test hain
    (`tests/test_evidence_honesty.py`), isliye unhe yahan jaan-boojh kar pass
    kara diya jaata hai — warna doc-only pack pehle hi kisi doosri wajah se ruk
    jaata aur ye test us wajah ko galti se "apni jeet" samajh leta.
    """
    engine = EvidenceEngine()
    picked = [copy.deepcopy(s) for s in sources]
    docs = [s for s in picked if s.source_type == SourceType.DOCUMENT]
    outside = [s for s in picked if s.source_type != SourceType.DOCUMENT]
    pack = engine.build_pack(QUESTION, docs, outside,
                            max_sources=12, queries=list(queries or []))
    for s in pack.sources:
        s.relevance_score = 0.62
        if s.source_type != SourceType.DOCUMENT:
            s.full_text_chars = 5000
    pack.reasoning_planned = planned
    pack.reasoning_done = done
    return engine, pack


# ── A. WEBSITE ka contract (static, browser ke bina) ─────────────────────────
def test_website_has_a_control_to_give_your_own_documents():
    text = _web()
    assert 'id="attach"' in text, "📎 control hi nahi hai"
    assert 'id="fileinput"' in text and 'type="file"' in text
    assert 'id="pastebox"' in text, "explanation paste karne ka raasta nahi hai"
    assert 'id="doclist"' in text, "di hui files ka status kahin dikhta nahi"
    assert "multiple" in text[text.index('id="fileinput"') - 40:
                              text.index('id="fileinput"') + 200]


def test_upload_goes_to_the_real_backend_endpoint():
    js = _upload_js(_web())
    assert "/api/v1/upload-document" in js
    assert 'method:"POST"' in js
    assert "new FormData()" in js and "body:fd" in js


def test_upload_uses_the_same_private_session_as_the_question():
    """Alag session = orchestrator._document_records() ko file milegi hi nahi."""
    js = _upload_js(_web())
    assert "await ensureSession()" in js
    assert 'fd.append("project_id",PROJECT.id)' in js
    # 404 (session expire) par ek baar naya session bana kar dobara koshish
    assert "resetProjectSession()" in js


def test_upload_sends_only_the_capability_header():
    """FormData par Content-Type khud lagana boundary tod deta hai."""
    js = _upload_js(_web())
    assert '{"X-Project-Token":PROJECT.token}' in js
    assert "projectHeaders" not in js, "FormData ke saath JSON headers nahi bhejne"
    assert "Content-Type" not in js


def test_capability_token_never_travels_in_a_url_or_browser_storage():
    low = _web().lower()
    assert "upload-document?" not in low
    for banned in ("x-project-token=", "project_token=", "project_access_token=",
                   "localstorage", "sessionstorage"):
        assert banned not in low, f"capability leak: {banned}"


def test_client_side_limits_match_the_backend_exactly():
    """Client apna alag rule bana le to user ko jhoothi 'ok'/'na' milegi."""
    web = _web()
    routes = ROUTES.read_text(encoding="utf-8")

    listed = re.search(r"const DOC_EXT=\[(.*?)\];", web)
    assert listed, "DOC_EXT list nahi mili"
    client_ext = re.findall(r'"(\.[a-z0-9]+)"', listed.group(1))

    block = re.search(r"SUPPORTED = \((.*?)\)", routes, re.S)
    assert block, "backend SUPPORTED tuple nahi mila"
    backend_ext = re.findall(r'"(\.[a-z0-9]+)"', block.group(1))

    assert client_ext == backend_ext, (client_ext, backend_ext)
    assert "const MAX_DOC_BYTES=60*1024*1024;" in web
    assert "MAX_UPLOAD_BYTES = 60 * 1024 * 1024" in routes


def test_unusable_files_are_refused_before_the_network_call():
    js = _upload_js(_web())
    assert "DOC_EXT.includes(docExt(name))" in js
    assert "if(!blob.size)" in js
    assert "blob.size>MAX_DOC_BYTES" in js


def test_zero_chunk_upload_is_reported_as_failure_not_success():
    """Scan-only PDF: HTTP 200 aata hai par padhne layak text zero hota hai."""
    js = _upload_js(_web())
    assert "const chunks=Number(data.chunks||0);" in js
    assert "if(!chunks){entry.bad=true;" in js
    assert "Research isko source nahi banayegi" in js
    # success wali line chunk count ke BAAD hi aati hai
    assert js.index("if(!chunks)") < js.index("entry.ready=true")


def test_uploads_go_one_at_a_time():
    """20 uploads/hour ka limit hai; ek saath 10 file bhejna use phaad deta hai."""
    js = _web()
    many = js[js.index("async function uploadMany"):
              js.index('attach.addEventListener("click"')]
    assert "if(uploading" in many and "uploading=true" in many
    assert "for(const it of items)await uploadDoc" in many


def test_panel_note_is_honest_about_privacy_and_verified():
    note = _web()
    start = note.index('id="docnote"')
    line = note[start:note.index("</div>", start)]
    assert "private session" in line
    assert "koi public link nahi banta" in line
    assert "tumhara uploaded document" in line
    assert "VERIFIED nahi banata" in line
    assert "Page refresh" in line, "ephemeral session ki baat chhupi nahi honi chahiye"


def test_user_documents_are_labelled_and_never_rendered_as_links():
    render = _render_js(_web())
    assert 'const mine=String(s.source_type||"")==="document"' in render
    assert 'String(s.connector||"")==="user_pdf"' in render
    assert 'link=mine?"":url' in render
    assert '\'<a target="_blank" rel="noopener noreferrer nofollow" href="\'+link+\'">\'' \
        in render, "anchor ab bhi bina-check url use kar raha hai"
    assert "Tumhara diya document" in render
    assert 'Akela ye kisi baat ko VERIFIED ya "sab sehmat hain" nahi banata' in render


def test_file_mode_disables_giving_documents():
    tail = _web()
    block = tail[tail.index("if(IS_FILE){"):]
    assert "attach.disabled=true" in block
    assert 'document dena band hai' in block


# ── B. BACKEND: document sach mein source banta hai ──────────────────────────
def test_uploaded_pages_become_labelled_document_sources():
    """Ye chain live hai: retrieval context -> per-page SourceRecord -> pack."""
    engine = EvidenceEngine()
    context = ("[Source: geeta-explanation.pdf, Page 12]\n" + _LONG
               + "\n[Source: geeta-explanation.pdf, Page 13]\n" + _LONG)
    records = engine.records_from_retrieval(
        {"context": context, "sources": [{"file": "geeta-explanation.pdf"}]})
    assert len(records) == 2, [r.locator for r in records]
    for rec in records:
        assert rec.source_type == SourceType.DOCUMENT
        assert rec.connector == "user_pdf"
        assert rec.reading_level() == "full_text"
        assert "tumhara uploaded document" in rec.citation_label()
    assert [r.locator for r in records] == ["Page 12", "Page 13"]
    # Ek hi file ke do page do "independent origin" nahi hain
    assert len({r.independence_key for r in records}) == 1


def test_citation_payload_carries_the_flags_the_website_checks():
    """Website `source_type`/`connector` par label lagati hai — payload me hon."""
    row = CitationEngine._citation_dict(USER_DOCS[0])
    assert row["source_type"] == "document"
    assert row["connector"] == "user_pdf"
    assert row["file"] == "geeta-explanation.pdf"
    assert row["page"] == "12"
    assert not row["url"], "user ke document ka koi public URL nahi hota"


# ── C. IMAANDAARI: apni hi di hui copy se VERIFIED nahi ──────────────────────
def test_only_user_documents_can_never_be_verified_or_strong():
    """Asli defect: teen apni file "✅ STRONG" bana deti thi."""
    engine, pack = _pack(USER_DOCS)
    assert len(pack.document_sources()) == 3
    assert pack.independent_source_count == 3      # ginti ke hisaab se "kaafi"
    assert pack.full_text_read_count == 3          # padhna sach hai
    grade = engine.grade_evidence(pack)
    assert "VERIFIED" not in grade and "STRONG" not in grade, grade
    assert "MIXED" in grade, grade
    assert "bahari independent origin" in grade, grade
    assert "uploaded document" in grade, grade


def test_one_outside_source_is_still_not_enough():
    engine, pack = _pack(USER_DOCS + EXTERNAL[:1])
    grade = engine.grade_evidence(pack)
    assert "VERIFIED" not in grade and "STRONG" not in grade, grade
    assert "bahari independent origin" in grade, grade


def test_documents_plus_outside_sources_can_still_reach_the_top_label():
    """Gate ko blanket 'hamesha MIXED' nahi banna chahiye."""
    engine, pack = _pack(USER_DOCS + EXTERNAL)
    grade = engine.grade_evidence(pack)
    assert "VERIFIED" in grade or "STRONG" in grade, grade
    assert "MIXED" not in grade, grade


def test_reason_is_shown_not_silently_downgraded():
    engine, pack = _pack(USER_DOCS)
    blocked = engine._honesty_gate(pack)
    assert blocked, "gate chup-chaap pass ho gaya"
    assert blocked in engine.grade_evidence(pack), "wajah user ko dikhni chahiye"


# ── D. CONSENSUS GATE ki aathvi shart ────────────────────────────────────────
_OPPOSITION_QUERY = "karma yoga interpretation criticism and contradictory readings"


def _consensus(sources):
    _, pack = _pack(sources, queries=[QUESTION, _OPPOSITION_QUERY])
    return consensus_gate.evaluate(pack, contradictions=[])


def test_user_documents_alone_cannot_open_the_consensus_gate():
    result = _consensus(USER_DOCS)
    names = [c["condition"] for c in result.checks]
    assert "sources_beyond_user_documents" in names
    assert not result.passed, result.to_dict()
    assert [c["condition"] for c in result.unmet] == \
        ["sources_beyond_user_documents"], result.to_dict()
    note = result.note()
    assert consensus_gate.CONSENSUS_UNAVAILABLE in note
    assert "khud ka uploaded document" in note, note


def test_outside_sources_satisfy_the_eighth_condition():
    result = _consensus(USER_DOCS + EXTERNAL)
    names = [c["condition"] for c in result.checks]
    assert "sources_beyond_user_documents" in names
    assert result.passed, result.to_dict()
    assert len(result.checks) == 7, names


def test_pack_without_user_documents_keeps_exactly_six_conditions():
    """Shart 8 sirf tab judti hai jab user ka document ho — warna nahi."""
    result = _consensus(EXTERNAL)
    names = [c["condition"] for c in result.checks]
    assert "sources_beyond_user_documents" not in names, names
    assert len(names) == 6, names
    assert result.passed, result.to_dict()


def test_document_split_does_not_guess_from_titles():
    docs, outside = consensus_gate._user_document_split(_pack(
        USER_DOCS + EXTERNAL)[1])
    assert {d.title for d in docs} == {s.title for s in USER_DOCS}
    assert {o.title for o in outside} == {s.title for s in EXTERNAL}
    assert consensus_gate.MIN_OUTSIDE_USER_DOCS == 3


def test_old_pack_objects_still_get_the_eighth_condition():
    """Purane run/fake pack ke paas `document_sources()` nahi hota.

    Us haalat mein bhi user ke document pehchaane jaane chahiye — warna gate
    sirf naye pack par lagta aur purana raasta chupke se khula reh jaata.
    """
    class _OldPack:                      # sirf `sources` — koi helper method nahi
        def __init__(self, rows):
            self.sources = list(rows)

    docs, outside = consensus_gate._user_document_split(
        _OldPack([copy.deepcopy(s) for s in USER_DOCS + EXTERNAL]))
    assert [d.title for d in docs] == [s.title for s in USER_DOCS], \
        "source_type se pehchaana hi nahi gaya"
    assert [o.title for o in outside] == [s.title for s in EXTERNAL]
