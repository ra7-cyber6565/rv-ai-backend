"""
#119 — sawaal ki bhasha app ki seema na bane.

Naapa hua baseline (isi repo par, 2026-08-27): teen bilkul on-topic English
paper, aur ek hi baat poochhne wale paanch sawaal —

    "how to improve brain performance and memory"  -> 0.667 / 0.093 / 0.314
    "dimag tej kaise kare"                         -> 0.520 / 0.000 / 0.338
    "दिमाग तेज कैसे करें"                            -> 0.418 / 0.000 / 0.279
    "মস্তিষ্ক কীভাবে তীক্ষ্ণ করা যায়"                  -> 0.000 / 0.000 / 0.000
    "как улучшить память и работу мозга"           -> 0.000 / 0.000 / 0.000

Hindi sirf isliye chal raha tha ki `multilingual_research.py` me un shabdon ki
hath se likhi glossary maujood hai. Jo bhasha kisi ne pehle type nahi ki, wo app
ke liye maujood hi nahi thi — aur `rank()` us par ZERO source rakhti thi.

Ye file teen cheezein pin karti hai:
  1. script ka pul kisi shabd-list se nahi, Unicode ke apne character naamon se
     banta hai (list-free ka static saboot bhi),
  2. matlab ka pul Wikipedia ke apne langlinks se aata hai, aur na mile to
     `translation_missing` bola jaata hai — chup nahi baithte,
  3. English↔English scoring bit-identical rehti hai, warna 983/594/649/156/328
     wale naape hue benchmark hil jaate.

Poora offline: koi network, koi model, koi nayi dependency.
"""
from __future__ import annotations

import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import lang_bridge as lb            # noqa: E402
from research_engine import semantic                     # noqa: E402
from research_engine.connectors import base as cbase     # noqa: E402
from research_engine.connectors import classic_connector as cc  # noqa: E402

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ENGLISH_PAPER = ("Cognitive training improves working memory and brain "
                 "performance in healthy adults")
OFFTOPIC_PAPER = ("Gearbox vibration spectra were measured to detect bearing "
                  "wear in rotating industrial machinery")


def _read(rel: str) -> str:
    with open(os.path.join(_BACKEND, rel), "r", encoding="utf-8",
              errors="replace") as handle:
        return handle.read()


# ── A. script ka pul — bina kisi shabd list ke ──────────────────────────────

def test_transliteration_joins_loanwords_across_scripts():
    """Ek bhi entry likhe bina judne chahiye — yehi #119 ka dil hai."""
    pairs = [
        ("क्वांटम", "quantum"), ("सुपरकंडक्टिविटी", "superconductivity"),
        ("श्रोडिंगर", "schrodinger"), ("फेनमैन", "feynman"),
        ("Шрёдингер", "schrodinger"), ("রামায়ণ", "ramayan"),
        ("ਗੁਰਬਾਣੀ", "gurbani"), ("ધ્યાન", "dhyan"),
        # Gurmukhi TIPPI Devanagari ke usi khaane par aligned nahi hai — nasal
        # gir jaaye to "cubk" bachta hai aur ye jodi tootti hai.
        ("ਚੁੰਬਕ", "chumbak"),
    ]
    for foreign, english in pairs:
        assert lb.skeletons_match(lb.roman(foreign), english), (
            foreign, lb.roman(foreign), english)


def test_the_bridge_does_not_join_words_that_only_look_similar():
    """Chhoot ek galti ki hai, andhi nahi — warna har shabd sabse match karega."""
    for a, b in (("brain", "train"), ("test", "text"), ("memory", "mercury"),
                 ("quantum", "quality"), ("dhyan", "gyan"),
                 # ye jodiyan do galti door hain (mgnt/plnt, krbn/grbk,
                 # ntrtn/vbrtn, kntm/kbnt) — chhoot 2 ho jaaye to gearbox wala
                 # off-topic paper carbon ke sawaal par match karne lagega.
                 ("magnet", "planet"), ("carbon", "gearbox"),
                 ("nutrition", "vibration"), ("quantum", "cabinet")):
        assert not lb.skeletons_match(a, b), (a, b)


