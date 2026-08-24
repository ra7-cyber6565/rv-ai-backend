"""ConceptLedger ke tests — task #83 (badhta hua concept ledger).

Ye file us module ke TEEN hard niyam pin karti hai (module docstring se hi):

  1. "Ye evidence nahi hai." — har entry aur har hint par ``verified`` False,
     aur ise True karne ka koi raasta module me nahi. File me koi haath se
     ``verified: true`` likh de to bhi load par wo maana nahi jaata.
  2. "Sirf jodta hai, kabhi kaatta nahi." — base plan ki koi query/naam ledger
     ke aane se gayab nahi hoti; lane khul sakti hai, band kabhi nahi.
  3. "Jo static list se pehle hi nikal aata hai, wo yaad nahi rakha jaata." —
     "granth"/"book"/"dharm"/"summary" jaise aam shabd andar hi nahi aate,
     warna ledger khud ko zeher de leta (har sawaal par galat lane).

Aur ek chauthi baat jise ye tests jaan-boojhkar naapte hain: ledger ka BIGADNA
research ko rok nahi sakta. Corrupt file, read-only folder, toota hua ledger
object, ya ``RV_CONCEPT_LEDGER=0`` — chaaron haalat me wapas wahi plan aata hai
jo ledger se pehle aata tha (kam nahi).

Naam yahan jaan-boojhkar wo liye gaye hain jo intel ne kabhi nahi bataye
(Muqaddimah, Canon of Medicine, Ibn Khaldun, Kitab al-Shifa) — kyunki poora
maqsad hi hand-typed list se azaadi hai.
"""
import contextlib
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import classics as C                     # noqa: E402
from research_engine import concept_ledger as G               # noqa: E402
from research_engine import lenses as L                       # noqa: E402
from research_engine.models import SourceRecord, SourceType   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_SOURCE_PATH = os.path.join(ROOT, "research_engine", "concept_ledger.py")
with open(LEDGER_SOURCE_PATH, "r", encoding="utf-8") as _handle:
    LEDGER_SOURCE = _handle.read()


@contextlib.contextmanager
def tmpdir():
    """Apna alag folder — asli ledger file kabhi test se chhui na jaaye."""
    path = tempfile.mkdtemp(prefix="concept_ledger_test_")
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@contextlib.contextmanager
def env(**pairs):
    """Env badlo aur PAKKA wapas kar do (2026-08-22 ka env-pollution sabak)."""
    old = {key: os.environ.get(key) for key in pairs}
    for key, value in pairs.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = str(value)
    G.reset_shared()
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        G.reset_shared()


def led(directory):
    return G.ConceptLedger(directory)


def rec(**kw):
    """Chhota SourceRecord."""
    return SourceRecord(
        title=kw.pop("title", "T"), url=kw.pop("url", ""),
        snippet=kw.pop("snippet", ""), connector=kw.pop("connector", "test"),
        source_type=kw.pop("source_type", SourceType.BOOK), **kw)


def teach(store, name, kind=G.KIND_WORK, lane=G.LANE_PRIMARY, times=G.MIN_CONFIRM):
    """Ek naam ko utni baar dikhao jitni baar lane confirm hone ke liye chahiye."""
    for _ in range(times):
        store.learn(name, kind, lane=lane, origin="test")
    return store


# ── 1. NIYAM 1: ye evidence nahi hai ────────────────────────────────────────

def test_module_has_no_way_to_set_verified_true():
    """Source me hi ``verified`` ko True karne ka koi raasta nahi hona chahiye."""
    for bad in ('"verified": True', "'verified': True",
                '["verified"] = True', "verified=True", "verified = True"):
        assert bad not in LEDGER_SOURCE, bad
    assert '"verified": False' in LEDGER_SOURCE


def test_stored_entry_is_always_unverified():
    with tmpdir() as path:
        store = led(path)
        assert store.learn("muqaddimah", G.KIND_WORK,
                           lane=G.LANE_PRIMARY)["stored"] is True
        entry = store.load()["concepts"]["muqaddimah"]
        assert entry["verified"] is False


def test_file_claiming_verified_true_is_not_believed():
    """Koi haath se file badle to bhi ledger verified True nahi maanta."""
    with tmpdir() as path:
        store = led(path)
        store.learn("canon of medicine", G.KIND_WORK, lane=G.LANE_PRIMARY)
        assert store.save() is True
        raw = json.load(open(store.path, encoding="utf-8"))
        raw["concepts"]["canon of medicine"]["verified"] = True
        with open(store.path, "w", encoding="utf-8") as handle:
            json.dump(raw, handle)
        fresh = led(path)
        assert fresh.load()["concepts"]["canon of medicine"]["verified"] is False


def test_hints_and_lane_plan_are_labelled_not_evidence():
    with tmpdir() as path:
        store = teach(led(path), "muqaddimah")
        hint = store.hints("muqaddimah me sabhyata ka chakra")
        assert hint["concepts"]
        assert hint["verified"] is False
        assert hint["is_evidence"] is False
        assert hint["evidence_status"] == G.NOT_EVIDENCE
        plan = store.lane_plan("muqaddimah me sabhyata ka chakra")
        assert plan["ledger"]["is_evidence"] is False
        assert plan["ledger"]["evidence_status"] == G.NOT_EVIDENCE
        assert plan["verified"] is False


