"""#120 — audio / video / YouTube / badi-kitaab lane ka naap (Claude-owned).

Ye lane website par tab tak nahi the jabki backend ke endpoint mahino se maujood
the. Sirf button laga dena kaafi nahi hota: teen jhooth aasani se ghus jaate hain
aur unke khilaaf yahan naap hai —

1. **"Chal jaayega" ka jhooth.** Server par local speech-to-text ya caption
   library na ho to button khula rakhna user se jhooth hai. Isliye teeno lane
   `GET /api/v1/processing-capabilities` ki asli list par khulte hain, aur band
   hone par server ki asli `needs` line dikhti hai.
2. **"Video dekh liya" ka jhooth.** Transcription sirf AUDIO ka hota hai. Koi
   frame, scene, chehra ya visual nahi padha jaata — ye baat har video lane par
   likhi rehni chahiye.
3. **"Kitaab padh li" ka jhooth.** Reading session bounded batch mein page
   dekhta hai; adhoori coverage ko poora dikhana mana hai. Jo ginti backend
   deta hai (page fraction, unreadable page, `completion_claim`) wahi screen par
   jaati hai.

Do tarah ke test:

* STATIC/CONTRACT — shipped `web/index.html` ki poori line pin ki gayi hai, aur
  client ki list/limit backend ke `ast` se nikaale gaye asli constant se milaayi
  jaati hai (do jagah alag ho jaana hi asli defect hota hai).
* BEHAVIOUR — shipped page ke `<script>` block asli mein **node** par chalte hain
  aur unka output naapa jaata hai. "Function maujood hai" aur "function sach
  bolta hai" alag ginte hain.

Node na mile to behaviour test **SKIP** (pytest ke saath) ya saaf FAIL — chup-chaap
pass kabhi nahi.
"""
from __future__ import annotations

import ast
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
ROUTES = os.path.join(ROOT, "api", "routes.py")
READING_ROUTES = os.path.join(ROOT, "api", "reading_routes.py")
READING_ENGINE = os.path.join(ROOT, "research_engine", "reading_sessions.py")
NODE = shutil.which("node") or shutil.which("nodejs")

# DOM ka utna hi stub jitna shipped script ke top-level code ko chahiye.
# (Jaan-boojh kar #113 wale harness jaisa — sandbox mein fastapi/pytest nahi hai,
# isliye ye file bilkul apne paon par khadi rehni chahiye.)
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
            "node nahi mila, isliye shipped media lane ka behaviour test CHALA "
            "HI NAHI. Ye pass nahi hai — node install karke dobara chalao."
        ) from None
    pytest.skip("node nahi mila — shipped UI ka behaviour test nahi chal sakta")


def _js(exprs, payload=None):
    """`exprs` ke naam->JS expression shipped page ke andar chalao."""
    _need_node()
    lines = ["const PAY=" + json.dumps(payload if payload is not None else {}) + ";"]
    lines.append("const OUT={};")
    for name, code in exprs.items():
        lines.append("OUT[" + json.dumps(name) + "]=String(" + code + ");")
    lines.append("process.stdout.write(JSON.stringify(OUT));")
    program = _STUB + "\n" + _scripts() + "\n" + "\n".join(lines) + "\n"
    folder = tempfile.mkdtemp(prefix="media_lanes_")
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


_TOP_LEVEL_RE = re.compile(r"^(?:async function|function|const) ", re.M)


def _fn(name: str) -> str:
    """Sirf `name` wale top-level function ka apna body.

    Ye helper mutation ne majboor kiya. Page-bhar ka `assert line in html` jhooth
    bol deta hai jab wahi line DO lane mein hoti hai (document + media): ek lane
    se line hata dene par bhi doosri lane ki copy check ko "pass" kara deti thi.
    Kis lane ki line hai, ye ab function ke andar naapa jaata hai.
    """
    html = _html()
    at = html.index("function " + name + "(")
    at = html.rindex("\n", 0, at) + 1
    nxt = _TOP_LEVEL_RE.search(html, html.index("\n", at) + 1)
    return html[at:nxt.start() if nxt else len(html)]