def test_script_and_language_are_read_from_the_code_point_not_a_list():
    assert lb.dominant_script("মস্তিষ্ক") == "bengali"
    assert lb.dominant_script("दिमाग") == "devanagari"
    assert lb.dominant_script("мозга") == "cyrillic"
    assert lb.dominant_script("brain") == "latin"
    assert lb.wiki_lang_of("bengali") == "bn"
    assert lb.wiki_lang_of("cyrillic") == "ru"
    # Latin/anjaan script par "en" — yahi safe default hai (English lane pehle
    # se khuli hoti hai, isliye `langs_for_question` par iska koi asar nahi).
    assert lb.wiki_lang_of("latin") == "en"
    assert lb.wiki_lang_of("unknown") == "en"


def test_a_danda_still_separates_two_words_after_romanisation():
    """
    Devanagari/Bangla me danda "।" ke baad space nahi hota. Viraam gir jaaye to
    do shabd chipak kar ek naya (galat) shabd ban jaate hain.
    """
    assert lb.roman_tokens("राम।सीता") == ["raam", "siitaa"]
    assert len(lb.roman_tokens("মস্তিষ্ক।ব্রেন")) == 2


def test_a_never_before_seen_word_still_gets_romanised():
    """Naya/anjaan shabd bhi roman ban jaaye — tabhi ye list-free hai."""
    for word in ("বিদ্যুৎচুম্বকীয়", "అయస్కాంతత్వం", "ਚੁੰਬਕਤਾ", "மின்காந்தவியல்"):
        out = lb.roman(word)
        assert out and out.isascii(), (word, out)
        assert out != word


def test_the_module_carries_no_hand_written_word_glossary():
    """
    #119 ki asli shikayat closed list thi. Isliye source par static check:
    is module me koi bhi dict/tuple 40 se zyada literal string na rakhe (script
    ke akshar-table chhote hote hain, shabd-glossary badi hoti hai).
    """
    tree = ast.parse(_read(os.path.join("research_engine", "lang_bridge.py")))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Dict, ast.Tuple, ast.Set, ast.List)):
            values = getattr(node, "values", None) or getattr(node, "elts", [])
            words = [v.value for v in values
                     if isinstance(v, ast.Constant) and isinstance(v.value, str)
                     and len(v.value) > 3]
            assert len(words) <= 40, f"{len(words)} shabd wali list mil gayi"


# ── B. zero-regression — English↔English kuch nahi badalta ──────────────────

def test_english_to_english_never_touches_the_bridge():
    assert lb.needs_bridge("brain memory", "brain study") is False
    assert lb.needs_bridge("दिमाग", "brain study") is True
    assert lb.needs_bridge("brain", "मस्तिष्क") is True


def test_ascii_similarity_is_bit_identical_to_the_old_literal_score():
    """
    Ye guard hi 983/594/649/156/328 ko bachata hai: agar bridge ASCII par bhi
    lag jaaye to poora naapa hua benchmark set hil jaayega.
    """
    cases = [
        ("superconductivity at room temperature", ENGLISH_PAPER),
        ("how to improve brain performance and memory", ENGLISH_PAPER),
        ("gearbox bearing wear", OFFTOPIC_PAPER),
        ("dimag tej kaise kare", ENGLISH_PAPER),
        # Ye do jodi asli gawah hain: skeleton feynman~foreman aur
        # memory~memoir ko jod deta hai, isliye bridge ASCII par lag jaaye to
        # score literal se UPAR chala jaayega. `needs_bridge` ka pehra hi
        # English↔English benchmark ko hilne se rokta hai.
        ("feynman lectures", "The foreman lectures workers on machinery safety"),
        ("memory of the planet", "A memoir about one pollutant and its history"),
    ]
    for query, text in cases:
        assert semantic.similarity(query, text) == round(
            semantic._literal(query, text), 4), (query, text)


def test_a_broken_bridge_can_never_lower_a_score():
    """Naya module fail ho to purana score wapas aaye — pipeline na girey."""
    saved = lb.bridged_overlap
    try:
        lb.bridged_overlap = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("bridge toota"))
        assert semantic.similarity("दिमाग तेज कैसे करें", ENGLISH_PAPER) >= 0.0
        assert semantic.similarity("brain memory", ENGLISH_PAPER) > 0.0
    finally:
        lb.bridged_overlap = saved


