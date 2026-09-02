"""#133b — DHOONDHA hua media: "mila" aur "padha" ek nahi hain.

#133a me user ke apne video/audio ka LIKHIT transcript padha jaane laga
(`media_study.craft_guidance`). Par intel ki maang me "logo ki recording" aur
"bade singer ke gaane dekhe" bhi hai — wo cheezein user ke upload me nahi hoti,
unhe DHOONDHNA padta hai. #133b ne wo lane banaya:
`connectors/media_connector.py` archive.org (keyless, official
advancedsearch API) se lecture/interview/recording dhoondhta hai.

Us lane ka asli khatra ek hi hai, aur ye file usi ke peeche padi hai:

    search se sirf uploader ka LIKHA HUA parichay milta hai. Video dekha
    nahi jaata, aawaz suni nahi jaati, transcript milta hi nahi. Us item
    ko "media source" ginte hi report padhne wala samajh leta hai ki app
    ne wo recording dekh/sun li.

Isliye is file ke kaam (har test ek naapa hua jhooth rokta hai):

  1. QUERY par pabandi — mediatype filter hamesha lagta hai, aur maujooda
     gaane ke bol/file dhoondhne wali query is lane me chalti hi nahi
     (do deewar: connector ke andar bhi, `source_discovery` me bhi).
  2. LABEL par pabandi — is lane ka koi record kabhi `full_text` nahi
     kehta; `read_level` hamesha "snippet", aur `read_note` shabdon me
     kehta hai ki dekha/suna nahi gaya.
  3. PROVIDER ka filter par bharosa nahi — server ne jo diya, uska
     mediatype dobara khud check hota hai.
  4. "0 mila" aur "humne chhaanta" alag reason hain, aur "key nahi thi"
     (`no_key`) kabhi nahi bolta — wo dusra jhooth hota.
  5. GINTI alag — dhoondha hua media `media_sources()` me nahi aata, aur
     padha hua transcript `discovered_media()` me nahi aata.
  6. REPORT me alag line + alag seema, aur audit ki chhat us line ko kaat
     na de.
  7. PROMPT me saaf mana — jo media sirf mila hai, uske naam par model
     koi baat na likhe.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import media_study as ms  # noqa: E402
from research_engine import songcraft as sc  # noqa: E402
from research_engine import depth  # noqa: E402
from research_engine import connectors as cpkg  # noqa: E402
from research_engine.connectors import base as cbase  # noqa: E402
from research_engine.connectors import media_connector as mc  # noqa: E402
from research_engine.models import SourceRecord, SourceType  # noqa: E402
from research_engine.planner import ResearchPlanner  # noqa: E402
from research_engine.source_discovery import SourceDiscovery  # noqa: E402

# ── chhote helpers (koi network, koi randomness) ─────────────────────────────
GOOD_DESC = ("A long-form interview in which a working lyricist explains how "
             "she builds a chorus around one image and keeps the verse "
             "concrete.")


class _Resp:
    """requests ka sirf wahi hissa jo connector chhoota hai — `.json()`."""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _StubHttp:
    """`media_connector.http_get` badal kar payload lautao. Koi network nahi."""

    def __init__(self, docs, raiser=None):
        self.docs = docs
        self.raiser = raiser
        self.calls = []
        self.original = None

    def __enter__(self):
        self.original = mc.http_get

        def fake(url, params=None, timeout=None, headers=None, retries=None):
            self.calls.append((url, dict(params or {})))
            if self.raiser is not None:
                raise self.raiser
            return _Resp({"response": {"docs": list(self.docs)}})

        mc.http_get = fake
        return self

    def __exit__(self, *exc):
        mc.http_get = self.original
        return False


def _doc(identifier="int1", mediatype="movies", description=GOOD_DESC, **kw):
    row = {"identifier": identifier, "title": "Songwriting interview",
           "description": description, "mediatype": mediatype,
           "creator": "Archive Uploader", "year": "2011",
           "publisher": "archive.org", "subject": "songwriting"}
    row.update(kw)
    return row

def _rec(**kw):
    """SourceRecord — default me wahi shape jo ye lane banata hai."""
    row = dict(title="Songwriting interview",
               url="https://archive.org/details/int1",
               snippet=GOOD_DESC, connector="archive_media",
               source_type=SourceType.TRANSCRIPT,
               full_text_available=False, read_level="snippet",
               read_note=mc.NOT_READ_NOTE)
    row.update(kw)
    return SourceRecord(**row)


def _search(docs, query="songwriting masterclass interview", rows=3,
            raiser=None):
    connector = mc.MediaArchiveConnector()
    with _StubHttp(docs, raiser=raiser) as stub:
        out = connector.search(query, max_results=rows)
    return out, connector, stub


# ── 1. query par pabandi — filter hamesha, aur do deewar ─────────────────────

def test_search_query_always_carries_the_media_type_filter():
    """Bina filter ye lane kitaab/text items bhi utha laata.

    Wahi is lane ka pehla jhooth hota: text ka scan "recording" ban jaata.
    """
    assert mc.build_query("songwriting") == (
        f"songwriting AND {mc.MEDIATYPE_FILTER}")
    _out, _c, stub = _search([_doc()])
    assert len(stub.calls) == 1
    url, params = stub.calls[0]
    assert url == mc.SEARCH_URL
    assert mc.MEDIATYPE_FILTER in params["q"]


def test_the_media_type_filter_names_only_video_and_audio():
    """Filter me `texts` ghusna do jagah jhooth banata.

    Ek: kitaab ka lane pehle se `book_connector` ke paas hai, to wahi item do
    baar ginta. Do: ek text scan is lane ke label ("recording — dekha nahi
    gaya") ke saath report me chala jaata. Isliye filter ka content bhi pin
    hai, sirf "filter lagta hai" naapna kaafi nahi.
    """
    assert mc.MEDIA_TYPES == ("movies", "audio")
    for kind in mc.MEDIA_TYPES:
        assert kind in mc.MEDIATYPE_FILTER
    assert "texts" not in mc.MEDIATYPE_FILTER
    assert "collection" not in mc.MEDIATYPE_FILTER
    assert mc.MEDIATYPE_FILTER.startswith("mediatype:")
    # Aur label sirf inhi do kism ke liye hai — teesri kism par khaali.
    assert sorted(mc.MEDIA_LABELS) == sorted(mc.MEDIA_TYPES)


def test_an_empty_query_is_not_reported_as_a_zero_result_search():
    """"Khaali query" aur "0 mila" do alag baatein hain.

    Dono ko ek kehna audit me "provider ke paas kuch nahi tha" jaisa padhta,
    jabki asal me humne request bheji hi nahi thi.
    """
    connector = mc.MediaArchiveConnector()
    with _StubHttp([_doc()]) as stub:
        assert connector.search("   ", max_results=3) == []
    assert stub.calls == []                       # network chhua hi nahi
    assert connector.last_reason == "empty_query"
    assert mc.build_query("   ") == ""

def test_a_lyrics_hunt_never_reaches_the_network_from_this_lane():
    """Doosri deewar (pehli `source_discovery` me hai).

    "tum hi ho lyrics mp3 download" par archive.org par jaana galat hai: wo
    craft padhna nahi, kisi ka gaana uthana hai.
    """
    # Neeche ke paanch roop `songcraft._LYRICS_HUNT_RE` ke paanch ALAG raaste
    # hain (file/copy maangna, "full lyrics", "lyrics - <naam>", karaoke/mp3,
    # aur Hindi "gaane ke bol"). Ek hi roop rakhne se regex ka ek hissa mar
    # jaata aur test chup rehta.
    #
    # NAAP HUA KHULA GAP (jaan-boojh kar yahan assert NAHI kiya, kyunki assert
    # karne se wo kamzori pin ho jaati): sirf "<gaane ka naam> song lyrics"
    # is regex par nahi girta. Filhaal iska raasta band hai — is lane ki saari
    # query `songcraft.study_queries()` se banti hai (seed + style shabd), usme
    # kisi gaane ka naam aata hi nahi, aur wahi baat
    # `test_no_planned_media_query_is_a_lyrics_hunt` pin karta hai.
    connector = mc.MediaArchiveConnector()
    for text in ("tum hi ho full lyrics download",
                 "karaoke track mp3 download",
                 "kesariya lyrics pdf",
                 "lyrics - kesariya",
                 "kesariya gaane ke bol"):
        with _StubHttp([_doc()]) as stub:
            assert connector.search(text, max_results=3) == [], text
        assert stub.calls == [], text
        assert connector.last_reason == "lyrics_hunt_blocked", text
        assert connector.last_note == mc.LYRICS_BLOCK_NOTE, text


def test_the_lyrics_wall_is_never_reported_as_a_missing_api_key():
    """`ConnectorSkipped` yahan uthana ek NAAPA hua jhooth hota.

    `base.safe_search` use `reason="no_key"` bana deta hai — yaani audit padhta
    "API key nahi thi", jabki asli wajah "humne khud chhaanta" hai. Isliye lane
    khaali list + apna `last_reason` deta hai.
    """
    connector = mc.MediaArchiveConnector()
    with _StubHttp([_doc()]):
        result = connector.safe_search("tum hi ho full lyrics", 3)
    assert result["records"] == []
    assert result["reason"] == "lyrics_hunt_blocked"
    assert result["reason"] != "no_key"
    # Aur ye baat sirf naam ki nahi hai: base me `no_key` ka raasta ab bhi
    # `ConnectorSkipped` se hi banta hai, isliye upar ka farq asli hai.
    assert issubclass(cbase.ConnectorSkipped, cbase.ConnectorError)


def test_a_provider_failure_is_not_turned_into_a_lyrics_block():
    """Har khaali jawab ki wajah alag likhni chahiye, warna audit andha hai."""
    connector = mc.MediaArchiveConnector()
    with _StubHttp([], raiser=cbase.RateLimited("429")):
        result = connector.safe_search("songwriting masterclass", 3)
    assert result["records"] == []
    assert result["reason"] == "rate_limited"

# ── 2. label par pabandi — is lane ke paas full text hota hi nahi ─────────────

def test_every_record_says_the_media_was_not_watched_or_heard():
    """Ye is poore batch ka dil hai.

    Ek search hit ka matlab sirf ye hai ki archive.org par kisi ne ek recording
    chadhayi aur uske baare me do line likhi. Us record ko bina label bhejna
    seedha "app ne wo lecture dekh liya" padhata hai.
    """
    out, _c, _s = _search([_doc()])
    assert len(out) == 1
    rec = out[0]
    assert rec.read_level == mc.READ_LEVEL == "snippet"
    assert rec.full_text_available is False
    assert rec.read_note == mc.NOT_READ_NOTE
    # Sirf field me nahi — padhne wale ke liye SHABDON me bhi.
    assert "dekha nahi gaya" in rec.read_note
    assert "suni nahi gayi" in rec.read_note
    assert mc.NOT_READ_NOTE in rec.snippet


def test_this_lane_can_never_produce_a_full_text_claim():
    """`reading_level()` hi §9 ka label banata hai — wahan se sach nikalna."""
    out, _c, _s = _search([_doc(), _doc(identifier="int2", mediatype="audio")])
    assert len(out) == 2
    for rec in out:
        assert rec.reading_level() == "snippet"
        assert rec.access_depth() == "SNIPPET ONLY"
        assert rec.access_depth() != "FULL TEXT ACCESSED"
        assert "VERIFIED" not in rec.access_depth()


def test_the_url_is_the_details_page_never_a_media_file():
    """Ye lane gaana download karne ka raasta nahi hai.

    File list maangi hi nahi jaati, isliye URL kabhi kisi media file par nahi
    ja sakta.
    """
    out, _c, stub = _search([_doc(identifier="talk-1996")])
    assert out[0].url == "https://archive.org/details/talk-1996"
    _url, params = stub.calls[0]
    fields = list(params.get("fl[]") or [])
    for banned in ("files", "file", "download", "format"):
        assert banned not in fields
    for rec in out:
        assert "/download/" not in rec.url
        assert not rec.url.endswith((".mp3", ".mp4", ".ogg", ".zip"))

# ── 3. provider ke filter par bharosa nahi ───────────────────────────────────

def test_a_non_media_item_is_dropped_even_though_the_query_filtered_it():
    """Server ka filter kal badal sakta hai; label ka jhooth reh jaata.

    `q` me mediatype pabandi jaane ke BAAD bhi har item khud check hota hai —
    warna ek text/collection item "recording" ban kar report me chala jaata.
    """
    out, connector, _s = _search([
        _doc(identifier="ok1", mediatype="movies"),
        _doc(identifier="bad1", mediatype="texts"),
        _doc(identifier="bad2", mediatype="collection"),
        _doc(identifier="bad3", mediatype=""),
    ])
    assert [r.url.rsplit("/", 1)[-1] for r in out] == ["ok1"]
    assert "3 non-media" in connector.last_note


def test_an_item_without_a_readable_description_is_dropped():
    """Parichay hi na ho to yahan padhne layak kuch nahi hai.

    Aisa record rakhna "ek source padha gaya" ka khaali daawa hai — ginti badh
    jaati aur padhna kuch nahi hota.
    """
    out, connector, _s = _search([
        _doc(identifier="thin1", description=""),
        _doc(identifier="thin2", description="short talk"),
        _doc(identifier="thin3", description="x" * (
            mc.MIN_DESCRIPTION_CHARS - 1)),
    ])
    assert out == []
    assert connector.last_reason == "filtered"
    assert str(mc.MIN_DESCRIPTION_CHARS) in connector.last_note
    # Seema par baithe item ko rakha jaata hai — pabandi "kam se kam" hai.
    kept, _c2, _s2 = _search([_doc(identifier="edge",
                                   description="y" * mc.MIN_DESCRIPTION_CHARS)])
    assert len(kept) == 1


def test_an_item_without_an_identifier_is_dropped_because_the_url_would_lie():
    out, connector, _s = _search([dict(_doc(), identifier="")])
    assert out == []
    assert connector.last_reason == "filtered"


def test_zero_results_and_we_filtered_them_are_two_different_reasons():
    """"0 mila" par `filtered` likhna bhi jhooth hota — dono alag rakhe gaye.

    Padhne ka tareeka bhi naapa hua hai: `safe_search()` se, kyunki `reason`
    thread-local hai aur SIRF `safe_search` use har call par saaf karta hai.
    Seedha `search()` bulane par pichhle call ka reason bacha reh jaata — aur
    audit purani wajah ko is call ki wajah samajh leta.
    """
    connector = mc.MediaArchiveConnector()
    with _StubHttp([]):
        empty = connector.safe_search("songwriting masterclass interview", 3)
    assert empty["records"] == []
    assert empty["reason"] == ""                # provider ke paas kuch nahi tha
    assert "0 media source bheje" in empty["note"]

    # Wahi khaali nateeja, par wajah alag: humne khud chhaanta.
    with _StubHttp([_doc(mediatype="texts")]):
        filtered = connector.safe_search("songwriting masterclass interview", 3)
    assert filtered["records"] == []
    assert filtered["reason"] == "filtered"
    assert filtered["reason"] != empty["reason"]
    assert "0 media source bheje" in filtered["note"]

def test_the_row_budget_is_bounded_so_this_lane_cannot_eat_the_run():
    """Craft padhna asli sawaal ka budget nahi kha sakta."""
    for asked, want in ((0, 1), (3, 3), (999, 20), (-5, 1)):
        _out, _c, stub = _search([_doc()], rows=asked)
        assert int(stub.calls[0][1]["rows"]) == want, asked


def test_a_list_valued_description_and_subject_do_not_crash_the_lane():
    """archive.org kabhi string deta hai, kabhi list — dono chalne chahiye."""
    out, _c, _s = _search([_doc(
        description=[GOOD_DESC, "second paragraph of the same note"],
        subject=["songwriting", "lyrics", "interview"],
        creator=["A Lyricist", "An Interviewer"])])
    assert len(out) == 1
    assert out[0].authors == ["A Lyricist", "An Interviewer"]
    assert "songwriting" in out[0].snippet


def test_the_year_comes_from_year_or_date_and_junk_stays_empty():
    out, _c, _s = _search([_doc(year="", date="1996-04-01")])
    assert out[0].year == 1996
    out2, _c2, _s2 = _search([_doc(identifier="j1", year="", date="n.d.")])
    assert out2[0].year is None


def test_the_media_kind_label_never_guesses():
    """Anjaan mediatype par khaali label — jhootha label se behtar khaali."""
    assert mc.media_label("movies") == mc.MEDIA_LABELS["movies"]
    assert mc.media_label("AUDIO ") == mc.MEDIA_LABELS["audio"]
    assert mc.media_label("texts") == ""
    assert mc.media_label(None) == ""
    for label in mc.MEDIA_LABELS.values():
        assert "nahi" in label            # har label apni seema khud kehta hai


# ── 4. facade aur package exports ────────────────────────────────────────────

def test_the_facade_finds_the_archive_connector_by_name():
    facade = mc.MediaConnector()
    assert [c.name for c in facade.connectors] == ["archive_media"]
    assert facade.by_name("archive_media") is not None
    assert facade.by_name("nahi_hai") is None


def test_the_package_exports_the_media_lane():
    """`connectors/__init__` se na milna matlab lane chup-chaap gum."""
    for name in ("MediaConnector", "MediaArchiveConnector",
                 "media_search_query", "media_label"):
        assert name in cpkg.__all__, name
        assert getattr(cpkg, name, None) is not None, name
    assert cpkg.media_search_query is mc.build_query

# ── 5. lane ka vocabulary aur budget (naya lane purane ko na khaye) ──────────

def test_study_lanes_is_the_single_source_of_truth():
    """Code aur test do alag sach bolein — yahi purani galti thi.

    Isliye lane ka naam ek hi jagah (`songcraft.STUDY_LANES`) se aata hai, aur
    seed us list se bahar ka lane naam nahi le sakta.
    """
    assert "media" in sc.STUDY_LANES
    for lane in ("web", "books", "papers"):
        assert lane in sc.STUDY_LANES, lane
    for _query, lane, _why in sc.CRAFT_STUDY_SEEDS:
        assert lane in sc.STUDY_LANES, lane


def test_the_media_seed_comes_first_so_it_never_loses_its_slot():
    """Seed ka kram budget hai, sajawat nahi.

    Dynamic queries (style + bhasha + mood) 4 slot le sakti hain. Jo seed
    peeche hai wo bure haalat me chalta hi nahi — isliye "logo ki recording"
    wala lane pehla hai.
    """
    assert sc.CRAFT_STUDY_SEEDS[0][1] == "media"
    lanes = [lane for _q, lane, _w in sc.CRAFT_STUDY_SEEDS]
    assert lanes.count("media") == 1
    # Aur seed ki apni wajah likhi honi chahiye (report me chhapti hai).
    for query, _lane, why in sc.CRAFT_STUDY_SEEDS:
        assert query.strip() and why.strip()


def test_the_budget_grew_instead_of_pushing_an_older_seed_out():
    """#129 me naapi hui kitaab/paper/web coverage waisi hi rehni chahiye.

    Naye lane ke liye purane seed ki jagah lena chhupa hua nuksaan hota: plan
    me ginti wahi rehti, par prosody/music-theory padhna band ho jaata.
    """
    assert sc.MAX_STUDY_QUERIES == 6
    assert sc.MAX_STUDY_QUERIES >= len(sc.CRAFT_STUDY_SEEDS)
    seed_lanes = [lane for _q, lane, _w in sc.CRAFT_STUDY_SEEDS]
    for lane in ("books", "papers", "web"):
        assert lane in seed_lanes, lane

def test_a_song_request_actually_plans_a_media_query():
    """Constant me lane hona kaafi nahi — plan me pahunchna chahiye."""
    ask = sc.style_of("sad punjabi gaana likho 8 line")
    rows = sc.study_queries(ask)
    lanes = [row["lane"] for row in rows]
    assert "media" in lanes
    assert len(rows) <= sc.MAX_STUDY_QUERIES
    plan = sc.study_plan(ask)
    assert "media" in plan["craft_study_lanes"]
    # Ginti teeno list me ek jaisi rehni chahiye, warna report me kram tootega.
    assert (len(plan["craft_study_queries"]) == len(plan["craft_study_lanes"])
            == len(plan["craft_study_reasons"]))


def test_the_older_seeds_still_survive_a_style_heavy_ask():
    """Sabse bhare haalat me bhi kitaab/paper wali coverage na mare.

    Yahi wo naap hai jiske liye chhat 5 se 6 ki gayi thi.
    """
    ask = sc.style_of("sad slow punjabi gangstar type hindi gaana likho")
    lanes = [row["lane"] for row in sc.study_queries(ask)]
    assert "media" in lanes
    assert len([lane for lane in lanes if lane != "media"]) >= 3


def test_no_planned_media_query_is_a_lyrics_hunt():
    """Apni hi query apni deewar se na takraye — warna lane chup-chaap khaali."""
    for text in ("sad punjabi gaana likho", "gangstar type gaana likho",
                 "hindi me romantic gaana banao"):
        ask = sc.style_of(text)
        for row in sc.study_queries(ask):
            assert sc.is_lyrics_hunt(row["query"]) is False, row
            if row["lane"] == "media":
                assert mc.build_query(row["query"]).endswith(
                    mc.MEDIATYPE_FILTER), row


def test_a_song_ask_never_claims_audio_was_produced():
    """intel ko saaf pata rahe: dhun/tone likh kar batayi jaati hai, banti nahi."""
    assert sc.AUDIO_GENERATED is False
    assert ms.AUDIO_LISTENED is False
    assert ms.FRAMES_READ is False

# ── 6. routing — plan ka naam sach me is connector par jaata hai ─────────────
class _Spy:
    """Connector ka naatak — network ke bina, jo query aayi wo yaad rakhta hai.

    `source_discovery._single()` `safe_search()` bulata hai, `search()` nahi —
    isliye naatak bhi wahi naam aur wahi 7-key shape deta hai. Sirf `search`
    rakhne se task `AttributeError` par girta aur "0 record mile" jaisa dikhta:
    yaani routing toota hone par bhi test hara ho sakta tha.
    """

    name = "archive_media"

    def __init__(self):
        self.seen = []

    def safe_search(self, query, max_results=3):
        self.seen.append(str(query))
        self.limits = getattr(self, "limits", [])
        self.limits.append(int(max_results))
        return {"connector": self.name, "records": [], "count": 0,
                "error": "", "reason": "", "note": "", "seconds": 0.0}


def _tasks_for(craft_entries, question="gaana likho"):
    discovery = SourceDiscovery()
    spy = _Spy()
    discovery.media.by_name = lambda name: spy
    plan = {"web": True, "papers": [], "books": [], "datasets": [],
            "patents": [], "markets": [], "craft_study": craft_entries}
    tasks = discovery._tasks([question], plan, 3, 5)
    return [label for label, _fn in tasks], tasks, spy


def test_discovery_owns_a_media_facade():
    """Facade na ho to lane ka naam kisi connector par nahi girta."""
    discovery = SourceDiscovery()
    assert hasattr(discovery, "media")
    assert [c.name for c in discovery.media.connectors] == ["archive_media"]


def test_the_media_lane_is_routed_to_the_archive_connector():
    labels, tasks, spy = _tasks_for([
        {"query": "songwriting masterclass interview lecture recording",
         "lane": "media"},
        {"query": "songwriting craft lyric writing guide", "lane": "books"},
    ])
    assert "craft_study_media" in labels
    ran = 0
    for label, fn in tasks:
        if label == "craft_study_media":
            out = fn()
            ran += 1
            # `_single()` ka shape — record aur log dono aane chahiye, warna
            # discovery is lane ka hisaab audit me likh hi nahi paata.
            assert set(out) == {"records", "log"}
    assert ran == 1
    assert spy.seen == ["songwriting masterclass interview lecture recording"]
    # Budget chhota hi rehna chahiye: craft padhna asli sawaal ka hissa nahi.
    assert spy.limits == [2]


def test_the_media_lane_does_not_quietly_fall_back_to_the_web():
    """Web se aaya webpage media nahi hota.

    Use `craft_study_media` kehna label ka jhooth hota — isliye media lane ka
    naam sirf media facade se aata hai.
    """
    labels, _tasks, _spy = _tasks_for([
        {"query": "songwriting masterclass interview", "lane": "media"}])
    assert labels.count("craft_study_media") == 1
    assert "craft_study_web" not in labels

def test_a_planted_lyrics_hunt_dies_at_the_discovery_wall_too():
    """Do deewar jaan-boojh kar: connector ke andar bhi, discovery me bhi.

    Ek deewar hone par kal koi doosra caller connector ko seedha bula kar
    guard chhod deta.
    """
    labels, _tasks, spy = _tasks_for([
        {"query": "songwriting masterclass interview", "lane": "media"},
        {"query": "tum hi ho full lyrics mp3", "lane": "media"},
    ])
    assert labels.count("craft_study_media") == 1
    assert spy.seen == []                      # abhi koi task chalaya nahi


def test_the_media_lane_stays_shut_when_the_plan_did_not_ask_for_it():
    """Ye lane sirf craft-study se chalta hai — asli sawaal ke evidence se nahi."""
    labels, _tasks, _spy = _tasks_for([])
    assert not [label for label in labels if "media" in label]


def test_the_planner_keeps_the_media_lane_name_untouched():
    """planner lane naam par apna faisla na thope — wo songcraft ka kaam hai."""
    planner = ResearchPlanner()
    config = depth.get_depth_config("DEEP")
    question = "sad punjabi gaana likho 8 line"
    plan = planner.connector_plan({"question": question}, config,
                                  question=question)
    lanes = [row["lane"] for row in plan["craft_study"]]
    assert lanes                                  # lane khuli hai
    for lane in lanes:
        assert lane in sc.STUDY_LANES, lane
    assert "media" in lanes
    # Lane sirf naam se nahi, gate se bhi khuli honi chahiye — aur us gate ka
    # sach yahi hai ki media SUNA/DEKHA nahi jaata.
    assert plan["craft_study_lane"]["audio_generated"] is False


# ── 7. "mila" ki ginti "padha" se ALAG rehti hai ─────────────────────────────

def test_a_found_media_item_is_not_counted_as_a_read_transcript():
    """Sabse important naap.

    `media_sources()` sirf unhe uthata hai jinka media kism naapa ja saka
    (extension ya samay-mohar). Search se aaye item me dono nahi hote — aur
    yahi imaandaar nateeja hai.
    """
    found = _rec(source_id="S1")
    assert ms.media_sources([found]) == []
    assert ms.media_kind(found.title, getattr(found, "locator", "")) == ""
    guidance = ms.craft_guidance([found])
    assert guidance["ran"] is False
    assert guidance["media_source_count"] == 0

def test_discovered_media_counts_only_items_whose_transcript_never_arrived():
    found = ms.discovered_media([
        _rec(source_id="S1"),
        _rec(source_id="S2", title="Lecture on melody", read_level="snippet"),
        _rec(source_id="S3", source_type=SourceType.PAPER,
             read_level="abstract"),
    ])
    assert found["count"] == 2
    assert [item["source_id"] for item in found["items"]] == ["S1", "S2"]
    assert found["transcript_available"] is False
    for item in found["items"]:
        assert item["read_level"] == "snippet"


def test_a_read_transcript_is_never_counted_as_merely_discovered():
    """#133a aur #133b ki ginti ek me mil jaaye to dono jhooth ban jaati."""
    read = _rec(source_id="S9", title="masterclass.vtt", locator="12:30",
                read_level="full_text", full_text_available=True,
                read_note="")
    found = ms.discovered_media([read])
    assert found["count"] == 0
    assert ms.media_sources([read]) == [read]
    # Aur ye baat `read_level` par tik nahi honi chahiye: media KISM naapi ja
    # sakti hai, iska matlab item #133a ke raste ka hai — bhale uska read level
    # abhi "snippet" ho. Warna wahi item DONO gintiyon me aa jaata.
    shallow = _rec(source_id="S10", title="lyric-masterclass.mp3",
                   locator="05:00", read_level="snippet")
    assert ms.media_sources([shallow]) == [shallow]
    assert ms.discovered_media([shallow])["count"] == 0
    assert ms.discovered_media([shallow])["full_transcript_count"] == 0


def test_user_supplied_media_keeps_its_own_label():
    """User ke upload ka apna niyam (#91) pehle se hai — dobara ginna galat."""
    own = _rec(source_id="U1", title="my-notes.mp3", locator="03:10",
               connector="user_pdf", source_type=SourceType.DOCUMENT,
               read_level="full_text")
    assert ms.discovered_media([own])["count"] == 0
    assert ms._user_supplied(own) is True
    # Sakht haalat: user ka apna media jiska naam bina extension aaya aur jo
    # abhi poora padha bhi nahi gaya. Yahan sirf "user ne di hui copy" wala
    # guard bachata hai — aur usi ke bina wo item "humne dhoondha" ban jaata.
    own_thin = _rec(source_id="U2", title="meri recording", locator="",
                    connector="user_pdf", read_level="snippet")
    assert ms._user_supplied(own_thin) is True
    assert ms.media_kind(own_thin.title, own_thin.locator) == ""
    assert ms.discovered_media([own_thin])["count"] == 0


def test_a_full_transcript_is_counted_separately_so_the_note_cannot_lie():
    """Kal koi lane sach me transcript le aaye to line jhooth ban jaati.

    Isliye us haalat ki ginti chhupayi nahi jaati — alag rakhi jaati hai.
    """
    later = _rec(source_id="F1", title="no-extension-title",
                 read_level="full_text", full_text_available=True)
    found = ms.discovered_media([later])
    assert found["count"] == 0
    assert found["full_transcript_count"] == 1
    assert "koi video/audio nahi mila" in found["note"]

def test_the_item_list_is_bounded_but_the_count_stays_true():
    """Report chhoti rehni chahiye, par ginti poori — warna hisaab hi galat."""
    many = [_rec(source_id=f"S{i}") for i in range(ms.MAX_DISCOVERED_ITEMS + 4)]
    found = ms.discovered_media(many)
    assert found["count"] == ms.MAX_DISCOVERED_ITEMS + 4
    assert len(found["items"]) == ms.MAX_DISCOVERED_ITEMS


def test_the_report_carries_the_found_hisaab_even_when_nothing_was_read():
    guidance = ms.craft_guidance([_rec(source_id="S1")])
    assert guidance["ran"] is False
    assert guidance["discovered"]["count"] == 1
    # Aur padhne wale haalat me bhi hisaab saath chalta hai.
    read = _rec(source_id="S2", title="talk.vtt", locator="12:30",
                read_level="full_text", full_text_available=True,
                snippet="Chorus me hook chhota rakho aur ek image par tiko.")
    both = ms.craft_guidance([read, _rec(source_id="S1")])
    assert both["ran"] is True
    assert both["media_source_count"] == 1
    assert both["discovered"]["count"] == 1


def test_a_generator_of_sources_is_not_silently_lost():
    """`sources` generator ho to dobara ghoomne par khaali milta.

    Wo "0 media mila" ban jaata — ek chup-chaap jhooth.
    """
    gen = (rec for rec in [_rec(source_id="S1"),
                           _rec(source_id="S2", source_type=SourceType.PAPER)])
    guidance = ms.craft_guidance(gen)
    assert guidance["discovered"]["count"] == 1
    assert guidance["sources_scanned"] == 2


def test_discovered_report_defaults_are_honest_when_the_key_is_missing():
    """Purane shape ka report bhi tootna nahi chahiye (crash-fallback bhi)."""
    empty = ms.discovered_report({})
    assert empty["count"] == 0 and empty["items"] == []
    assert empty["transcript_available"] is False
    assert ms.discovered_report(None)["count"] == 0
    assert ms.discovered_report("kachra")["count"] == 0
    assert ms.discovered_lines(empty) == []
    assert ms.discovered_prompt_line(empty) == ""

# ── 8. report me alag line, alag seema, aur prompt me saaf mana ──────────────

def test_the_section_fires_when_media_was_only_found():
    """Pehle block sirf "padha gaya" par chhapta tha.

    Uska matlab tha: 5 recording mile aur report ne unka naam bhi nahi liya —
    yaani kami chup-chaap gayab.
    """
    guidance = ms.craft_guidance([_rec(source_id="S1")])
    text = ms.media_section(guidance)
    assert text
    assert ms.MEDIA_SUBHEADING in text
    assert "padhe NAHI gaye" in text
    assert "Songwriting interview [S1]" in text
    assert "transcript mila hi nahi" in text
    # Aur "kitne transcript padhe: 1" jaisa jhooth kahin nahi.
    assert "Kitne transcript padhe" not in text


def test_the_section_stays_empty_when_there_is_no_media_at_all():
    """Har report me "video nahi mila" ki line chipkaana bakwaas hai."""
    guidance = ms.craft_guidance([_rec(source_id="P1",
                                       source_type=SourceType.PAPER,
                                       read_level="abstract")])
    assert ms.media_section(guidance) == ""
    assert ms.media_limits(guidance) == []
    assert ms.media_section(None) == ""
    assert ms.media_limits("kachra") == []


def test_read_and_found_media_are_two_different_blocks_in_one_section():
    read = _rec(source_id="S2", title="talk.vtt", locator="12:30",
                read_level="full_text", full_text_available=True,
                snippet="Chorus me hook chhota rakho aur ek image par tiko.")
    text = ms.media_section(ms.craft_guidance([read, _rec(source_id="S1")]))
    assert "**Kitne transcript padhe:** 1" in text
    assert "**Search se mile video/audio (padhe NAHI gaye):** 1" in text
    assert text.index("Kitne transcript padhe") < text.index("padhe NAHI gaye")
    # Do block ke beech khaali line ka farq — warna dono ek dikhte hain.
    assert "\n\n**Search se mile" in text

def test_the_found_but_unread_media_has_its_own_audit_limit():
    """Ye seema PADHNE waali seemaon se alag hai.

    Wahan transcript tha par aawaz nahi; yahan transcript hi nahi tha. Dono ko
    ek line me likhna do alag kami ko ek dikha deta.
    """
    only_found = ms.media_limits(ms.craft_guidance([_rec(source_id="S1")]))
    assert only_found == [ms.DISCOVERED_LIMIT_LINE]
    assert "transcript nahi mila" in ms.DISCOVERED_LIMIT_LINE


def test_the_audit_ceiling_does_not_cut_the_found_media_line():
    """Audit me media ki chhat 5 hai; 4 rehne par nayi line kat jaati thi."""
    read = _rec(source_id="S2", title="talk.vtt", locator="12:30",
                read_level="full_text", full_text_available=True,
                snippet="Chorus me hook chhota rakho aur ek image par tiko.")
    lines = ms.media_limits(ms.craft_guidance([read, _rec(source_id="S1")]))
    assert len(lines) == 5
    assert lines[-1] == ms.DISCOVERED_LIMIT_LINE
    # synthesizer ki chhat wahi 5 honi chahiye, warna line chup-chaap gayab.
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "research_engine", "synthesizer_claude.py")
    with open(path, "r", encoding="utf-8") as handle:
        code = handle.read()
    assert "media_limits(media_report)[:5]" in code


