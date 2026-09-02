"""Classic/mool-text lane ke tests — task #84 (classics.py + wiring).

Ye file intel ki do shartein pin karti hai, unke apne shabdon se:

  1. "rahi copyright book ki baat to jo book copy right ho uski summary dekh lo
     ya or lokal kisi ne pdf ya kahi or de rkha wo explane de rkha ho usko dekh
     lo ignore chhodo mt"
     → copyright book ka MOOL TEXT kabhi fetch nahi hota, par usko IGNORE bhi
     nahi kiya jaata: uski summary/vyakhya lane chalti hai aur label par saaf
     likha rehta hai ki book padhi nahi gayi.

  2. "mene jitne bhi topic mathmetic ya jo bhi books vegyanik ka naam btaya h
     sirf unhe hi mt add krna ... unke baare me app khud se soch reserch kr ske
     waisa bhi bnana"
     → lane detection kisi granth/lekhak ki LIST se nahi hoti. Isliye yahan
     jaan-boojhkar wo naam use hue hain jo intel ne kabhi nahi bataye (Talmud,
     Torah, Avesta, Zohar, Kojiki, Ramanujan ke notebooks).

Teesri baat, jo isi module ki jaan hai: **naam lena padhna nahi hai.** Har lane
plan par ``verified is False`` rehta hai, aur read level ``read_ceiling`` se
aage structurally ja hi nahi sakta — isliye "FULL TEXT ACCESSED" jhooth bolna
namumkin hai, sirf mana hua nahi.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import classics as C                    # noqa: E402
from research_engine import content_fetcher as CFM           # noqa: E402
from research_engine.depth import get_depth_config           # noqa: E402
from research_engine.models import (EvidencePack,            # noqa: E402
                                    READ_LEVEL_ORDER,
                                    SourceRecord, SourceType)
from research_engine.planner import ResearchPlanner          # noqa: E402
from research_engine.source_discovery import SourceDiscovery  # noqa: E402


def rec(url="", **kw):
    """Chhota SourceRecord banane wala helper."""
    return SourceRecord(
        title=kw.pop("title", "T"), url=url,
        snippet=kw.pop("snippet", ""), connector=kw.pop("connector", "test"),
        source_type=kw.pop("source_type", SourceType.BOOK), **kw)


def stance(url="", **kw):
    return C.copyright_stance(rec(url, **kw))


# ── 1. rule ORDER — pirate/commercial pehle, licence-daava baad me ───────────

def test_unauthorised_host_never_allowed():
    out = stance("https://libgen.is/book/index.php?md5=x")
    assert out["rule"] == "unauthorised_host"
    assert out["full_text_allowed"] is False
    assert out["read_ceiling"] == "metadata"
    assert out["summary_lane"] is True


def test_pirate_host_claiming_public_domain_still_refused():
    """Rule order ka asli test: shadow library snippet me "public domain" likh
    de to bhi chhoot nahi milti. Agar `declared_open_licence` galti se pehle
    aa jaaye, ye test red hoga."""
    out = stance("https://libgen.rs/get.php?md5=y",
                 snippet="This is a public domain scan, CC0")
    assert out["rule"] == "unauthorised_host"
    assert out["full_text_allowed"] is False


def test_commercial_host_is_snippet_only():
    out = stance("https://books.google.com/books?id=abc")
    assert out["rule"] == "commercial_host"
    assert out["full_text_allowed"] is False
    assert out["read_ceiling"] == "snippet"
    assert out["summary_lane"] is True


def test_public_domain_library_full_text():
    out = stance("https://www.gutenberg.org/ebooks/2383")
    assert out["rule"] == "public_domain_library"
    assert out["full_text_allowed"] is True
    assert out["read_ceiling"] == "full_text"
    assert out["summary_lane"] is False


def test_open_licensed_wikimedia_full_text():
    for url in ("https://en.wikisource.org/wiki/Rig_Veda",
                "https://sa.wikisource.org/wiki/ऋग्वेद",
                "https://en.wikibooks.org/wiki/Sanskrit"):
        out = stance(url)
        assert out["rule"] == "open_licensed_host", url
        assert out["full_text_allowed"] is True, url


def test_old_publication_beats_book_type():
    out = stance("https://someblog.example.com/book.pdf", year=1899)
    assert out["rule"] == "old_publication"
    assert out["full_text_allowed"] is True


def test_modern_book_is_summary_lane_not_ignored():
    out = stance("https://someblog.example.com/book.pdf", year=1960)
    assert out["rule"] == "modern_book"
    assert out["full_text_allowed"] is False
    assert out["read_ceiling"] == "abstract"
    # "ignore chhodo mt" — summary lane ON hoti hai, source phenka nahi jaata
    assert out["summary_lane"] is True


def test_book_without_year_says_publisher_in_reason():
    out = stance("https://someblog.example.com/x.pdf",
                 publisher="Unknown House Pvt Ltd")
    assert out["rule"] == "book_unknown_year"
    assert out["full_text_allowed"] is False
    assert "Unknown House" in out["reason"]


def test_declared_open_licence_opens_a_modern_book():
    """OER textbook / CC-BY monograph purane `.pdf` route se padhi ja rahi thi.
    Route-0 guard use band kar deta, isliye licence-daava wala rule zaroori
    hai — aur wo daava source ke APNE metadata se aata hai, kisi book-list se
    nahi."""
    out = stance("https://openpress.example.edu/statistics.pdf", year=2020,
                 publisher="OpenPress, licensed CC BY 4.0")
    assert out["rule"] == "declared_open_licence"
    assert out["full_text_allowed"] is True
    assert out["read_ceiling"] == "full_text"


def test_licence_marker_needs_word_boundary():
    """"oer" shabd "coerce"/"Boer" ke andar bhi milta hai. Substring matching
    hoti to ye modern book ka mool text khol deti."""
    out = stance("https://press.example.com/book.pdf", year=1985,
                 publisher="Coercive Goer Press, Boer edition")
    assert out["rule"] == "modern_book"
    assert out["full_text_allowed"] is False
    assert C._licence_marker("Coercive Goer Press, Boer edition") == ""
    assert C._licence_marker("released under CC BY 4.0") == "cc by"


def test_host_gated_archive_stays_readable():
    out = stance("https://archive.org/details/somebook", year=1994)
    assert out["rule"] == "host_gated_archive"
    assert out["full_text_allowed"] is True
    # naya item hai, isliye summary lane BHI saath chalti hai
    assert out["summary_lane"] is True


def test_non_book_sources_get_no_new_restriction():
    """Ye module ka fail-safe default: paper/dataset/webpage/user-PDF par koi
    nayi rok NAHI. Isi wajah se poori purani pipeline (374/594/649/156/325)
    waisi hi chalti rahi."""
    for kind in (SourceType.PAPER, SourceType.WEB, SourceType.DATASET,
                 SourceType.DOCUMENT):
        out = stance("https://arxiv.org/abs/2401.00001", source_type=kind,
                     year=2024, publisher="Elsevier")
        assert out["rule"] == "not_book_like", kind
        assert out["full_text_allowed"] is True, kind
        assert out["read_ceiling"] == "full_text", kind


def test_stance_has_no_credential_or_url_leak_fields():
    out = stance("https://libgen.is/x?key=SECRET123")
    assert "SECRET123" not in " ".join(str(v) for v in out.values())


# ── 2. read ceiling = structural honesty ─────────────────────────────────────

def test_cap_read_level_lowers_but_never_raises():
    low = {"read_ceiling": "abstract"}
    assert C.cap_read_level("full_text", low) == "abstract"
    assert C.cap_read_level("snippet", low) == "snippet"
    high = {"read_ceiling": "full_text"}
    assert C.cap_read_level("snippet", high) == "snippet"


def test_cap_read_level_ignores_garbage_ceiling():
    assert C.cap_read_level("full_text", {"read_ceiling": "banana"}) == "full_text"
    assert C.cap_read_level("full_text", {}) == "full_text"


def test_full_text_is_the_top_of_the_order():
    assert READ_LEVEL_ORDER[-1] == "full_text"


def test_read_note_speaks_when_read_was_capped():
    st = {"full_text_allowed": True, "read_ceiling": "abstract"}
    note = C.read_note(st, "abstract")
    assert "abstract" in note and note.strip()
    # bina cap wala normal read chup rehta hai (shor nahi)
    assert C.read_note({"full_text_allowed": True,
                        "read_ceiling": "full_text"}, "full_text") == ""


def test_read_note_for_copyright_book_says_text_not_read():
    note = C.read_note({"full_text_allowed": False,
                        "verdict": C.COPYRIGHT_LIKELY})
    assert note == C.SUMMARY_LANE_NOTE
    assert "nahi padha" in note


# ── 3. lane detection — bina LIST, bina model ────────────────────────────────

UNLISTED = [
    "talmud aur torah me nyay ka niyam kya likha hai",
    "avesta ke shlok me aag ka matlab",
    "zohar granth me kya likha hai",
    "kojiki text me srishti ki katha",
    "ramanujan ke notebooks me kya tha",
]


def test_lane_opens_for_names_never_hardcoded():
    for question in UNLISTED:
        plan = C.lane_plan(question)
        assert plan["wants_primary_text"] is True, question
        assert plan["classic_queries"], question
        assert plan["summary_queries"], question


def test_lane_is_model_free_and_never_claims_verification():
    plan = C.lane_plan(UNLISTED[0])
    assert plan["model_used"] is False
    assert plan["method"] == "deterministic_classics"
    assert plan["verified"] is False
    assert "no_text_was_read" in plan["evidence_status"]


def test_ordinary_question_opens_no_text_lane():
    for question in ("quantum entanglement kaise kaam karta hai",
                     "dimag tez kaise kare",
                     "india ka gdp 2024 me kitna tha"):
        plan = C.lane_plan(question)
        assert plan["wants_primary_text"] is False, question
        assert plan["classic_queries"] == [], question
        assert plan["summary_queries"] == [], question


def test_two_lanes_ask_different_things():
    plan = C.lane_plan("vivekananda ki book raja yoga ka asli text padhna hai")
    assert any("full text" in q for q in plan["classic_queries"])
    assert all("full text public domain" not in q
               for q in plan["summary_queries"])
    assert any(("summary" in q or "explained" in q or "free to read" in q)
               for q in plan["summary_queries"])


def test_lane_plan_is_deterministic():
    assert C.lane_plan(UNLISTED[4]) == C.lane_plan(UNLISTED[4])


def test_read_cue_alone_does_not_open_the_lane():
    """"padhna" har jagah aata hai. Akela read-cue lane khole to har sawaal par
    do bekaar queries chal jaatin."""
    assert C.text_intent("ye article padhna hai")["wants_primary_text"] is False


# ── 4. planner wiring (additive) ─────────────────────────────────────────────

P = ResearchPlanner()


def plan_for(question, mode="DEEP"):
    config = get_depth_config(mode)
    return P.connector_plan(P.classify(question), config, question)


def test_planner_runs_text_tier_for_a_granth_question():
    plan = plan_for(UNLISTED[0])
    assert plan["classics"], "mool-text tier chalna chahiye tha"
    assert plan["classic_queries"] and plan["summary_queries"]
    assert plan["classic_lane"]["wants_primary_text"] is True
    assert plan["classic_lane"]["verified"] is False


def test_planner_text_tier_does_not_depend_on_book_keyword_list():
    """Pehla gate `use_books or needs_books` tha. DEEP me `use_books=False` hai,
    aur is sawaal par koi book-keyword hit nahi hota — isliye saaf public-domain
    granth par tier chup-chaap band reh jaata tha."""
    question = "talmud aur torah me nyay ka niyam kya hai"
    config = get_depth_config("DEEP")
    assert config.use_books is False
    cls = P.classify(question)
    assert cls["needs_books"] is False
    assert C.lane_plan(question)["wants_primary_text"] is True
    plan = P.connector_plan(cls, config, question)
    assert plan["classics"], "lane khud detect kar chuki thi, phir bhi tier band"
    assert plan["books"], "mool text ka doosra raasta (archive/openlibrary) bhi khule"


def test_planner_adds_nothing_for_an_ordinary_question():
    plan = plan_for("quantum entanglement kaise kaam karta hai")
    assert plan["classics"] == []
    assert plan["classic_queries"] == []
    assert plan["summary_queries"] == []
    assert plan["classic_lane"]["wants_primary_text"] is False
    assert "ishara nahi mila" in plan["classic_lane"]["note"]


def test_text_lane_budget_follows_what_can_actually_be_read():
    """Depth lane ko BAND nahi karti, CHHOTI karti hai. QUICK sirf 1 source ka
    full text padh sakta hai (max_fulltext=1), to 2 mool-text candidate maangna
    sirf budget kharch karna hai."""
    quick = plan_for(UNLISTED[0], "QUICK")
    deep = plan_for(UNLISTED[0], "DEEP")
    assert get_depth_config("QUICK").max_fulltext == 1
    assert len(quick["classic_queries"]) == 1
    assert len(quick["summary_queries"]) == 1
    assert len(deep["classic_queries"]) == 2
    assert quick["classics"] == deep["classics"]


def test_planner_plan_is_deterministic():
    assert plan_for(UNLISTED[2]) == plan_for(UNLISTED[2])


def test_classic_lane_note_never_claims_evidence():
    plan = plan_for(UNLISTED[1])
    low = plan["classic_lane"]["note"].casefold()
    for lie in ("verified", "saabit", "proved", "padh liya"):
        assert lie not in low


# ── 5. source_discovery wiring (additive) ────────────────────────────────────

SD = SourceDiscovery()


def labels_for(plan, query="test query"):
    return [label for label, _fn in SD._tasks([query], plan, 3, 5)]


def test_discovery_runs_both_lanes_for_a_granth_plan():
    plan = plan_for(UNLISTED[0])
    labels = labels_for(plan)
    assert any("wikisource" in label for label in labels)
    assert "classic_summary_web" in labels


def test_discovery_ignores_a_plan_without_the_new_keys():
    """Purana plan dict (jisme `classics` key hi nahi) toota nahi chahiye —
    orchestrator ke kisi bhi purane raaste se aaya plan chalta rahe."""
    old = {"web": True, "papers": [], "books": [], "datasets": [],
           "patents": []}
    assert labels_for(old) == ["web_chain"]


def test_summary_lane_needs_the_web_tier():
    plan = dict(plan_for(UNLISTED[0]))
    plan["web"] = False
    labels = labels_for(plan)
    assert "classic_summary_web" not in labels
    assert any("wikisource" in label for label in labels)


def test_duplicate_classic_queries_are_not_searched_twice():
    plan = dict(plan_for(UNLISTED[0]))
    plan["classic_queries"] = ["ved full text", "VED FULL TEXT", ""]
    plan["summary_queries"] = ["ved summary", "ved summary"]
    labels = labels_for(plan)
    assert len([x for x in labels if "wikisource" in x]) == 1
    assert labels.count("classic_summary_web") == 1


def test_classic_tier_is_off_when_no_classic_connector_named():
    plan = dict(plan_for("quantum entanglement kaise kaam karta hai"))
    assert not any("wikisource" in label for label in labels_for(plan))


# ── 6. content_fetcher route 0 — guard sabse pehle ───────────────────────────

CF = CFM.ContentFetcher(allow_network=True)


def test_route0_blocks_copyright_book_before_any_fetch_route():
    plan = CF.resolve(rec("https://libgen.is/book/x.pdf"))
    assert plan["ok"] is False
    assert plan["copyright_stance"]["rule"] == "unauthorised_host"
    assert plan["summary_lane"] is True
    assert plan["read_ceiling"] == "metadata"


def test_route0_blocks_modern_book_pdf_that_used_to_be_fetched():
    plan = CF.resolve(rec("https://someblog.example.com/book.pdf", year=1975))
    assert plan["ok"] is False
    assert plan["read_ceiling"] == "abstract"
    assert plan["summary_lane"] is True


def test_route0_lets_an_open_licensed_modern_book_through():
    plan = CF.resolve(rec("https://openpress.example.edu/stats.pdf", year=2021,
                          publisher="OpenPress, CC BY 4.0"))
    assert plan["ok"] is True
    assert plan["kind"] == "pdf"


def test_route0_does_not_touch_ordinary_paper_pdfs():
    plan = CF.resolve(rec("https://journals.example.org/paper.pdf",
                          source_type=SourceType.PAPER, year=2024))
    assert plan["ok"] is True


def test_wikisource_uses_the_official_api():
    plan = CF.resolve(rec("https://en.wikisource.org/wiki/Rig_Veda"))
    assert plan["ok"] is True
    assert plan["kind"] == "wikipedia"
    assert plan["url"].endswith("titles=Rig_Veda")
    assert "action=query" in plan["url"] and "explaintext=1" in plan["url"]


def test_gutenberg_id_maps_to_its_own_plain_text():
    for url in ("https://www.gutenberg.org/ebooks/2383",
                "https://www.gutenberg.org/files/2383/2383-0.txt",
                "https://www.gutenberg.org/cache/epub/2383/pg2383.txt"):
        plan = CF.resolve(rec(url))
        assert plan["ok"] is True, url
        assert plan["url"] == ("https://www.gutenberg.org/cache/epub/2383/"
                               "pg2383.txt"), url


def test_gutenberg_mirrors_have_their_own_numbering():
    """gutenberg.net.au / gutenberg.ca ki id gutenberg.org se match nahi karti.
    Pehle version un ids ko bhi gutenberg.org ke cache URL par bhej raha tha —
    wo 404 deta, par report me "read route mil gaya" likha jaata."""
    plan = CF.resolve(rec("https://gutenberg.ca/ebooks/1234"))
    assert plan["ok"] is False
    assert "id" in plan["reason"].casefold()
    ok = CF.resolve(rec("https://gutenberg.net.au/ebooks/a00001.txt"))
    assert ok["ok"] is True and ok["kind"] == "txt"


# ── 7. enrich() ka imaandaar hisaab (stubbed download, koi network nahi) ─────

TEXT = "Om. Yah granth ka mool paath hai. " * 60


class _Proc:
    def process(self, path, use_ocr=True, question="", size_bytes=0,
                large=False):
        return {"ok": True, "text": TEXT, "kind": "txt",
                "chunks": [{"locator": "p1", "text": TEXT[:400]}], "notes": []}


def _fetcher():
    fetcher = CFM.ContentFetcher(allow_network=True)

    def fake_download(url, kind, directory):
        path = os.path.join(directory, "stub.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(TEXT)
        return {"ok": True, "path": path, "bytes": len(TEXT), "large": False}

    fetcher._download = fake_download            # type: ignore[assignment]
    fetcher._processor = lambda: _Proc()         # type: ignore[assignment]
    return fetcher


def _enrich(source):
    pack = EvidencePack(question="granth me kya likha hai")
    pack.sources.append(source)
    return _fetcher().enrich(pack, max_sources=1, budget_chars=800), pack


def test_public_domain_text_is_really_read():
    report, pack = _enrich(rec("https://www.gutenberg.org/ebooks/2383"))
    entry = report["entries"][0]
    assert entry["ok"] is True
    assert entry["read_level"] == "full_text"
    assert pack.sources[0].full_text_available is True
    assert pack.passages, "padha gaya text passage banna chahiye"


def test_copyright_book_is_counted_separately_and_never_read():
    report, pack = _enrich(rec("https://someblog.example.com/book.pdf",
                               year=1975))
    assert report["copyright_blocked"] == 1
    assert report["succeeded"] == 0
    source = pack.sources[0]
    assert source.full_text_available is False
    assert source.reading_level() != "full_text"
    note = CFM.ContentFetcher.reading_note(report)
    assert "chhua hi nahi gaya" in note
    assert "summary" in note


def test_capped_read_is_not_reported_as_full_text():
    """Aaj koi rule "allowed par ceiling neeche" nahi banata. Kal ban gaya to
    label khud-ba-khud sach bole — ye test wahi guarantee pin karta hai."""
    real = C.copyright_stance

    def capped(source=None, **kwargs):
        out = dict(real(source, **kwargs))
        if "capme" in str(getattr(source, "url", "") or ""):
            out.update({"read_ceiling": "abstract", "full_text_allowed": True,
                        "verdict": C.UNKNOWN, "summary_lane": True,
                        "rule": "test_forced_ceiling"})
        return out

    CFM.classics.copyright_stance = capped       # type: ignore[assignment]
    try:
        report, pack = _enrich(rec("https://example.org/capme/x.pdf", year=1900))
    finally:
        CFM.classics.copyright_stance = real     # type: ignore[assignment]

    entry = report["entries"][0]
    assert entry["read_level"] == "abstract"
    assert report["capped"] == 1
    source = pack.sources[0]
    assert source.full_text_available is False
    assert "abstract" in source.read_note
    note = CFM.ContentFetcher.reading_note(report)
    assert note.startswith("0/1")
    assert "licence ceiling" in note


def test_reading_note_never_calls_a_capped_read_full():
    note = CFM.ContentFetcher.reading_note(
        {"attempted": 2, "succeeded": 2, "failed": 0, "chars_read": 100,
         "capped": 2, "copyright_blocked": 0, "entries": []})
    assert note.startswith("0/2")