# ── C. asli faayda — non-Latin sawaal par score 0.0 se hilta hai ────────────

def test_a_devanagari_question_now_scores_on_an_english_paper():
    """Naapa hua sudhaar: 0.418 -> 0.5 se upar, bina kisi glossary ke."""
    hindi = "दिमाग तेज कैसे करें brain memory"
    assert semantic.similarity(hindi, ENGLISH_PAPER) > 0.4
    assert semantic.similarity(hindi, OFFTOPIC_PAPER) < 0.2


def test_a_hindi_page_is_found_for_a_hinglish_question():
    """PDF page selection isi similarity par tikti hai (pdf_chunker.page_score)."""
    from research_engine.processing.pdf_chunker import page_score
    page = ("क्वांटम कंप्यूटिंग में सुपरकंडक्टिविटी का उपयोग होता है "
            "और श्रोडिंगर समीकरण भी")
    assert page_score(page, "quantum computing superconductivity schrodinger") > 0.5
    assert page_score(page, "gearbox bearing vibration") == 0.0


def test_one_bridged_word_alone_does_not_win_a_cross_script_score():
    """
    Cross-script pass sirf tab chalta hai jab sawaal me kam se kam do English
    shabd hon — ek shabd par poora score dena jhooth hota.
    """
    assert semantic._MIN_CROSS_TOKENS >= 2
    single = semantic.similarity("मस्तिष्क brain", ENGLISH_PAPER)
    assert single < 0.9, single


def test_the_off_topic_paper_is_still_rejected_in_every_language():
    for question in ("दिमाग तेज कैसे करें", "মস্তিষ্ক তীক্ষ্ণ", "мозга память",
                     "brain memory improve"):
        assert semantic.similarity(question, OFFTOPIC_PAPER) < 0.25, question


# ── D. matlab ka pul — Wikipedia ke apne langlinks ──────────────────────────

class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _fake_fetch(links, calls=None):
    def fetch(url, params=None, timeout=None, retries=None):
        if calls is not None:
            calls.append((url, dict(params or {})))
        lang = url.split("//", 1)[1].split(".", 1)[0]
        term = (params or {}).get("gsrsearch", "")
        page = {"pageid": 1, "title": term}
        title = links.get((lang, term), "")
        if title:
            page["langlinks"] = [{"lang": "en", "title": title}]
        return _Resp({"query": {"pages": [page]}})
    return fetch


def test_the_english_word_comes_from_wikipedias_own_langlinks():
    lb._english_cache.clear()
    calls = []
    fetch = _fake_fetch({("bn", "মস্তিষ্ক"): "Brain"}, calls)
    terms, status = lb.english_terms("মস্তিষ্ক তীক্ষ্ণ", fetch=fetch)
    assert terms == ["Brain"], terms
    assert status == "wikipedia_langlinks_search_vocabulary"
    assert calls and calls[0][0] == "https://bn.wikipedia.org/w/api.php"
    params = calls[0][1]
    assert params["lllang"] == "en" and params["prop"] == "langlinks"
    assert params["action"] == "query" and params["gsrnamespace"] == "0"


def test_the_same_word_is_never_asked_twice():
    lb._english_cache.clear()
    calls = []
    fetch = _fake_fetch({("ru", "мозга"): "Brain"}, calls)
    lb.english_terms("мозга", fetch=fetch)
    lb.english_terms("мозга", fetch=fetch)
    assert len(calls) == 1, calls


def test_nothing_found_is_reported_as_translation_missing():
    lb._english_cache.clear()
    terms, status = lb.english_terms("মস্তিষ্ক", fetch=_fake_fetch({}))
    assert terms == [] and status == "translation_missing"
    report = lb.bridge_report("মস্তিষ্ক", fetch=_fake_fetch({}))
    assert report["status"] == "translation_missing"
    assert report["note"], "chup rehna bhi jhooth hai"
    assert "kam mel" in report["note"]