def test_the_prompt_forbids_speaking_for_media_that_was_only_found():
    """Model ke paas sirf NAAM hote hain — us par baat likhna sabse aasan jhooth."""
    line = ms.discovered_prompt_line(
        ms.discovered_media([_rec(source_id="S1")]))
    assert "sirf SEARCH me mile" in line
    assert "pata NAHI" in line
    block = ms.prompt_block(ms.craft_guidance([_rec(source_id="S1")]))
    assert line in block
    # Jab ek bhi transcript na padha ho, tab ye chetavni SABSE zaroori hai.
    assert ms.EMPTY_PROMPT_LINE in block


def test_the_prompt_warning_also_survives_when_a_transcript_was_read():
    read = _rec(source_id="S2", title="talk.vtt", locator="12:30",
                read_level="full_text", full_text_available=True,
                snippet="Chorus me hook chhota rakho aur ek image par tiko.")
    block = ms.prompt_block(ms.craft_guidance([read, _rec(source_id="S1")]))
    assert "sirf SEARCH me mile" in block
    assert "[S2, Samay 12:30]" in block

def test_section_lines_say_the_found_media_was_not_read():
    lines = ms.section_lines(ms.craft_guidance([_rec(source_id="S1")]))
    joined = "\n".join(lines)
    assert "kuch padha nahi gaya" in joined
    assert "sirf parichay padha gaya" in joined
    assert ms.DISCOVERED_LIMIT_LINE in joined