def test_note_says_out_loud_that_nothing_was_read():
    with tmpdir() as path:
        store = teach(led(path), "muqaddimah")
        note = store.note(store.hints("muqaddimah me sabhyata"))
        assert "muqaddimah" in note.casefold()
        assert "padha" in note or "saabit" in note
        assert store.note({}) == ""
        assert store.note(None) == ""


def test_stats_never_reports_verified_knowledge():
    with tmpdir() as path:
        store = teach(led(path), "muqaddimah")
        stats = store.stats()
        assert stats["verified"] is False
        assert stats["evidence_status"] == G.NOT_EVIDENCE
        assert stats["concepts"] == 1
        assert stats["lane_confirmed"] == 1


def test_entry_schema_is_closed_and_has_no_content_fields():
    """Entry me sirf naam-level metadata — koi text, url, snippet, claim nahi."""
    with tmpdir() as path:
        store = led(path)
        store.learn("muqaddimah", G.KIND_WORK, lane=G.LANE_PRIMARY,
                    origin="question:work_candidate")
        entry = store.load()["concepts"]["muqaddimah"]
        assert set(entry) == {"concept", "kinds", "lanes", "origins",
                             "first_seen", "last_seen", "seen", "verified"}
        for banned in ("url", "text", "content", "snippet", "claim",
                       "confidence", "evidence"):
            assert banned not in entry


# ── 2. NIYAM 2: sirf jodta hai, kabhi kaatta nahi ───────────────────────────

def test_merge_keeps_whole_base_even_when_limit_is_smaller():
    out = G._merge_lists(["a", "b", "c", "d"], ["x"], limit=2)
    assert out[:4] == ["a", "b", "c", "d"]


def test_merge_never_reorders_or_drops_base():
    out = G._merge_lists(["muqaddimah", "canon of medicine"],
                         ["zohar", "muqaddimah"], limit=8)
    assert out[:2] == ["muqaddimah", "canon of medicine"]
    assert "zohar" in out
    assert len(out) == len(set(item.casefold() for item in out))


def test_ledger_never_removes_a_base_query_or_name():
    question = "ibn khaldun ki book muqaddimah me sabhyata ka chakra"
    base = C.lane_plan(question, limit=4)
    with tmpdir() as path:
        store = teach(led(path), "zohar")
        store.learn("zohar", G.KIND_WORK, lane=G.LANE_SUMMARY, origin="test")
        store.learn("zohar", G.KIND_WORK, lane=G.LANE_SUMMARY, origin="test")
        plan = store.lane_plan(question + " aur zohar", limit=4)
    for field in ("works", "people", "classic_queries", "summary_queries"):
        for item in base.get(field) or []:
            assert item in plan[field], (field, item)


def test_hint_name_never_pushes_a_base_person_query_out():
    """Asli khatra: naye naam ke liye jagah banane me base ki query kat jaaye.

    Is sawaal ka base plan = 1 work (2 query) + 1 person (1 query). Ledger ek
    doosra naam (kojiki) jodta hai. Agar queries dobara BANAI jaayein (jodi na
    jaayein) to limit=4 par do naam ki 4 work-query hi bachengi aur person wali
    query chup-chaap gayab ho jaayegi. Isliye yahan dono cheez pinned hain:
    base ki poori list bachi rahe, AUR naya naam sach me juda ho.
    """
    question = "ibn khaldun ka granth padhna hai kojiki ke saath"
    base = C.lane_plan(question, limit=4)
    assert base["wants_primary_text"] is True
    assert len(base["works"]) == 1 and base["people"]          # fixture pinned
    person_q = [q for q in base["classic_queries"] if "collected works" in q]
    assert person_q, base["classic_queries"]
    with tmpdir() as path:
        store = teach(led(path), "kojiki")
        plan = store.lane_plan(question, limit=4)
    for field in ("classic_queries", "summary_queries"):
        for item in base[field]:
            assert item in plan[field], (field, item)
    assert person_q[0] in plan["classic_queries"]
    added = [q for q in plan["classic_queries"] if "kojiki" in q.casefold()]
    assert added, plan["classic_queries"]
    assert len(plan["classic_queries"]) > len(base["classic_queries"])
    assert len(plan["summary_queries"]) > len(base["summary_queries"])


def test_hint_can_open_a_lane_but_never_close_one():
    """Base ne True kaha to hint (jo sirf summary jaanta hai) use False na kare."""
    question = "ibn khaldun ki book muqaddimah me sabhyata"
    assert C.lane_plan(question)["wants_primary_text"] is True
    with tmpdir() as path:
        store = led(path)
        for _ in range(G.MIN_CONFIRM):
            store.learn("muqaddimah", G.KIND_WORK, lane=G.LANE_SUMMARY,
                        origin="test")
        plan = store.lane_plan(question)
        assert plan["wants_primary_text"] is True
        assert plan["ledger_opened_lane"] is False       # base ne hi kholi thi