def test_a_broken_api_answer_never_raises_and_never_lies():
    lb._english_cache.clear()

    def angry(url, params=None, timeout=None, retries=None):
        raise RuntimeError("network down")

    terms, status = lb.english_terms("মস্তিষ্ক", fetch=angry)
    assert terms == [] and status == "translation_missing"

    for junk in ({}, {"query": {}}, {"query": {"pages": None}},
                 {"query": {"pages": [{"langlinks": [{}]}]}}):
        lb._english_cache.clear()
        terms, _ = lb.english_terms(
            "মস্তিষ্ক", fetch=lambda *a, **k: _Resp(junk))
        assert terms == []


def test_an_english_question_never_spends_a_lookup():
    calls = []
    terms, status = lb.english_terms(
        "how to improve brain memory", fetch=_fake_fetch({}, calls))
    assert terms == [] and status == "not_needed_latin_script"
    assert calls == []


def test_the_lookup_can_be_switched_off_and_says_so():
    saved = os.environ.get("LANG_BRIDGE_LOOKUP")
    os.environ["LANG_BRIDGE_LOOKUP"] = "0"
    try:
        assert lb.lookup_enabled() is False
        terms, status = lb.english_terms("মস্তিষ্ক")
        assert terms == [] and status == "lookup_disabled_by_config"
        report = lb.bridge_report("মস্তিষ্ক")
        assert report["status"] == "lookup_disabled_by_config"
        assert "band hai" in report["note"]
    finally:
        if saved is None:
            os.environ.pop("LANG_BRIDGE_LOOKUP", None)
        else:
            os.environ["LANG_BRIDGE_LOOKUP"] = saved


def test_romanisation_is_never_called_translation():
    """"мозга" -> "mozga" hai, "brain" NAHI. Report me ye farak likha rehna chahiye."""
    report = lb.bridge_report("как улучшить память и работу мозга", lookup=False)
    assert report["romanisation_is_not_translation"] is True
    assert "mozga" in report["roman"]
    assert "brain" not in report["roman"].lower()
    assert report["wiki_lang"] == "ru"


def test_the_bridge_report_never_carries_a_key_or_a_token():
    report = lb.bridge_report("মস্তিষ্ক", fetch=_fake_fetch({("bn", "মস্তিষ্ক"): "Brain"}))
    blob = repr(report).lower()
    for marker in ("api_key", "apikey", "token", "secret", "authorization"):
        assert marker not in blob


# ── E. wiring — pul asli pipeline me lagta hai ──────────────────────────────

def _function(source: str, name: str) -> ast.AST:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} nahi mila")


def test_the_orchestrator_builds_the_bridge_and_guards_it():
    """
    Anchor set karne ka kaam try/except me hona chahiye (pul ek sudhaar hai,
    zaroorat nahi) aur lens ka anchor mil gaya ho to hum usko chhedte nahi.
    """
    source = _read(os.path.join("research_engine", "orchestrator.py"))
    node = _function(source, "research")
    names = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
    assert "bridge_report" in names, "orchestrator pul banata hi nahi"
    guarded = False
    for handler in ast.walk(node):
        if not isinstance(handler, ast.Try):
            continue
        called = {n.attr for n in ast.walk(handler) if isinstance(n, ast.Attribute)}
        if "bridge_report" in called and handler.handlers:
            guarded = True
    assert guarded, "bridge_report bina try/except ke bulaya ja raha hai"
    assert "lens_scoring_query" in source
    assert "language_bridge" in source


def _bridge_try(source: str) -> ast.Try:
    """Wahi `try` block jisme bridge banta hai — poori file me dhoondhna dhoka
    hai (orchestrator me `warnings.append(strict_report["note"])` jaisi aur bhi
    lines hain, jo test ko jhoothi green de deti hain)."""
    node = _function(source, "research")
    for block in ast.walk(node):
        if not isinstance(block, ast.Try):
            continue
        called = {n.attr for n in ast.walk(block) if isinstance(n, ast.Attribute)}
        if "bridge_report" in called:
            return block
    raise AssertionError("bridge_report ka try block nahi mila")