def _literal(node):
    """`ast` node se asli value — `200 * 1024 * 1024` bhi chalta hai.

    Import ka raasta jaan-boojh kar nahi liya: `api/routes.py` fastapi maangta
    hai aur wo is offline box par nahi hai. Constant ko haath se dobara likh
    dena bhi mana hai — tab test client aur backend ke *farq* ko naap hi nahi
    paayega, jo is file ka poora maqsad hai.
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return tuple(_literal(item) for item in node.elts)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_literal(node.operand)
    if isinstance(node, ast.BinOp):
        left, right = _literal(node.left), _literal(node.right)
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Add):
            return left + right
    raise AssertionError("is constant ko ast se padha nahi ja saka: "
                         + ast.dump(node)[:120])


def _backend_const(path, name):
    """Backend file se module-level constant nikaalo (source of truth)."""
    with open(path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if name in names:
                return _literal(node.value)
        if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                and node.target.id == name and node.value is not None):
            return _literal(node.value)
    raise AssertionError(
        name + " " + os.path.basename(path) + " me mila hi nahi — matlab ye "
        "contract test khali chal raha tha (rename hua ho to test bhi badlo)")


def _js_const(name):
    """Shipped page ke `const NAME=...;` ko node se padho (asli shipped value)."""
    return _js({"value": "JSON.stringify(" + name + ")"})["value"]


def _shipped_expr(name):
    """`const NAME=<expr>;` ka raw expression — bina node ke (static test)."""
    html = _html()
    found = re.search(r"const " + re.escape(name) + r"=([^;\n]+);", html)
    assert found, ("shipped page mein `const " + name + "=` nahi mila — client "
                   "constant ka naam badla hai to ye test bhi badlo")
    return found.group(1).strip()


def _py_number(expr):
    """`200*1024*1024` jaisi expression ka number (python side)."""
    return _literal(ast.parse(expr.replace(" ", ""), mode="eval").body)


def _strings(expr):
    """Expression ke andar ke quoted string (JS list ya python tuple, dono)."""
    return [m.group(2) for m in re.finditer(r"""(['"])(.*?)\1""", expr)]


# ── STATIC: client ki list/limit backend ke asli constant se milao ────────────

def test_media_extension_list_matches_backend_audio_supported():
    """Client ka accept aur backend ka AUDIO_SUPPORTED ek hi hone chahiye.

    Alag ho jaane par user ko 400 milta hai *upload ke baad* — 200 MB bhej kar.
    Isliye ye ginti list dono jagah se nikaali jaati hai, haath se likhi nahi.
    """
    backend = list(_backend_const(ROUTES, "AUDIO_SUPPORTED"))
    client = _strings(_shipped_expr("MEDIA_EXT"))
    assert backend, "AUDIO_SUPPORTED khaali nikla — contract test khali chal raha tha"
    assert client == backend, ("MEDIA_EXT aur AUDIO_SUPPORTED alag hain: client="
                              + repr(client) + " backend=" + repr(backend))
    # File-picker ka accept bhi wahi list dikhaye, warna user ko file hi nahi milegi.
    accept = re.search(r'id="mediainput"[^>]*accept="([^"]+)"', _html())
    assert accept, "mediainput par accept attribute hi nahi hai"
    assert [x.strip() for x in accept.group(1).split(",")] == backend


def test_size_and_batch_limits_match_the_backend_numbers():
    """Teen limit backend se aayi hain: audio bytes, PDF bytes, batch pages."""
    assert _py_number(_shipped_expr("MAX_MEDIA_BYTES")) == \
        _backend_const(ROUTES, "MAX_AUDIO_BYTES")
    assert _py_number(_shipped_expr("MAX_BOOK_BYTES")) == \
        _backend_const(READING_ROUTES, "MAX_READING_PDF_BYTES")
    batch = _py_number(_shipped_expr("BOOK_BATCH_PAGES"))
    assert batch == _backend_const(READING_ENGINE, "DEFAULT_BATCH_PAGES")
    assert 1 <= batch <= _backend_const(READING_ENGINE, "MAX_BATCH_PAGES")


def test_youtube_id_rules_match_the_backend_parser():
    """Client wahi marker aur wahi 64-char had use kare jo backend karta hai.

    Backend mein ye constant nahi hai (inline tuple hai), isliye usi source line
    se nikaala jaata hai — dobara type karke "match" dikhana bekaar hota.
    """
    with open(ROUTES, "r", encoding="utf-8") as handle:
        routes_src = handle.read()
    # Sirf ingest-youtube handler ke andar dekho — routes.py mein `for marker in`
    # kahin aur bhi hai, aur poori file par regex chalane se galat tuple mil jaata
    # hai (test "pass" dikhta hai par kuch bhi naapa nahi jaata).
    at = routes_src.index('@router.post("/ingest-youtube")')
    handler = routes_src[at:at + 2000]
    hit = re.search(r"for marker in \(([^)]*)\)", handler)
    assert hit, "routes.py mein youtube marker wala loop nahi mila"
    backend_markers = _strings(hit.group(1))
    assert backend_markers, "marker tuple khaali nikla"
    js = re.search(r"for\(const marker of \[([^\]]*)\]\)", _html())
    assert js, "shipped page mein ytVideoId ka marker loop nahi mila"
    assert _strings(js.group(1)) == backend_markers, "marker list dono jagah alag hai"
    cap = re.search(r"len\(video_id\) > (\d+)", routes_src)
    assert cap, "routes.py mein video-id length cap nahi mila"
    assert "id.length>" + cap.group(1) in _html(), \
        "client ki id-length had backend se alag hai"
    assert "/^[A-Za-z0-9_-]+$/.test(id)" in _html(), \
        "client par alnum/_/- ki jaanch nahi hai (backend par hai)"


def test_the_endpoints_this_page_calls_actually_exist_in_backend():
    """Har URL jo page maangta hai, backend ke router mein hona chahiye."""
    html = _html()
    with open(ROUTES, "r", encoding="utf-8") as handle:
        routes_src = handle.read()
    with open(READING_ROUTES, "r", encoding="utf-8") as handle:
        reading_src = handle.read()
    pairs = [("/api/v1/processing-capabilities", routes_src),
             ("/api/v1/transcribe-audio", routes_src),
             ("/api/v1/ingest-youtube", routes_src),
             ("/api/v1/reading-sessions/start", reading_src)]
    for url, src in pairs:
        assert url in html, "page ye endpoint call hi nahi karta: " + url
        assert url.replace("/api/v1", "") in src, "backend mein route nahi: " + url
    assert "/resume" in reading_src and '+"/resume"' in html


# ── STATIC: shipped markup/JS ki poori line pin ───────────────────────────────

def test_all_three_lanes_ship_disabled_until_capability_is_known():
    """Default halat BAND hai. Khula button = "chal jaayega" ka waada."""
    html = _html()
    for line in [
        '        <button type="button" class="dbtn" id="pickmedia" disabled>Audio/video file do (local transcribe)</button>',
        '        <button type="button" class="dbtn" id="yttoggle" disabled>YouTube link do (public captions)</button>',
        '        <button type="button" class="dbtn" id="pickbook" disabled>Badi PDF/kitaab — page-by-page padho</button>',
    ]:
        assert line in html, "shipped markup ki ye line badal gayi:\n" + line
    # Khulne ka ek hi raasta: server ki asli capability.
    assert "  pickmedia.disabled=!m.ok;yttoggle.disabled=!y.ok;pickbook.disabled=!b.ok;" in html
    assert "pickmedia.disabled=false" not in html and "yttoggle.disabled=false" not in html \
        and "pickbook.disabled=false" not in html, \
        "kahin lane ko capability dekhe bina khola ja raha hai"


def test_unknown_capability_list_shuts_every_lane_with_the_reason():
    """Capability list na aaye to teeno band + wajah, na ki chup-chaap khula."""
    html = _html()
    assert "  if(!CAPS.data){pickmedia.disabled=true;yttoggle.disabled=true;pickbook.disabled=true;\n" \
        in html.replace("\r\n", "\n"), "capability na milne par band karne wali line gayab"
    assert 'band dikhana galat \\"chal jaayega\\" se behtar hai' in html, \
        "capability unknown wali honesty line gayab hai"
    assert "isliye audio/video/YouTube/kitaab lane band rakhe hain" in html


def test_capability_probe_runs_on_panel_open_and_only_once():
    """Page load par extra request nahi; aur single-flight guard rehna chahiye."""
    html = _html()
    assert "attach.addEventListener" in html and "loadCaps().then(applyCaps)" in html
    assert "  if(CAPS.loaded){applyCaps();return;}" in html
    assert "  if(capsPromise)return capsPromise;" in html, \
        "single-flight guard hata diya to ek hi panel-open par kai request jaayengi"
    assert _count(html, "/api/v1/processing-capabilities") == 1


def test_file_mode_shuts_the_media_lanes_too():
    """file:// se khole page par API hi nahi hoti — lane khule dikhana jhooth hai."""
    html = _html()
    assert "  pickmedia.disabled=true;yttoggle.disabled=true;pickbook.disabled=true;ytactions.hidden=true;" in html
    assert "isliye audio/video, YouTube aur kitaab wale lane bhi band hain" in html


def test_uploads_keep_the_session_token_in_the_header_only():
    """Token URL/query mein kabhi nahi (log mein leak ho jaata hai)."""
    html = _html()
    assert '{method:"POST",headers:{"X-Project-Token":PROJECT.token},body:build(PROJECT.id)}' in html
    for leak in ['token="+', "?token", "&token", "token="+"'"]:
        assert leak not in html, "session token URL/query mein ja raha hai: " + leak
    # FormData par Content-Type browser khud lagata hai; hum lagayein to boundary toot jaati hai.
    form = html[html.index("async function projectForm"):html.index("async function uploadMedia")]
    code = "\n".join(l for l in form.splitlines() if not l.strip().startswith("//"))
    assert "Content-Type" not in code, "FormData request par Content-Type set ho raha hai"

    # 404 par exactly ek refresh — loop nahi.
    assert "  for(let attempt=0;attempt<2;attempt++){" in form
    assert "    if(out.r.status!==404||attempt===1)break;" in form


def test_one_file_at_a_time_lock_is_shared_with_document_upload():
    """Local transcribe CPU-bhaari hai; do saath chalein to backend ragad jaata hai."""
    html = _html()
    # Dono lane ka lock alag-alag naapo: pehle sirf page-bhar dekha jaata tha, aur
    # ek lane se lock hata dene par doosri lane ki copy check ko pass kara deti thi.
    for name in ("uploadMany", "mediaMany"):
        body = _fn(name)
        for line in ("  if(uploading||!items.length)return;",
                     "  uploading=true;attach.disabled=true;",
                     "  finally{uploading=false;attach.disabled=IS_FILE;}"):
            assert line in body, name + " ka ek-waqt-ek-file lock toota: " + line.strip()
    assert _count(html, "  if(uploading||!items.length)return;") == 2, \
        "lock sirf do jagah (document + media) hona chahiye"


def test_earlier_document_lane_is_still_intact():
    """#90-#92 ka upload lane hataya nahi gaya — naya lane uske neeche juda hai."""
    html = _html()
    for needle in ['<div class="doclist" id="doclist"></div>',
                   'id="fileinput"', 'id="pastesend"', 'async function uploadDoc',
                   'id="pickfile"']:
        assert needle in html, "purana document lane ka hissa gayab: " + needle
    assert html.index('id="doclist"') < html.index('class="docsep"'), \
        "naya media block purane doclist se pehle chala gaya"
    assert 'id="booklist"' in html and '$("#booklist")' in html, \
        "booklist ka markup aur uska JS handle, dono chahiye"
    assert 'id="doclist"' in html and "function renderDocs" in html, \
        "purana doclist render hona band ho gaya"


# ── BEHAVIOUR: shipped JS asli mein node par chalta hai ───────────────────────

# Server ka asli payload shape (api/routes.py ke processing-capabilities se).
CAPS_ALL_OK = {
    "pdf_text": {"available": True, "needs": "pymupdf install karo"},
    "pdf_ocr_for_scanned_pages": {"available": True,
                                  "detail": {"ok": True, "backend": "pytesseract"},
                                  "needs": "pytesseract + Tesseract binary"},
    "docx": {"available": True, "needs": "python-docx"},
    "transcripts_vtt_srt": {"available": True, "needs": ""},
    "youtube_captions": {"available": True, "enabled_flag": True,
                         "library_installed": True,
                         "needs": ".env mein ALLOW_YT_TRANSCRIPT=true + youtube-transcript-api"},
    "full_text_fetch": {"enabled": True, "note": "free sources only"},
    "audio_video_transcription": {"available": True, "backend": "faster-whisper",
                                  "needs": "faster-whisper ya openai-whisper",
                                  "note": "local only"},
}


def _caps(**patch):
    """CAPS_ALL_OK ki copy, kuch key badli hui (deep copy — leak na ho)."""
    data = json.loads(json.dumps(CAPS_ALL_OK))
    for key, value in patch.items():
        data[key] = value
    return data


def _gates(caps):
    out = _js({"m_ok": "mediaGate(PAY.caps).ok", "m_why": "mediaGate(PAY.caps).why",
               "y_ok": "ytGate(PAY.caps).ok", "y_why": "ytGate(PAY.caps).why",
               "b_ok": "bookGate(PAY.caps).ok", "b_why": "bookGate(PAY.caps).why",
               "lines": 'capsLines(PAY.caps).join(" | ")'}, {"caps": caps})
    return out


def test_all_three_lanes_open_when_the_server_says_it_can():
    got = _gates(CAPS_ALL_OK)
    assert got["m_ok"] == "true" and got["y_ok"] == "true" and got["b_ok"] == "true"
    assert "faster-whisper" in got["m_why"], "asli local backend ka naam dikhna chahiye"
    assert got["lines"].count("✓") == 3 and "✕" not in got["lines"]


def test_audio_lane_closes_and_names_the_real_missing_dependency():
    """Server ka `needs` jaisa hai waisa dikhe — apna anumaan nahi."""
    caps = _caps(audio_video_transcription={
        "available": False, "backend": "",
        "needs": "faster-whisper YA openai-whisper install karo (free + local).",
        "note": "koi paid API nahi"})
    got = _gates(caps)
    assert got["m_ok"] == "false"
    assert "faster-whisper YA openai-whisper install karo (free + local)" in got["m_why"]
    assert ".." not in got["m_why"], "backend ke needs ka full-stop dobara lag gaya"
    assert "paid API" in got["m_why"], "₹0 ka niyam lane ki wajah ke saath likha rehna chahiye"
    assert got["lines"].split(" | ")[0].startswith("✕ Audio/video:")


def test_missing_capability_key_is_treated_as_closed_not_as_yes():
    """Key hi na aaye (purana backend) to lane BAND — `undefined` khula nahi."""
    caps = json.loads(json.dumps(CAPS_ALL_OK))
    caps.pop("audio_video_transcription")
    caps.pop("youtube_captions")
    caps["pdf_text"] = {"needs": "pymupdf"}
    got = _gates(caps)
    assert got["m_ok"] == "false" and got["y_ok"] == "false" and got["b_ok"] == "false"
    assert "undefined" not in got["lines"] and "[object Object]" not in got["lines"]


def test_null_or_broken_capability_payload_keeps_lanes_shut():
    for payload in [None, "nope", [1, 2], 7]:
        got = _js({"m": "String(mediaGate(PAY.c).ok)", "y": "String(ytGate(PAY.c).ok)",
                   "b": "String(bookGate(PAY.c).ok)",
                   "lines": 'capsLines(PAY.c).join(" | ")'}, {"c": payload})
        assert got["m"] == "false" and got["y"] == "false" and got["b"] == "false", \
            "toote payload par lane khul gaya: " + repr(payload)
        assert "undefined" not in got["lines"]


def test_youtube_lane_says_which_half_is_missing():
    """Flag band hona aur library na hona do alag baat hai — dono alag likhi jayein."""
    both = _gates(_caps(youtube_captions={
        "available": False, "enabled_flag": False, "library_installed": False,
        "needs": "ALLOW_YT_TRANSCRIPT=true + youtube-transcript-api"}))["y_why"]
    flag_off = _gates(_caps(youtube_captions={
        "available": False, "enabled_flag": False, "library_installed": True,
        "needs": "ALLOW_YT_TRANSCRIPT=true"}))["y_why"]
    lib_off = _gates(_caps(youtube_captions={
        "available": False, "enabled_flag": True, "library_installed": False,
        "needs": "youtube-transcript-api"}))["y_why"]
    assert "flag band hai aur caption library bhi install nahi hai" in both
    assert "caption library install hai, par server ka ALLOW_YT_TRANSCRIPT flag band hai" in flag_off
    assert "flag on hai, par caption library install nahi hai" in lib_off
    assert len({both, flag_off, lib_off}) == 3, "teen haalat ka ek hi jawab aa raha hai"


def test_book_lane_needs_pdf_library_and_warns_when_ocr_is_absent():
    shut = _gates(_caps(pdf_text={"available": False, "needs": "pymupdf install karo"}))
    assert shut["b_ok"] == "false" and "pymupdf install karo" in shut["b_why"]
    no_ocr = _gates(_caps(pdf_ocr_for_scanned_pages={
        "available": False, "detail": {"ok": False, "backend": ""},
        "needs": "pytesseract + Tesseract binary"}))
    assert no_ocr["b_ok"] == "true", "text-PDF padhna OCR ke bina bhi hota hai"
    assert "Scan-only page OCR ke bina unreadable rahenge" in no_ocr["b_why"]
    assert "pytesseract + Tesseract binary" in no_ocr["b_why"]
    yes_ocr = _gates(CAPS_ALL_OK)["b_why"]
    assert "Scan wale page ke liye OCR bhi available hai" in yes_ocr
    assert "unreadable rahenge" not in yes_ocr, "OCR hote hue bhi darane wali line aa gayi"


def test_book_lane_never_promises_the_whole_book_in_one_go():
    why = _gates(CAPS_ALL_OK)["b_why"]
    batch = _py_number(_shipped_expr("BOOK_BATCH_PAGES"))
    assert str(batch) + " page ke bounded batch" in why
    assert 'adhoori reading kabhi "poori kitaab padh li" nahi kehlati' in why
    assert "Text nikal jaana padh-kar-samajh lena nahi hai" in why


def test_video_lanes_always_say_no_visual_analysis_happens():
    """Sabse aasan jhooth: "video dekh liya". Transcription sirf audio ka hai."""
    note = _js({"n": "NO_FRAME_NOTE"})["n"]
    # Sirf "no-frame ka tukda maujood hai" dekhna kaafi nahi tha: line ke *aage* ek
    # ulta daawa jod dene par bhi wo check pass ho jaata tha. Isliye line ka shuru
    # aur "visual/audio" ki ginti, dono pin hain.
    assert note.startswith("Video ka sirf audio padha jaata hai"), \
        "no-frame line ke aage kuch aur daawa lag gaya: " + note
    assert "frame" in note and "visual ka koi analysis nahi hota" in note
    assert _count(note, "visual") == 1 and _count(note, "audio") == 1, \
        "no-frame line mein doosra (ulta) daawa ghus gaya: " + note
    why = _gates(CAPS_ALL_OK)["m_why"]
    assert note in why, "audio/video gate par no-frame line nahi"
    assert _count(why, "visual") == 1 and _count(why, "frame") == 1, \
        "gate par visual/frame ki baat do baar — ek jagah ulta daawa hai: " + why
    # Dono video lane ke success text mein bhi (uploadMedia + ingestYt).
    assert "NO_FRAME_NOTE" in _fn("uploadMedia") and "NO_FRAME_NOTE" in _fn("ingestYt")


def test_youtube_lane_calls_it_captions_not_transcription():
    why = _gates(CAPS_ALL_OK)["y_why"]
    assert "public captions hain, audio transcription nahi" in why
    assert "caption milna samajh lena nahi hota" in why
    ingest = _html()
    assert 'Ye video ke public captions hain, audio transcription nahi.' in ingest, \
        "backend honesty_note na aaye to bhi client ki apni saaf line honi chahiye"


def test_video_id_is_parsed_exactly_like_the_backend_does():
    samples = ["https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s",
               "https://youtu.be/abc_-123",
               "https://www.youtube.com/shorts/xyz789",
               "https://www.youtube.com/embed/ID9/",
               "dQw4w9WgXcQ",
               "  https://youtu.be/dQw4w9WgXcQ?si=zz  ",
               "https://example.com/not-a-video/#$%",
               "a" * 65,
               "", "   ", "v="]
    got = _js({"ids": "JSON.stringify(PAY.rows.map(ytVideoId))"}, {"rows": samples})
    ids = json.loads(got["ids"])
    assert ids == ["dQw4w9WgXcQ", "abc_-123", "xyz789", "ID9", "dQw4w9WgXcQ",
                   "dQw4w9WgXcQ", "", "", "", "", ""], ids


def test_reading_line_reports_measured_coverage_not_a_finished_claim():
    session = {"session_id": "s1", "status": "IN_PROGRESS", "processing_blocker": "",
               "coverage": {"total_pages": 120, "page_inspection_fraction": 0.25,
                            "text_available_fraction": 0.2, "next_page": 31,
                            "unreadable_page_ranges": [{"start": 7, "end": 9},
                                                       {"start": 31, "end": 31}],
                            "pending_translation_page_ranges": []},
               "honesty": {"completion_claim": "PARTIAL_PAGE_INSPECTION"}}
    got = _js({"line": "readingLine(PAY.s)", "done": "String(bookDone(PAY.s))"},
              {"s": session})
    assert got["line"] == ("Status: IN_PROGRESS • Page dekhe: 25% (kul 120 page) "
                           "• Text mila: 20% • Padhe nahi ja sake page: 7-9, 31 "
                           "• Dawa: PARTIAL_PAGE_INSPECTION • Agla batch page 31 se")
    assert got["done"] == "false", "next_page bacha hai to kitaab poori nahi hui"


def test_reading_line_prints_the_backend_blocker_when_there_is_one():
    session = {"status": "BLOCKED", "processing_blocker": "pymupdf missing",
               "coverage": {"total_pages": 0, "next_page": 0},
               "honesty": {"completion_claim": "NOT_READ_YET"}}
    got = _js({"line": "readingLine(PAY.s)", "done": "String(bookDone(PAY.s))"},
              {"s": session})
    assert "Ruka: pymupdf missing" in got["line"]
    assert "Kul page ka pata nahi chala" in got["line"], \
        "page count na mile to 0% dikhana jhooth hai"
    assert "Dawa: NOT_READ_YET" in got["line"]
    assert got["done"] == "true"


def test_reading_line_invents_nothing_from_an_empty_payload():
    for payload in [None, {}, "kuch nahi", []]:
        line = _js({"line": "readingLine(PAY.s)"}, {"s": payload})["line"]
        assert "Status: pata nahi" in line and "Dawa: NOT_READ_YET" in line, line
        assert "Text mila: pata nahi" in line, "0% dikhana = naapa hua 0 ka jhooth"
        assert "undefined" not in line and "NaN" not in line
        assert "Aage koi pending batch nahi" in line


def test_page_ranges_render_as_numbers_not_object_tostring():
    """Backend `[{"start":a,"end":b}]` deta hai — seedha join karne par
    "[object Object]" chhapta hai (#113 wala defect). Aur adhoori list ko chhota
    kar ke dikhana ho to "+N aur" saaf likha jaana chahiye."""
    rows = [{"start": 1, "end": 1}, {"start": 4, "end": 6}, {"start": 0, "end": 0},
            None, "x", {"start": 9, "end": 9}]
    got = _js({"few": "rangeText(PAY.rows)", "empty": "rangeText([])",
               "junk": "rangeText(PAY.junk)",
               "many": "rangeText(PAY.many)"},
              {"rows": rows, "junk": "nope",
               "many": [{"start": i, "end": i} for i in range(1, 13)]})
    assert got["few"] == "1, 4-6, 9"
    assert got["empty"] == "" and got["junk"] == ""
    assert got["many"] == "1, 2, 3, 4, 5, 6, 7, 8 (+4 aur)"
    assert "[object Object]" not in got["few"] + got["many"]


def test_unreadable_pages_are_never_hidden():
    session = {"status": "IN_PROGRESS",
               "coverage": {"total_pages": 10, "page_inspection_fraction": 1.0,
                            "text_available_fraction": 0.4, "next_page": 0,
                            "unreadable_page_ranges": [{"start": 2, "end": 5}],
                            "pending_translation_page_ranges": [{"start": 8, "end": 8}]},
               "honesty": {"completion_claim": "PAGES_SEEN_TEXT_PARTIAL"}}
    line = _js({"line": "readingLine(PAY.s)"}, {"s": session})["line"]
    assert "Padhe nahi ja sake page: 2-5" in line
    assert "Translation review pending page: 8" in line
    assert "Dawa: PAGES_SEEN_TEXT_PARTIAL" in line


def test_backend_reason_reaches_the_user_string_or_dict():
    got = _js({"s": 'detailText({detail:"  koi library nahi  "})',
               "d": 'detailText({detail:{message:"501 hai",hint:"install karo",needs:"whisper"}})',
               "long": 'String(detailText({detail:"x".repeat(900)}).length)',
               "none": "detailText({})",
               "arr": "detailText({detail:[1,2]})"})
    assert got["s"] == "koi library nahi"
    assert got["d"] == "501 hai install karo whisper"
    assert got["long"] == "400", "bahut lamba detail screen bhar deta hai"
    assert got["none"] == "" and got["arr"] == ""


def _failures():
    rows = [[501, {"detail": {"message": "local STT nahi hai", "hint": "faster-whisper"}}, "Transcribe", False],
            [400, {"detail": "video id galat"}, "YouTube captions", False],
            [422, {"detail": "captions available nahi"}, "YouTube captions", False],
            [429, {"detail": "busy", "retry_after_seconds": 45}, "Transcribe", False],
            [429, {}, "Transcribe", False],
            [413, {}, "Reading session", False],
            [401, {}, "Transcribe", False],
            [403, {}, "Transcribe", False],
            [404, {}, "Reading session", False],
            [503, {}, "Reading session", False],
            [500, {}, "Reading session", False],
            [0, {}, "Transcribe", False],
            [418, {}, "Transcribe", False],
            [200, {}, "Reading session", True]]
    got = _js({"out": "JSON.stringify(PAY.rows.map(r=>mediaFailure(r[0],r[1],r[2],r[3])))"},
              {"rows": rows})
    return json.loads(got["out"])


def test_a_501_never_advises_a_retry_that_cannot_work():
    """501 = capability install hi nahi hai. "dobara try karo" jhooth hoga."""
    lines = _failures()
    first = lines[0]
    assert "capability install hi nahi hai, retry se nahi hogi" in first
    assert "dobara" not in first.lower(), "501 par retry ki salah di ja rahi hai: " + first
    assert "Backend ne kaha: local STT nahi hai faster-whisper" in first


def test_upload_failures_never_talk_about_the_question_input():
    """Chat wali line ("question input mein wapas rakh diya hai") yahan jhooth hai —
    koi question bheja hi nahi gaya tha."""
    for line in _failures():
        assert "Question input" not in line and "question input" not in line, line
        assert line.strip() and "undefined" not in line and "[object Object]" not in line
        assert "NaN" not in line


def test_each_failure_code_gets_its_own_honest_reason():
    lines = _failures()
    assert "supported nahi hai" in lines[1] and "kaam layak content nahi nikla" in lines[2]
    assert "45 second baad dobara do" in lines[3]
    assert "thoda ruk kar dobara do" in lines[4] and "second baad" not in lines[4]
    assert "server ki had se badi hai" in lines[5]
    for i in (6, 7, 8):
        assert "Private session valid nahi rahi" in lines[i]
    assert "private session/storage layer ready nahi hai" in lines[9]
    assert "complete nahi ki" in lines[10]
    assert "network connection nahi bana — kuch bhi upload/ingest nahi hua" in lines[11]
    assert "(HTTP 418)" in lines[12]
    assert "safe wait-time khatam" in lines[13] and "backend abhi bhi chala raha ho" in lines[13]
    # 400 / 422 / 501 ek hi `if` mein hain — phir bhi teeno ki wajah alag likhi jaaye.
    assert len({lines[0], lines[1], lines[2]}) == 3, "teen alag wajah ka ek hi jawab"


# ── HONESTY: kya ye lane apne aap ko sabooot bana leta hai? ──────────────────

_BIG_WORDS = ["PROVEN", "TESTED_PASS", "CONFIRMED", "saabit", "sach hai",
              "video dekh liya", "samajh liya", "poora padh liya"]


def test_media_lanes_never_upgrade_themselves_into_evidence():
    """Gate/coverage/failure ki kisi line mein bada daawa nahi aana chahiye."""
    got = _gates(CAPS_ALL_OK)
    session = {"status": "COMPLETED",
               "coverage": {"total_pages": 5, "page_inspection_fraction": 1.0,
                            "text_available_fraction": 1.0, "next_page": 0},
               "honesty": {"completion_claim": "ALL_PAGES_INSPECTED"}}
    text = " ".join([got["m_why"], got["y_why"], got["b_why"], got["lines"],
                     _js({"l": "readingLine(PAY.s)"}, {"s": session})["l"]]
                    + _failures())
    for word in _BIG_WORDS:
        assert word not in text, "media lane khud ko sabooot bana raha hai: " + word
    assert "VERIFIED" not in text, "gate/coverage line VERIFIED ka daawa kar rahi hai"
    # "poori kitaab padh li" sirf inkaar ke saath aa sakta hai.
    for hit in re.finditer(r"poori kitaab padh li", text):
        assert 'nahi kehlati' in text[hit.start():hit.start() + 60], \
            "kitaab poori padh li ka daawa: " + text[hit.start():hit.start() + 60]


def test_success_text_labels_it_as_user_supplied_and_not_verification():
    """Transcript/captions research ka source hai, saboot nahi.

    "VERIFIED" shabd is lane mein sirf inkaar ke saath aa sakta hai.
    """
    html = _html()
    assert ("akela ye kisi baat ko VERIFIED nahi banata" in html), \
        "transcript ko VERIFIED se alag karne wali line gayab hai"
    block = html[html.index("async function uploadMedia"):html.index("const bookRuns=[]")]
    for hit in re.finditer(r"VERIFIED", block):
        tail = block[hit.start():hit.start() + 30]
        assert "VERIFIED nahi banata" in tail, "VERIFIED ka daawa: " + tail
    assert "machine transcript hai — samajh (comprehension) nahi" in html
    # Teen lane (document, transcribe, captions) — teeno ka 0-chunk case alag naapo.
    # Pehle sirf ek bade block mein dekha jaata tha, isliye ek lane se ye line hata
    # dene par doosri lane ki copy check ko pass kara deti thi.
    assert _count(html, "Research isko source nahi banayegi") == 3, \
        "0-chunk par 'source nahi banegi' ki line teen lane mein honi chahiye"
    for name in ("uploadDoc", "uploadMedia", "ingestYt"):
        assert "Research isko source nahi banayegi" in _fn(name), \
            name + " 0 chunk par bhi 'tayyar' dikha raha hai"


def test_media_failure_does_not_borrow_the_chat_failure_text():
    """`clientFailure` chat ke liye hai (question wapas rakhna, retry ki salah).
    Upload/ingest par wo line jhooth hoti hai, isliye alag ladder hai."""
    html = _html()
    chat, media = _fn("clientFailure"), _fn("mediaFailure")
    assert "clientFailure" not in media, "media lane phir se chat ka text use kar raha hai"
    assert _count(html, "function mediaFailure") == 1
    assert _count(html, "function needsText") == 1, \
        "needsText do baar define ho gaya (pehle ek baar ye galti hui thi)"
    # `aborted` ka jawab theek do jagah likha hai — chat wala question wapas rakhta
    # hai, media wala nahi. Ek bhi extra `if(aborted)return` matlab ab ye tay nahi
    # ki user ko kaunsi line dikhegi.
    assert _count(html, "if(aborted)return ") == 2, \
        "aborted ka jawab do se zyada jagah likha hai: " + str(
            _count(html, "if(aborted)return "))
    assert _count(chat, "if(aborted)return ") == 1
    assert _count(media, "if(aborted)return ") == 1
    assert "Question input mein wapas rakh diya hai" in chat, \
        "chat ka aborted jawab badal gaya — wahan question wapas rakhna sahi hai"
    assert "Question input" not in media, \
        "media ka aborted jawab chat wali line bol raha hai"


def test_the_same_payload_always_renders_the_same_text():
    """Koi random/waqt par nirbhar text nahi — do baar mein ek hi jawab."""
    first, second = _gates(CAPS_ALL_OK), _gates(CAPS_ALL_OK)
    assert first == second
    assert _failures() == _failures()