def test_policy_and_cannot_measure_name_the_gap_by_name():
    """Audit me sach naam se hona chahiye, warna wo chhup sakta hai."""
    policy = ms.policy()
    assert policy["discovered_read_level"] == "snippet"
    assert policy["discovered_transcript_available"] is False
    assert policy["frames_read"] is False and policy["audio_listened"] is False
    assert policy["gemini_calls"] == 0 and policy["network_used"] is False
    joined = " | ".join(ms.CANNOT_MEASURE)
    assert "search se mile video/audio ke ANDAR kya kaha gaya" in joined


def test_the_found_hisaab_never_claims_frames_or_audio():
    found = ms.discovered_media([_rec(source_id="S1")])
    assert found["frames_read"] is False
    assert found["audio_listened"] is False
    assert found["transcript_available"] is False
    assert "VERIFIED" not in found["label"]
    assert "VERIFIED" not in found["limit_line"]


def test_the_whole_report_is_deterministic():
    """Do baar chalane par ek hi jawab — warna audit par bharosa nahi."""
    sources = [_rec(source_id="S1"),
               _rec(source_id="S2", title="Lecture on melody"),
               _rec(source_id="P1", source_type=SourceType.PAPER,
                    read_level="abstract")]
    first = ms.craft_guidance(list(sources))
    second = ms.craft_guidance(list(sources))
    assert first["discovered"] == second["discovered"]
    assert ms.media_section(first) == ms.media_section(second)
    assert ms.media_limits(first) == ms.media_limits(second)
    assert ms.prompt_block(first) == ms.prompt_block(second)


def test_this_lane_spends_no_model_call_and_no_extra_network():
    """Lens/craft ka faisla ₹0 me hota hai — ye waada naapa jaata hai."""
    assert ms.GEMINI_CALLS == 0 and ms.NETWORK_USED is False
    assert sc.GEMINI_CALLS == 0 and sc.NETWORK_USED is False
    guidance = ms.craft_guidance([_rec(source_id="S1")])
    assert guidance["gemini_calls"] == 0
    assert guidance["network_used"] is False