def test_ledger_opened_lane_flag_is_only_true_when_ledger_did_it():
    cueless = "muqaddimah me sabhyata ka chakra kya kehta hai"
    assert C.lane_plan(cueless)["wants_primary_text"] is False
    with tmpdir() as path:
        store = teach(led(path), "muqaddimah")
        plan = store.lane_plan(cueless)
        assert plan["wants_primary_text"] is True
        assert plan["ledger_opened_lane"] is True
        assert "muqaddimah" in [w.casefold() for w in plan["works"]]
        assert plan["classic_queries"]
        assert plan["summary_queries"]


def test_empty_ledger_leaves_the_base_plan_untouched():
    question = "muqaddimah me sabhyata ka chakra kya kehta hai"
    base = C.lane_plan(question, limit=4)
    with tmpdir() as path:
        plan = led(path).lane_plan(question, limit=4)
    assert plan["ledger_opened_lane"] is False
    assert plan["wants_primary_text"] == base["wants_primary_text"]
    assert plan["classic_queries"] == base["classic_queries"]
    assert plan["summary_queries"] == base["summary_queries"]


# ── 3. NIYAM 3: jo static rule se pehle hi nikalta hai, wo yaad nahi rehta ──

def test_generic_text_words_are_never_remembered():
    """Ledger ka aatm-ghaat yahi hota: "granth" yaad ho jaaye to har sawaal
    par mool-text lane khul jaayegi. Isliye ye sab andar hi nahi aate."""
    with tmpdir() as path:
        store = led(path)
        for word in ("granth", "book", "kitab", "summary", "vyakhya",
                     "padho", "text", "pustak"):
            out = store.learn(word, G.KIND_WORK, lane=G.LANE_PRIMARY)
            assert out["stored"] is False, word
            assert out["reason"], word
        assert store.load()["concepts"] == {}


def test_tradition_markers_are_never_remembered():
    """"dharm"/"veda" pehle se lenses ke marker hain — dohrana bekaar aur khatarnak."""
    with tmpdir() as path:
        store = led(path)
        for word in ("dharm", "veda", "quran", "philosophy"):
            if not L.tradition_hits(word):
                continue
            out = store.learn(word, G.KIND_PERSON, lane=G.LANE_PRIMARY)
            assert out["stored"] is False, word
            assert out["reason"] == "already_derivable", word


def test_question_words_are_never_remembered_alone_or_at_an_edge():
    with tmpdir() as path:
        store = led(path)
        for junk in ("kaise", "kaun", "what", "muqaddimah kis",
                     "kaise muqaddimah"):
            out = store.learn(junk, G.KIND_WORK, lane=G.LANE_PRIMARY)
            assert out["stored"] is False, junk
        assert store.load()["concepts"] == {}


def test_urls_numbers_and_fragments_are_rejected_with_named_reasons():
    cases = {"https://en.wikisource.org/wiki/X": "looks_like_url",
             "www.example.com/book": "looks_like_url",
             "1962": "no_letters",
             "of medicine": "edge_too_short",
             "the muqaddimah": "edge_stopword",
             "muqaddimah aur": "edge_stopword",
             "the": "too_short",
             "": "empty",
             "ek do teen chaar paanch chhah": "too_many_words"}
    for text, reason in cases.items():
        assert G.admission_reason(text) == reason, (text, G.admission_reason(text))
        assert G.is_admissible(text) is False, text


def test_real_unlisted_names_are_admitted():
    """Wo naam jo intel ne kabhi nahi bataye — inhe ledger yaad rakh sakta hai."""
    for name in ("muqaddimah", "canon of medicine", "ibn khaldun",
                 "kojiki", "mulamadhyamakakarika", "al-shifa"):
        assert G.admission_reason(name) == "", (name, G.admission_reason(name))


def test_a_rejection_is_never_silent():
    """Har reject ki NAAMIT wajah aati hai — warna probe me pakda nahi jaata."""
    with tmpdir() as path:
        store = led(path)
        out = store.learn("granth", G.KIND_WORK, lane=G.LANE_PRIMARY)
        assert out == {"stored": False, "reason": "already_derivable",
                       "concept": "granth"}
        assert store.learn("muqaddimah", "topic")["reason"] == "unknown_kind"
        assert store.learn("muqaddimah", G.KIND_WORK,
                           lane="full_text")["reason"] == "unknown_lane"


def test_unknown_kind_or_lane_stores_nothing_at_all():
    with tmpdir() as path:
        store = led(path)
        store.learn("muqaddimah", "topic")
        store.learn("muqaddimah", G.KIND_WORK, lane="full_text")
        assert store.load()["concepts"] == {}


def test_learn_is_the_only_admission_door():
    """Naya naam sirf ``learn`` se andar aata hai — koi doosra darwaza nahi."""
    body = LEDGER_SOURCE.split("class ConceptLedger", 1)[1]
    writers = [line.strip() for line in body.splitlines()
               if 'concepts[' in line and '=' in line and 'get(' not in line]
    assert len(writers) == 1, writers