def test_the_bridge_note_reaches_the_user_through_warnings():
    source = _read(os.path.join("research_engine", "orchestrator.py"))
    block = _bridge_try(source)
    appended = False
    for call in ast.walk(block):
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "append"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "warnings"):
            if any(isinstance(n, ast.Constant) and n.value == "note"
                   for n in ast.walk(call)):
                appended = True
    assert appended, "pul ki wajah user tak jaati hi nahi"


def test_the_bridge_anchor_never_overwrites_the_lens_anchor():
    """
    Lens ka anchor pehle se mil gaya ho to pul usko chhedta nahi. Isliye
    `set_scoring_anchor` wali line ka `if` khud `not lens_anchor` par tika hona
    chahiye — sirf "lens_anchor shabd file me hai" dekhna jhootha guard hai.
    """
    block = _bridge_try(_read(os.path.join("research_engine", "orchestrator.py")))
    guarded = False
    for node in ast.walk(block):
        if not isinstance(node, ast.If):
            continue
        body = " ".join(ast.unparse(stmt) for stmt in node.body)
        if "set_scoring_anchor" in body and "not lens_anchor" in ast.unparse(node.test):
            guarded = True
    assert guarded, "bridge anchor lens ke anchor ko overwrite kar sakta hai"


def test_semantic_similarity_is_the_single_place_the_bridge_is_applied():
    """
    Ek hi jagah — warna kal koi doosri jagah bina discount ke bridge laga dega.
    `relevance.py` aur `pdf_chunker.py` isi function ko bulate hain.
    """
    source = _read(os.path.join("research_engine", "semantic.py"))
    assert "_with_script_bridge" in source
    assert "needs_bridge" in source
    assert semantic._BRIDGE_TRUST < 1.0, "bridge match ko poora weight nahi milta"


# ── F. bhasha ka faisla sawaal ki script se ─────────────────────────────────

def test_wikisource_language_follows_the_question_script():
    saved = os.environ.pop("WIKISOURCE_LANGS", None)
    try:
        assert cc.langs_for_question("রামায়ণ কোথায় পাওয়া যায়") == ("en", "bn")
        assert cc.langs_for_question("रामायण का मूल पाठ") == ("en", "hi", "sa")
        assert cc.langs_for_question("where is the ramayana text") == ("en",)
        os.environ["WIKISOURCE_LANGS"] = "en,ta"
        langs = cc.langs_for_question("রামায়ণ")
        assert langs[:2] == ("en", "ta") and "bn" in langs
    finally:
        os.environ.pop("WIKISOURCE_LANGS", None)
        if saved is not None:
            os.environ["WIKISOURCE_LANGS"] = saved


def test_a_language_the_planner_picked_is_actually_built():
    """
    Facade construction ke waqt sawaal pata nahi hota. Naam ko chup-chaap gira
    dena = lane band, aur user ko kabhi pata na chalna ki uski bhasha ki wiki
    dekhi hi nahi gayi.
    """
    facade = cc.ClassicTextConnector()
    connector = facade.by_name("wikisource_bn")
    assert connector is not None and connector.lang == "bn"
    assert facade.by_name("wikisource_bn") is connector
    assert facade.by_name("wikisource_klingon") is None
    assert facade.by_name("wikisource_zz") is None


def test_every_bridge_language_host_is_on_the_allowlist():
    """Allowlist wildcard nahi leti — jo bhasha hum maang sakte hain, wo host ho."""
    for script, _s, _e, lang in lb._SCRIPTS:
        if not lang:
            continue
        assert f"{lang}.wikipedia.org" in cbase.DISCOVERY_ALLOWED_HOSTS, lang
    assert "en.wikipedia.org" in cbase.DISCOVERY_ALLOWED_HOSTS
    for lang in cc._KNOWN_LANGS:
        assert f"{lang}.wikisource.org" in cbase.DISCOVERY_ALLOWED_HOSTS, lang


def test_the_planner_asks_for_the_question_language():
    source = _read(os.path.join("research_engine", "planner.py"))
    assert "langs_for_question" in source
    assert "wikisource_langs()" not in source, (
        "planner ab bhi env-only list par chal raha hai")