# ── 4. MIN_CONFIRM: ek tukka research nahi kheench sakta ────────────────────

def test_min_confirm_is_two():
    assert G.MIN_CONFIRM == 2


def test_one_sighting_does_not_open_a_lane():
    cueless = "muqaddimah me sabhyata ka chakra kya kehta hai"
    with tmpdir() as path:
        store = teach(led(path), "muqaddimah", times=1)
        hint = store.hints(cueless)
        assert hint["concepts"]                      # naam yaad hai
        assert hint["wants_primary_text"] is False   # par lane nahi kholta
        assert store.lane_plan(cueless)["wants_primary_text"] is False


def test_second_sighting_of_the_same_lane_opens_it():
    cueless = "muqaddimah me sabhyata ka chakra kya kehta hai"
    with tmpdir() as path:
        store = teach(led(path), "muqaddimah", times=G.MIN_CONFIRM)
        hint = store.hints(cueless)
        assert hint["wants_primary_text"] is True
        assert hint["concepts"][0]["confirmed_lanes"] == [G.LANE_PRIMARY]


def test_two_different_lanes_do_not_add_up_to_a_confirmation():
    """Ek baar primary + ek baar summary = kisi lane ka confirm NAHI."""
    cueless = "muqaddimah me sabhyata ka chakra kya kehta hai"
    with tmpdir() as path:
        store = led(path)
        store.learn("muqaddimah", G.KIND_WORK, lane=G.LANE_PRIMARY)
        store.learn("muqaddimah", G.KIND_WORK, lane=G.LANE_SUMMARY)
        hint = store.hints(cueless)
        assert hint["concepts"]
        assert hint["wants_primary_text"] is False
        assert hint["summary_lane"] is False


def test_longer_phrase_wins_over_its_own_first_word():
    with tmpdir() as path:
        store = led(path)
        teach(store, "canon of medicine")
        teach(store, "canon")
        hint = store.hints("canon of medicine me bukhar ka ilaj")
        assert hint["works"][0] == "canon of medicine"


# ── 5. sawaal se seekhna (cue wala sawaal) ──────────────────────────────────

def test_question_with_a_cue_teaches_work_and_person():
    with tmpdir() as path:
        store = led(path)
        out = store.observe_question(
            "ibn khaldun ki book muqaddimah me sabhyata ka chakra")
        assert out["wants_primary_text"] is True
        assert out["verified"] is False
        low = [name.casefold() for name in out["learned"]]
        assert "muqaddimah" in low
        assert "ibn khaldun" in low
        entry = store.load()["concepts"]["muqaddimah"]
        assert entry["lanes"][G.LANE_PRIMARY] == 1
        assert entry["lanes"][G.LANE_SUMMARY] == 1   # copyright ka imaandaar raasta


def test_hinglish_head_final_question_still_teaches_the_name():
    """Hinglish me naam PEHLE aata hai: "muqaddimah granth me..." — isliye
    extraction ko peeche bhi dekhna padta hai, warna kuch seekha hi nahi jaata."""
    with tmpdir() as path:
        store = led(path)
        out = store.observe_question("muqaddimah granth me nyay ka niyam")
        assert "muqaddimah" in [name.casefold() for name in out["learned"]]


def test_a_question_word_never_becomes_a_work_name():
    """Purana defect: "muqaddimah kis" naam ban kar ledger me ghus gaya tha.

    Do parat par pin kiya hai: (a) classics khud aisa candidate banata hi nahi,
    (b) agar bana bhi de to ledger use andar nahi leta."""
    question = "muqaddimah granth kis niyam ki baat karta hai"
    for candidate in C.work_candidates(question):
        for word in candidate.split():
            assert not C.is_question_word(word), candidate
    with tmpdir() as path:
        store = led(path)
        store.observe_question(question)
        for key in store.load()["concepts"]:
            assert "kis" not in key.split()
            assert "kya" not in key.split()


def test_a_cueless_question_teaches_no_lane():
    """Ledger apni hi galti se lane nahi seekhta (feedback loop band).

    Sawaal me naam hai (quote me), par "asli text chahiye" ka koi cue nahi —
    isliye naam yaad hota hai, lane nahi."""
    question = '"vigyan bhairav" me shwas par kya kaha hai'
    assert C.text_intent(question)["wants_primary_text"] is False
    assert C.work_candidates(question)
    with tmpdir() as path:
        store = led(path)
        out = store.observe_question(question)
        assert out["learned"]
        for entry in store.load()["concepts"].values():
            assert entry["lanes"] == {}


def test_empty_question_learns_nothing():
    with tmpdir() as path:
        store = led(path)
        assert store.observe_question("")["learned"] == []
        assert store.observe_question("   ")["learned"] == []
        assert store.load()["concepts"] == {}


def test_rejected_names_come_back_with_reasons():
    with tmpdir() as path:
        out = led(path).observe_question("granth me kya likha hai")
        for item in out["rejected"]:
            assert item["reason"]


# ── 6. mile hue sources se seekhna (duniya se, list se nahi) ────────────────

def test_copyright_book_teaches_the_summary_lane_only():
    """intel ki shart: copyright book ignore nahi — uski summary dekho. Isliye
    aisi kitab ka naam SUMMARY lane sikhata hai, mool-text lane kabhi nahi."""
    book = rec(title="The Structure of Scientific Revolutions",
               url="https://www.amazon.com/dp/x", year=1962)
    assert C.copyright_stance(book)["verdict"] == C.COPYRIGHT_LIKELY
    with tmpdir() as path:
        store = led(path)
        for _ in range(G.MIN_CONFIRM):
            store.observe_sources([book])
        entry = list(store.load()["concepts"].values())[0]
        assert entry["lanes"].get(G.LANE_SUMMARY) == G.MIN_CONFIRM
        assert G.LANE_PRIMARY not in entry["lanes"]


def test_open_licensed_source_teaches_the_primary_text_lane():
    text = rec(title="Kitab al-Shifa: A Treatise",
               url="https://en.wikisource.org/wiki/Kitab_al-Shifa", year=1020)
    assert C.copyright_stance(text)["verdict"] in (C.PUBLIC_DOMAIN,
                                                  C.OPEN_LICENSED)
    with tmpdir() as path:
        store = led(path)
        for _ in range(G.MIN_CONFIRM):
            store.observe_sources([text])
        entry = list(store.load()["concepts"].values())[0]
        assert entry["lanes"].get(G.LANE_PRIMARY) == G.MIN_CONFIRM


def test_a_paper_or_webpage_teaches_nothing():
    """Book-jaisa nahi hai to ledger chhoo kar chhod deta hai (verdict unknown)."""
    paper = rec(title="Room-temperature superconductivity in a carbonaceous sulfur",
                url="https://arxiv.org/abs/2001.1", year=2020,
                source_type=SourceType.PAPER)
    with tmpdir() as path:
        store = led(path)
        out = store.observe_sources([paper])
        assert out["learned"] == []
        assert out["skipped"] == 1
        assert store.load()["concepts"] == {}


def test_titleless_source_is_skipped_not_guessed():
    with tmpdir() as path:
        store = led(path)
        out = store.observe_sources([rec(title="", url="https://x.org/a")])
        assert out["learned"] == []
        assert out["skipped"] == 1


def test_dict_shaped_records_work_too():
    """Job/queue se dict aata hai — usme bhi fields NAAM se padhe jaate hain."""
    payload = {"title": "Sapiens: A Brief History of Humankind",
               "url": "https://books.google.com/books?id=x", "year": 2011,
               "source_type": "book"}
    with tmpdir() as path:
        store = led(path)
        for _ in range(G.MIN_CONFIRM):
            store.observe_sources([payload])
        entries = store.load()["concepts"]
        assert entries
        entry = list(entries.values())[0]
        assert entry["lanes"].get(G.LANE_SUMMARY) == G.MIN_CONFIRM


def test_learned_title_name_is_only_words_from_that_title():
    """Naam title ke shabdon ka hi tukda hota hai — kuch gadha nahi jaata."""
    title = "The Structure of Scientific Revolutions"
    name = G._title_concept(title)
    assert name
    for word in name.split():
        assert word.casefold() in title.casefold().split()


def test_nothing_but_the_name_is_ever_written_to_disk():
    """File me url, snippet, ya content ka ek tukda bhi nahi jaata."""
    book = rec(title="Muqaddimah", url="https://www.amazon.com/dp/SECRETURL",
               snippet="SECRETSNIPPET about civilisation", year=1377)
    with tmpdir() as path:
        store = led(path)
        store.observe_sources([book])
        store.observe_question("ibn khaldun ki book muqaddimah me sabhyata")
        assert store.save() is True
        raw = open(store.path, encoding="utf-8").read()
        assert "SECRETURL" not in raw
        assert "SECRETSNIPPET" not in raw
        assert "amazon.com" not in raw
        assert "muqaddimah" in raw.casefold()


def test_repeated_corpus_author_is_remembered_without_a_lane():
    """Do alag family me mila lekhak yaad rehta hai — par lane NAHI kholta.

    Wajah: lekhak ka naam dikhna ye nahi batata ki uska mool text chahiye.
    """
    papers = [rec(title="A study of cuprate pairing", url="https://arxiv.org/abs/1",
                  source_type=SourceType.PAPER, authors=["Hideo Hosono"],
                  methodology="experiment"),
              rec(title="Iron pnictide superconductors", url="https://nature.com/x",
                  source_type=SourceType.PAPER, authors=["Hideo Hosono"],
                  methodology="simulation")]
    assert L.author_thinkers(papers, min_repeat=2) == ["Hideo Hosono"]
    with tmpdir() as path:
        store = led(path)
        out = store.observe_sources(papers)
        assert "Hideo Hosono" in out["learned"]
        entry = store.load()["concepts"]["hideo hosono"]
        assert entry["lanes"] == {}   # lekhak ka naam lane nahi kholta
        assert entry["kinds"] == {G.KIND_PERSON: 1}
        assert store.hints("hideo hosono ka kaam")["wants_primary_text"] is False


# ── 7. storage: file bigde to research na ruke ──────────────────────────────

def test_corrupt_file_gives_a_blank_ledger_not_a_crash():
    with tmpdir() as path:
        store = led(path)
        os.makedirs(path, exist_ok=True)
        with open(store.path, "w", encoding="utf-8") as handle:
            handle.write("{not json at all")
        assert store.load()["concepts"] == {}
        assert store.hints("muqaddimah me sabhyata")["concepts"] == []


def test_entries_of_a_wrong_shape_are_dropped_on_load():
    with tmpdir() as path:
        store = led(path)
        os.makedirs(path, exist_ok=True)
        with open(store.path, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "concepts": {
                "muqaddimah": {"concept": "muqaddimah",
                               "kinds": {"work": 2}, "lanes": {"primary_text": 2}},
                "granth": {"concept": "granth", "kinds": {"work": 9},
                           "lanes": {"primary_text": 9}},
                "nokind": {"concept": "zohar", "kinds": {}, "lanes": {}},
                "junk": "not-a-dict"}}, handle)
        concepts = store.load()["concepts"]
        assert set(concepts) == {"muqaddimah"}      # granth/junk andar nahi aate


def test_an_unwritable_directory_returns_false_and_never_raises():
    """Read-only folder par save() False deta hai, exception bahar nahi jaati.

    Windows/root par chmod ko OS khud maan nahi sakta — us haalat me ye test
    kam se kam ye pin karta hai ki return sirf bool hai aur True kehne par file
    asli me maujood hai (jhoothi haami nahi).
    """
    with tmpdir() as path:
        blocked = os.path.join(path, "blocked")
        os.makedirs(blocked, exist_ok=True)
        store = led(os.path.join(blocked, "inner"))
        store.learn("muqaddimah", G.KIND_WORK, lane=G.LANE_PRIMARY)
        os.chmod(blocked, 0o500)
        try:
            saved = store.save()
            assert saved in (True, False)
            if saved:
                assert os.path.exists(store.path)
            else:
                assert not os.path.exists(store.path)
            # Ledger bigda ho ya na ho, yaad hui cheez wapas milti rehti hai.
            assert store.hints("muqaddimah me sabhyata")["concepts"] != []
        finally:
            os.chmod(blocked, 0o700)


def test_save_leaves_no_temp_file_behind():
    with tmpdir() as path:
        store = led(path)
        store.learn("muqaddimah", G.KIND_WORK, lane=G.LANE_PRIMARY)
        assert store.save() is True
        names = os.listdir(store.directory)
        assert os.path.basename(store.path) in names
        assert not any(name.startswith("ledger_") for name in names)


def test_two_stale_workers_merge_different_concepts_instead_of_last_writer_wins():
    """Purana bug: doosre worker ka save pehle worker ka naam mita deta tha."""
    with tmpdir() as path:
        first, second = led(path), led(path)
        assert first.load()["concepts"] == {}
        assert second.load()["concepts"] == {}       # dono stale snapshot
        first.learn("muqaddimah", G.KIND_WORK, lane=G.LANE_PRIMARY)
        second.learn("zohar", G.KIND_WORK, lane=G.LANE_PRIMARY)
        assert first.save() is True
        assert second.save() is True
        assert set(led(path).load()["concepts"]) == {"muqaddimah", "zohar"}


def test_two_stale_workers_merge_counts_for_the_same_concept():
    """Merge sirf keys ka nahi; confirmation count bhi lost-update safe hai."""
    with tmpdir() as path:
        first, second = led(path), led(path)
        first.load()
        second.load()
        first.learn("muqaddimah", G.KIND_WORK, lane=G.LANE_PRIMARY)
        second.learn("muqaddimah", G.KIND_WORK, lane=G.LANE_PRIMARY)
        assert first.save() is True
        assert second.save() is True
        entry = led(path).load()["concepts"]["muqaddimah"]
        assert entry["seen"] == 2
        assert entry["lanes"][G.LANE_PRIMARY] == 2


def test_cached_reader_refreshes_after_another_worker_saves():
    """Long-running Railway worker ko doosre worker ki nayi memory dikhe."""
    with tmpdir() as path:
        reader, writer = led(path), led(path)
        assert reader.hints("muqaddimah me sabhyata")["concepts"] == []
        teach(writer, "muqaddimah")
        assert writer.save() is True
        assert reader.hints("muqaddimah me sabhyata")["concepts"]


def test_single_huge_token_cannot_break_the_byte_bound():
    with tmpdir() as path:
        store = led(path)
        result = store.learn("x" * (G.MAX_CONCEPT_CHARS + 1), G.KIND_WORK,
                             lane=G.LANE_PRIMARY)
        assert result["stored"] is False
        assert result["reason"] == "too_long"
        assert store.load()["concepts"] == {}


def test_ledger_stays_bounded_and_keeps_the_names_it_saw_most():
    with tmpdir() as path:
        store = led(path)
        for index in range(G.MAX_CONCEPTS + 25):
            store.learn("concept%04d" % index, G.KIND_WORK, lane=G.LANE_PRIMARY)
        for _ in range(5):
            store.learn("concept0000", G.KIND_WORK, lane=G.LANE_PRIMARY)
        assert store.save() is True
        fresh = led(path).load()["concepts"]
        assert len(fresh) == G.MAX_CONCEPTS
        assert "concept0000" in fresh


def test_filename_cannot_escape_its_own_folder():
    store = G.ConceptLedger("/tmp/ledger_probe", filename="../../etc/passwd")
    assert os.path.dirname(store.path) == store.directory


def test_no_secret_value_can_reach_the_ledger_file():
    with tmpdir() as path:
        with env(GEMINI_API_KEY="AIzaFAKEKEYVALUE123", CONCEPT_LEDGER_DIR=path):
            store = G.shared()
            G.remember_question("ibn khaldun ki book muqaddimah me sabhyata")
            raw = open(store.path, encoding="utf-8").read()
        assert "AIzaFAKEKEYVALUE123" not in raw
        assert "GEMINI_API_KEY" not in raw


# ── 8. kill switch + fail-safe (ledger ka bigadna research na roke) ─────────

def test_kill_switch_gives_exactly_the_old_behaviour():
    cueless = "muqaddimah me sabhyata ka chakra kya kehta hai"
    with tmpdir() as path:
        with env(CONCEPT_LEDGER_DIR=path):
            teach(G.shared(), "muqaddimah")
            assert G.shared().save() is True
            assert G.lane_plan(cueless)["wants_primary_text"] is True
        with env(CONCEPT_LEDGER_DIR=path, RV_CONCEPT_LEDGER="0"):
            assert G.enabled() is False
            plan = G.lane_plan(cueless)
            base = C.lane_plan(cueless)
            assert plan["ledger"]["enabled"] is False
            assert plan["ledger_opened_lane"] is False
            assert plan["wants_primary_text"] == base["wants_primary_text"]
            assert plan["classic_queries"] == base["classic_queries"]
            assert G.remember_question(cueless)["learned"] == []
            assert G.remember_sources([rec(title="Muqaddimah")])["learned"] == []
            assert G.hints(cueless)["concepts"] == []


def test_kill_switch_accepts_the_usual_off_spellings():
    for value in ("0", "false", "no", "off", "OFF", "False"):
        with env(RV_CONCEPT_LEDGER=value):
            assert G.enabled() is False, value
    for value in ("1", "true", "yes", "on"):
        with env(RV_CONCEPT_LEDGER=value):
            assert G.enabled() is True, value


class _BrokenLedger:
    """Har raaste par phatne wala ledger — pipeline ko phir bhi chalna chahiye."""

    def lane_plan(self, question, limit=4):
        raise RuntimeError("ledger file khul hi nahi rahi")

    def observe_question(self, question):
        raise RuntimeError("boom")

    def observe_sources(self, records):
        raise RuntimeError("boom")

    def hints(self, question):
        raise RuntimeError("boom")


def test_a_broken_ledger_falls_back_to_the_base_plan():
    question = "ibn khaldun ki book muqaddimah me sabhyata ka chakra"
    base = C.lane_plan(question, limit=4)
    plan = G.lane_plan(question, limit=4, ledger=_BrokenLedger())
    assert plan["ledger"]["error"] == "ledger_unavailable"
    assert plan["ledger_opened_lane"] is False
    assert plan["wants_primary_text"] == base["wants_primary_text"]
    assert plan["classic_queries"] == base["classic_queries"]
    assert plan["works"] == base["works"]


def test_broken_ledger_learning_calls_never_raise():
    broken = _BrokenLedger()
    for out in (G.remember_question("muqaddimah me sabhyata", ledger=broken),
                G.remember_sources([rec(title="Muqaddimah")], ledger=broken)):
        assert out["learned"] == []
        assert out["saved"] is False
        assert out["error"] == "ledger_unavailable"
    assert G.hints("muqaddimah", ledger=broken) == G._blank_hint()


def test_module_level_api_survives_junk_input():
    """Khaali/kachra input par bhi shape poori aati hai aur kuch seekha nahi jaata."""
    with tmpdir() as path:
        with env(CONCEPT_LEDGER_DIR=path):
            for junk in ("", "   ", "12345", "???"):
                plan = G.lane_plan(junk)
                assert isinstance(plan["ledger_opened_lane"], bool)
                assert plan["ledger_opened_lane"] is False
                assert G.remember_question(junk)["learned"] == []
            assert G.remember_sources(None)["learned"] == []
            assert G.remember_sources([None, 5, "x"])["learned"] == []
            assert G.shared().load()["concepts"] == {}


def test_shared_instance_is_reused_and_resettable():
    with tmpdir() as path:
        with env(CONCEPT_LEDGER_DIR=path):
            first = G.shared()
            assert G.shared() is first
            G.reset_shared()
            assert G.shared() is not first
            assert G.shared(path) is not G.shared()   # explicit dir = alag instance


def test_ledger_imports_no_model_or_network_library():
    """₹0 aur offline: is module me na network, na koi model client aata hai."""
    for banned in ("requests", "httpx", "urllib", "google.generativeai",
                   "genai", "gemini_reasoning", "openai", "socket",
                   "chromadb", "sentence_transformers"):
        assert banned not in LEDGER_SOURCE, banned
    assert "import json" in LEDGER_SOURCE


# ── 9. wiring: planner aur orchestrator ─────────────────────────────────────

def test_planner_reports_who_opened_the_classic_lane():
    from research_engine.depth import get_depth_config
    from research_engine.planner import ResearchPlanner
    cueless = "muqaddimah me sabhyata ka chakra kya kehta hai"
    planner = ResearchPlanner()
    config = get_depth_config("QUICK")
    with tmpdir() as path:
        with env(CONCEPT_LEDGER_DIR=path):
            plan = planner.connector_plan(planner.classify(cueless), config,
                                          cueless)
            lane = plan["classic_lane"]
            assert lane["ledger_opened_lane"] is False
            assert lane["ledger"]["evidence_status"] == G.NOT_EVIDENCE

            for _ in range(G.MIN_CONFIRM):
                G.remember_question(
                    "ibn khaldun ki book muqaddimah me sabhyata ka chakra")
            plan = planner.connector_plan(planner.classify(cueless), config,
                                          cueless)
            lane = plan["classic_lane"]
            assert lane["wants_primary_text"] is True
            assert lane["ledger_opened_lane"] is True
            assert lane["verified"] is False
            assert plan["classic_queries"]
            assert plan["classics"]


def test_planner_plan_without_the_ledger_is_never_smaller():
    from research_engine.depth import get_depth_config
    from research_engine.planner import ResearchPlanner
    question = "ibn khaldun ki book muqaddimah me sabhyata ka chakra"
    planner = ResearchPlanner()
    config = get_depth_config("QUICK")
    with tmpdir() as path:
        with env(CONCEPT_LEDGER_DIR=path, RV_CONCEPT_LEDGER="0"):
            off = planner.connector_plan(planner.classify(question), config,
                                         question)
        with env(CONCEPT_LEDGER_DIR=path):
            teach(G.shared(), "zohar")
            on = planner.connector_plan(planner.classify(question), config,
                                        question)
    for field in ("classic_queries", "summary_queries"):
        for item in off.get(field) or []:
            assert item in (on.get(field) or []), (field, item)


def test_orchestrator_learns_after_the_run_and_inside_a_try():
    """Structure test: hook memory.save() ke BAAD hai, try ke andar hai, aur
    ``self.memory`` ke bahar hai — yaani memory band ho ya ledger phat jaaye,
    answer par koi asar nahi."""
    path = os.path.join(ROOT, "research_engine", "orchestrator.py")
    source = open(path, encoding="utf-8").read()
    assert "from . import concept_ledger" in source
    save_at = source.index("self.memory.save()")
    learn_at = source.index("concept_ledger.remember_question(")
    assert save_at < learn_at
    block = source[learn_at - 400:learn_at]
    assert "try:" in block
    tail = source[learn_at:learn_at + 400]
    assert "concept_ledger.remember_sources(" in tail
    assert "except Exception" in tail
    save_line = source[:save_at].rsplit("\n", 1)[-1]
    try_line = [line for line in block.splitlines() if line.strip() == "try:"][-1]
    assert (len(try_line) - len(try_line.lstrip())
            < len(save_line) - len(save_line.lstrip()))


def test_ledger_result_is_never_turned_into_a_claim_or_confidence():
    """CODE me (comment/docstring nahi) claim/confidence banane wala naam hi nahi."""
    import ast
    tree = ast.parse(LEDGER_SOURCE)
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    doc_nodes = set()
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = list(getattr(node, "body", []) or [])
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            doc_nodes.add(id(body[0].value))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in doc_nodes:
                names.add(node.value)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.add(getattr(node, "module", "") or "")
            for alias in node.names:
                names.add(alias.name)
    for banned in ("claimverification", "confidence", "evidence_level",
                   "claim_label", "verify", "probability"):
        assert not any(banned in str(name).casefold()
                       for name in names), banned


def test_pipeline_round_trip_learns_then_opens_the_lane():
    """Poora chakkar: pehle cue wale sawaal, phir bina cue wala sawaal khud khule."""
    cued = "nagarjuna ka granth mulamadhyamakakarika me shunyata"
    cueless = "mulamadhyamakakarika me shunyata ka arth kya hai"
    assert C.lane_plan(cueless)["wants_primary_text"] is False
    with tmpdir() as path:
        with env(CONCEPT_LEDGER_DIR=path):
            for _ in range(G.MIN_CONFIRM):
                assert G.remember_question(cued)["saved"] is True
            G.reset_shared()                      # naya process jaisa
            plan = G.lane_plan(cueless)
            assert plan["wants_primary_text"] is True
            assert plan["ledger_opened_lane"] is True
            assert any("mulamadhyamakakarika" in query.casefold()
                       for query in plan["classic_queries"])
            assert plan["ledger"]["note"]
            assert plan["ledger"]["verified"] is False
