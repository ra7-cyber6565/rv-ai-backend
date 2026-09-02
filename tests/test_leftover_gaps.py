"""#186f — BACHE HUE CHHED ka pehra (craft want-tier, read-depth, trade cue, bol-talaash).

#186a ke audit ne chaar aisi kharabiyaan naapi thi jo har suite GREEN hone par
bhi zinda thi, kyunki unme se kisi par bhi koi test khada nahi tha. Ye file
unhi chaar ke peeche padi hai — aur har group ke saath wo naap likhi hai jo
kharabi ke waqt ASLI me galat aa rahi thi:

  A. CRAFT ka darwaza (#186b) — "ek sad gaana chahiye" par `craft.detect()`
     False deta tha (`no_make_verb`), yaani intel ki sabse aam hindi phrasing
     par gaana/kavita/kahani ka poora lane chalta hi nahi tha. Ulta khatra bhi
     naapa gaya: "gaana kaise likhte hain" par True aa raha tha — app tarika
     samjhane ki jagah gaana likh deta. Isliye ab TEEN darje hain: seedha hukum
     (pehra nahi), dhala hua roop, aur maangne wala verb (dono par pehra).
  B. GEHRAI ka naam (#186c) — market series par `read_level="full"` likha tha,
     jo `models.READ_LEVEL_ORDER` me hai hi nahi. Natija: poori padhi hui series
     "METADATA ONLY" dikhti thi aur `read_level_counts()` se gayab thi. Yahan
     ek AAM contract test hai — poore engine me set hone wala har read_level
     jaana-pehchana naam ho — taaki agli baar kisi bhi connector me wahi galti
     na chhupe.
  C. TRADE ka cue (#186d) — `_has()` shabd ki seema par milata hai, isliye cue
     "failure class" spec ke sabse aam sarkari phrase "failure classification"
     ko pakadta hi nahi tha, aur point NOT_MEASURED ("zikr nahi mila") reh jaata
     tha. Saare 17 cue par teen-tarfa seedhi naap yahan pin ki gayi hai.
  D. BOL ki talaash (#186e) — "tum hi ho song lyrics" / "channa mereya lyrics"
     jaisi farmaish guard se nikal jaati thi. Ilaaj me gaano ki koi NAAM-LIST
     nahi hai: shabdkosh app ke APNE table se banta hai, isliye app ki khud ki
     banayi query kabhi apne hi guard me nahi phansti.

Do baaton par ye file JAAN-BOOJH KAR "abhi ye nahi hota" likhti hai, kyunki
dono jagah galat pakadna asli farmaish maar deta (intel ki shart #155b —
"maanga hua gaana kabhi chup-chaap gayab na ho"): `craft.WANT_TIER_KNOWN_LIMIT`
aur `songcraft.LYRICS_HUNT_KNOWN_LIMIT`. Test dono seemao ko naapta hai taaki
kal koi unhe chupke se "theek hai" na samajh le.

Sab kuch OFFLINE aur ₹0 — na Gemini, na network.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import craft  # noqa: E402
from research_engine import market_data as md  # noqa: E402
from research_engine import models  # noqa: E402
from research_engine import songcraft as sc  # noqa: E402
from research_engine import trademodel as tm  # noqa: E402
from research_engine.connectors import market_connector as mc  # noqa: E402
from research_engine.models import EvidencePack  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, "research_engine")

TRADE_Q = ("US100 aur XAUUSD ka intraday scalping model banao 15M context 5M "
           "confirmation 1M entry ke saath")


def _trade_row(spec, point_id="failure_classification"):
    """Ek contract point ki asli row — `point_id` se, kram se nahi."""
    report = tm.study(question=TRADE_Q, spec=spec)
    for row in report.get("checks", []):
        if row.get("point_id") == point_id:
            return row
    raise AssertionError(f"{point_id} ki row hi nahi mili")


def _series(points=6):
    """Ek chhoti par poori padhi hui series — provider ka apna data."""
    return md.MarketSeries(
        points=[md.SeriesPoint(period=str(2010 + i), order=2010 + i,
                               value=100.0 + i, unit="index")
                for i in range(points)],
        frequency="yearly", unit="index", provider="world_bank",
        series_id="TEST.SERIES", label="Test series")


def _engine_files():
    """`research_engine/` ke saare .py — pycache chhod kar, stable kram me."""
    found = []
    for folder, dirs, names in os.walk(ENGINE):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(names):
            if name.endswith(".py"):
                found.append(os.path.join(folder, name))
    return found


# ── A. #186b — CRAFT ka darwaza: hukum, dhala hua roop, aur maangna ──────────
def test_a_wanting_a_song_also_opens_the_craft_lane():
    """
    "chahiye" / "de do" bhi banane ka signal hai — bas kamzor signal.

    Pehle sirf banane wala verb (likho/banao) chalta tha, isliye "ek sad gaana
    chahiye" par CRAFT chalta hi nahi tha aur uski jagah research aa jaati thi.
    """
    for question, form in (("ek sad gaana chahiye", "song"),
                           ("ek gaana de do", "song"),
                           ("mujhe ek kahani chahiye", "story"),
                           ("ek kavita chaiye", "poem"),
                           ("mujhe ek shayari de dena", "poem")):
        found = craft.detect(question)
        assert found["is_request"] is True, question
        assert found["form"] == form, question
        # darja report me saaf dikhe: ye MAANGNE wala signal tha, hukum nahi
        assert found["make_kind"] == "want", question
        assert found["make_cue"], question
        assert found["reason"] == "", question


def test_a_a_spelling_variant_is_not_a_new_meaning():
    """"taiyaar"/"ready" wahi hukum hai jo "tayaar" tha — sirf hijje ki chhoot."""
    for question in ("gaana taiyaar karo", "ek gaana ready karo",
                     "ek gaana tyar karo"):
        found = craft.detect(question)
        assert found["is_request"] is True, question
        assert found["form"] == "song", question
        # hijje ki chhoot hai, isliye darja BANANE wala hi rehna chahiye
        assert found["make_kind"] == "make", question


def test_a_an_explaining_question_never_becomes_a_deliverable():
    """
    "gaana kaise likhte hain" tarika poochh raha hai, gaana nahi maang raha.

    Ye kamzor signal (prefix se mila "likhte" ← "likh") par pehra hai. Reason
    alag hai — `explain_intent`, `no_make_verb` nahi — kyunki "cue tha hi nahi"
    aur "cue tha par ye sawaal samjhane ka tha" do alag baatein hain.
    """
    for question, cue in (("gaana kaise likhte hain", "kaise"),
                          ("gaana banane ka tarika batao", "batao"),
                          ("lyrics likhne ka matlab kya hai", "matlab"),
                          ("gaana chahiye kaise banega", "kaise")):
        found = craft.detect(question)
        assert found["is_request"] is False, question
        assert found["reason"] == "explain_intent", question
        assert found["explain_cue"] == cue, question
        assert found["make_cue"] == "" and found["make_kind"] == "", question


def test_a_a_direct_order_is_immune_to_the_explain_guard():
    """
    Seedha hukum ("likho"/"banao") par pehra NAHI lagta.

    Warna "ek gaana likho aur batao kaise likha" — jisme farmaish AUR sawaal
    dono hain — chup-chaap research ban jaata aur gaana gayab ho jaata.
    """
    for question in ("ek sad gaana likho aur batao kaise likha",
                     "gaana banao aur tarika bhi batao",
                     "ek kavita likho aur samjhao matlab kya hai"):
        found = craft.detect(question)
        assert found["is_request"] is True, question
        assert found["make_kind"] == "make", question
        # pehra chala hi nahi, isliye cue bhi darj nahi hota
        assert found["explain_cue"] == "", question


def test_a_the_three_refusal_reasons_stay_separate():
    """
    "cue nahi tha", "cue tha par samjhane ka sawaal tha" aur "kism ka naam nahi
    tha" — teen alag wajah, teen alag naam. Ek naam ho jaaye to audit me kabhi
    pata nahi chalega ki lane kis wajah se band raha.
    """
    # nanga "do" kabhi maangne ka cue nahi ban sakta — warna "solution do",
    # "do line", "do doston ka samvaad" sab farmaish ban jaate
    for question in ("de kar dekho solution do", "solution bhi do",
                     "do line me jawab do"):
        assert craft.detect(question)["reason"] == "no_make_verb", question
    found = craft.detect("ek report banao superconductivity par")
    assert found["is_request"] is False
    assert found["reason"] == "no_form_word"
    # cue mila tha, isliye wo report me zinda rehta hai
    assert found["make_cue"] == "banao" and found["make_kind"] == "make"
    assert craft.detect("gaana kaise likhte hain")["reason"] == "explain_intent"


def test_a_explain_intent_is_a_public_measured_helper():
    """Pehra bahar se naapa ja sake, aur list ka adhoora hona likha ho."""
    assert craft.explain_intent("gaana kaise likhte hain") == "kaise"
    assert craft.explain_intent("gaana banane ka tarika batao") == "batao"
    assert craft.explain_intent("ek sad gaana likho") == ""
    assert craft.explain_intent("") == ""
    # list poori nahi hai — ye baat code me likhi hai, test isi ko pin karta hai
    assert craft.EXPLAIN_CUE_LIST_IS_NOT_EXHAUSTIVE is True


def test_a_research_questions_still_never_enter_craft():
    """
    Sabse zaroori guard: naya want-tier research ko hijack na kar de.

    Ye wahi nau sawaal hain jo `test_craft.py` pin karta hai — yahan dobara
    naape ja rahe hain, kyunki #186b ne darwaza CHAUDA kiya hai aur chauda
    darwaza sabse pehle isi guard ko todta.
    """
    for question in (
            "room temperature superconductivity par latest research kya kehti hai",
            "math basic se strong kaise karun",
            "kaunsa business karu 2026 me",
            "Kabir ki kavita ke baare me batao",
            "Feynman ki kahani batao",
            "RPF SI exam ka syllabus kya hai",
            "nifty ka trading model kaise kaam karta hai",
            "gyan aur vigyan me farak kya hai",
            "mere gaon ka itihas batao"):
        assert craft.detect(question)["is_request"] is False, question


def test_a_the_old_creative_orders_are_untouched():
    """Purani saat farmaish jaisi thi waisi hi chale — kuch ghata nahi."""
    for question, form in (
            ("hindi me tanhai par 8 line ka gaana banao", "song"),
            ("sad punjabi gaana likho", "song"),
            ("ek kavita likho barish par", "poem"),
            ("ek chhoti kahani likho", "story"),
            ("shayari likho do line", "poem"),
            ("ek letter likho principal ko", "letter"),
            ("do doston ka samvaad likho", "dialogue")):
        found = craft.detect(question)
        assert found["is_request"] is True, question
        assert found["form"] == form, question
        assert found["make_kind"] == "make", question


def test_a_the_want_tier_limit_is_written_down_not_hidden():
    """
    Naapi hui seema: "Kabir ki kavita chahiye" bhi banane ki farmaish padhi
    jaati hai. Ise band karna aasan tha par "barish ki kavita chahiye" ki
    shakal bilkul wahi hai — aur wo ASLI farmaish hai. Galat band karna intel
    ki shart todta hai ("maanga hua gaana chup-chaap gayab na ho"), isliye
    khula rakha gaya aur seema LIKHI gayi. Test dono baatein pin karta hai.
    """
    assert craft.detect("Kabir ki kavita chahiye")["is_request"] is True
    assert craft.detect("Kabir ki kavita chahiye")["make_kind"] == "want"
    # asli farmaish, wahi shakal — yahi wajah hai ki upar wala band nahi kiya
    assert craft.detect("barish ki kavita chahiye")["is_request"] is True
    limit = craft.WANT_TIER_KNOWN_LIMIT
    assert isinstance(limit, str) and len(limit) > 120
    for needle in ("chahiye", "label"):
        assert needle in limit, needle


# ── B. #186c — GEHRAI ka naam poore engine me jaana-pehchana ho ──────────────
def test_b_every_read_level_set_in_the_engine_is_a_known_level():
    """
    Poore `research_engine/` me set hone wala har `read_level` literal
    `models.READ_LEVEL_ORDER` ka member ho.

    Ye aam contract hai, ek connector ka patch nahi: `reading_level()` value
    jaisi-ki-taisi lautata hai, `access_depth()` anjaan naam par chup-chaap
    METADATA par gir jaata hai, aur `read_level_counts()` anjaan naam ko ginti
    se hi hata deta hai. Matlab ek galat spelling do jagah jhooth bolti hai aur
    kahin crash nahi karti — isliye pehra static scan par rakha gaya hai.
    """
    pattern = re.compile(r"""read_level["']?\s*[:=]\s*["']([A-Za-z_]*)["']""")
    seen = []
    files = _engine_files()
    assert len(files) >= 30, len(files)
    for path in files:
        with open(path, "r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, 1):
                for value in pattern.findall(line):
                    seen.append((os.path.relpath(path, ROOT), lineno, value))
    # scan khud khaali na ho jaaye — warna ye test hamesha green rahega
    assert len(seen) >= 4, seen
    for where, lineno, value in seen:
        assert value in models.READ_LEVEL_ORDER, (where, lineno, value)


def test_b_the_indirect_read_level_constants_are_known_too():
    """
    Jo jagah constant se level bhejti hai (static scan use nahi dekh sakta),
    us constant ki value bhi jaani-pehchani ho.
    """
    from research_engine import media_study  # noqa: WPS433
    from research_engine.connectors import media_connector  # noqa: WPS433
    assert media_connector.READ_LEVEL in models.READ_LEVEL_ORDER
    assert media_study.DISCOVERED_READ_LEVEL in models.READ_LEVEL_ORDER
    # "gehri padhai" ki definition bhi usi shabdawali se aaye
    from research_engine import exammodel as em  # noqa: WPS433
    for level in tuple(em.DEEP_READ_LEVELS) + tuple(tm.DEEP_READ_LEVELS):
        assert level in models.READ_LEVEL_ORDER, level


def test_b_the_label_table_covers_the_whole_vocabulary():
    """Har level ka apna label ho, aur wo label allowed paanch me se ho."""
    assert sorted(models.ACCESS_DEPTH_LABELS) == sorted(models.READ_LEVEL_ORDER)
    for level in models.READ_LEVEL_ORDER:
        assert models.ACCESS_DEPTH_LABELS[level] in models.ACCESS_DEPTH_ALLOWED
    # "VERIFIED" is shabdawali me jaan-boojh kar nahi hai — gehrai sach hone ka
    # dava nahi hai
    for label in models.ACCESS_DEPTH_ALLOWED:
        assert "VERIFIED" not in label.upper(), label


def test_b_a_fully_read_series_is_labelled_and_counted():
    """#186c ka asli natija: poori padhi hui series poori dikhe aur gini jaaye."""
    record = mc.WorldBankSeriesConnector().record(_series(),
                                                  "https://example.org/s")
    assert record.read_level == "full_text"
    assert record.reading_level() == "full_text"
    assert record.access_depth() == models.ACCESS_FULL == "FULL TEXT ACCESSED"
    assert EvidencePack(sources=[record]).read_level_counts() == {"full_text": 1}


def test_b_an_unknown_level_silently_lies_in_two_places():
    """
    Negative control — yahi wo do jhooth hain jo "full" likhne se hote the.

    Ye test #186c ki WAJAH pin karta hai: galti crash nahi karti, chup-chaap
    (a) label ko METADATA ONLY kar deti hai — yaani "content dekha hi nahi" —
    aur (b) source ko ginti se hata deti hai. Isi liye upar wala static scan
    zaroori hai.
    """
    record = mc.WorldBankSeriesConnector().record(_series(),
                                                  "https://example.org/s")
    record.read_level = "full"          # READ_LEVEL_ORDER me nahi hai
    assert record.reading_level() == "full"          # value jaisi-ki-taisi
    assert record.access_depth() == models.ACCESS_METADATA
    assert EvidencePack(sources=[record]).read_level_counts() == {}


# ── C. #186d — TRADE ka cue: har 17 phrase par teen-tarfa naap ───────────────
def test_c_every_failure_cue_is_actually_matched():
    """
    Har cue par poori ladder: number ke saath MET, bina number NOT_MET.

    Pehle sirf 6 cue the aur unme "failure classification" nahi tha — spec ka
    sabse aam sarkari phrase. Natija: point NOT_MEASURED ("zikr nahi mila")
    reh jaata tha, jise report me "ye naapa hi nahi gaya" padha jaata hai
    jabki spec me wo poora likha hota tha.
    """
    cues = tm._POINT_CUES["failure_classification"]
    assert len(cues) >= 17, len(cues)
    for cue in cues:
        with_number = _trade_row(f"Model spec.\n{cue} ke hisaab se 12 loss "
                                 f"aur 3 class bani.\n")
        assert with_number["status"] == tm.MET, (cue, with_number["status"])
        without = _trade_row(f"Model spec.\n{cue} ka poora hisaab likha "
                             f"gaya hai.\n")
        # naam lena naap nahi hai — number ke bina MET kabhi nahi
        assert without["status"] == tm.NOT_MET, (cue, without["status"])


def test_c_the_official_phrase_no_longer_slips_through():
    """Wahi do phrase jo #186a me naape gaye the — ab pakde jaate hain."""
    for cue in ("failure classification", "loss classification", "per-loss",
                "post-mortem"):
        assert tm._has(tm._norm(f"is model ka {cue} 12 loss par"), cue), cue
        row = _trade_row(f"Testing.\n{cue}: 12 loss, 4 class.\n")
        assert row["status"] == tm.MET, cue


def test_c_no_mention_stays_not_measured_not_fine():
    """
    Zikr hi na ho to NOT_MEASURED — aur reason me saaf likha ho ki ise "theek
    hai" na padha jaaye. "Naapa nahi gaya" aur "naap ke baad theek nikla" ek
    jaise dikhna sabse khatarnak jhooth hai.
    """
    row = _trade_row("Model spec.\nEntry 15M context par, 5M confirmation.\n")
    assert row["status"] == tm.NOT_MEASURED
    assert "zikr nahi mila" in row["observed"]
    assert "theek hai" in row["reason"]


def test_c_widening_a_cue_can_never_weaken_a_met():
    """
    Cue chauda karna sirf NOT_MEASURED → MET/NOT_MET kar sakta hai.

    Wajah: number ki shart cue se alag lagti hai. Isliye ek nakli chauda cue
    daal kar bhi bina-number wala spec MET nahi ban sakta.
    """
    original = tm._POINT_CUES["failure_classification"]
    try:
        tm._POINT_CUES["failure_classification"] = original + ("nakli cue",)
        row = _trade_row("Testing.\nnakli cue ka zikr, koi ginti nahi.\n")
        assert row["status"] == tm.NOT_MET
    finally:
        tm._POINT_CUES["failure_classification"] = original
    assert tm._POINT_CUES["failure_classification"] == original


# ── D. #186e — BOL ki talaash: naam se nahi, SANDARBH se pakdi jaati hai ─────
def test_d_a_multi_word_title_before_lyrics_is_caught():
    """
    "lyrics" se ulta chal kar naam-jaisa shabd-jhund milta hai to ye maujooda
    gaane ke BOL ki maang hai — aur us par craft/listener/music lane band hoti
    hai, kyunki app ke paas copyright wale bol likhne ka koi kaam nahi hai.
    """
    for question in ("tum hi ho song lyrics",
                     "arijit singh tum hi ho song lyrics likh do",
                     "channa mereya lyrics",
                     "kal ho na ho song lyrics",
                     "tera ban jaunga song lyrics",
                     "apna bana le piya lyrics"):
        assert sc.is_lyrics_hunt(question) is True, question
        reason = sc.title_hunt_reason(question)
        assert reason.startswith("naam jaisa shabd-jhund"), (question, reason)
    assert sc.TITLE_HUNT_MIN_RUN == 2


def test_d_a_bare_one_word_title_query_is_caught():
    """Sirf naam + jodne wale shabd + "lyrics" — isme koi topic nahi hai."""
    for question in ("kesariya song lyrics", "kesariya ka song lyrics",
                     "chaleya gaane ke lyrics"):
        assert sc.is_lyrics_hunt(question) is True, question
        assert sc.title_hunt_reason(question).startswith(
            "sirf naam aur bol ki maang"), question


def test_d_a_topic_ask_is_never_a_title_hunt():
    """
    Sabse zaroori half: mood/topic par gaana maangna banane ki farmaish hai.

    Yahan galat pakadna intel ki shart todta hai — gaana chup-chaap gayab ho
    jaata aur uski jagah "bol nahi likhenge" ka jawab aata.
    """
    for question in ("ek sad gaana likho",
                     "ek sad song ki lyrics likho",
                     "breakup song lyrics likho",
                     "monsoon song lyrics likho",
                     "barish par song lyrics likho",
                     "tanhai wale gaane ki lyrics likho",
                     "mere gaon ki yaad par gaana ki lyrics likho",
                     "punjabi dance wala gaana chahiye",
                     "gangster type punjabi song lyrics banao",
                     "hindi me ek emotional gaana ki lyrics likh do",
                     "sad lyrics kaise likhte hain",
                     "songwriting craft lyric writing guide",
                     "prosody meter syllable stress in song lyrics"):
        assert sc.is_lyrics_hunt(question) is False, question
        assert sc.title_hunt_reason(question) == "", question


def test_d_the_app_never_trips_its_own_guard():
    """
    App khud jo query banata hai, unme se ek bhi "bol ki talaash" na lage.

    Yahi wajah hai ki shabdkosh app ke APNE table se banta hai: naya style ya
    naya seed jodne par shabdkosh khud chauda ho jaata hai, aur guard apne hi
    kaam par nahi girta.
    """
    generated = set()
    for style in sc.STYLES:
        generated.update(style.study_terms)
    for _lang_id, label, _cues in sc.LANGUAGE_ASKS:
        generated.add(f"{label} song lyric writing tradition structure")
    for query, _lane, _why in sc.CRAFT_STUDY_SEEDS:
        generated.add(query)
    for text in ("sad punjabi gaana likho", "gangstar rap likho",
                 "ek gaana likho", "shudh hindi me bhajan likho",
                 "hindi me romantic gaana banao", "tamil me romantic gaana likho",
                 "kids ke liye simple gaana banao", "lofi indie sad gaana likho"):
        for row in sc.study_queries(sc.style_of(text)):
            generated.add(row["query"])
    assert len(generated) >= 30, len(generated)
    for query in sorted(generated):
        assert sc.is_lyrics_hunt(query) is False, query


def test_d_the_vocabulary_grows_with_the_apps_own_tables():
    """
    Shabdkosh hand-typed list nahi hai — wo module ke apne table se banta hai.

    Sabooot: ek naya seed daalo jisme ek anjaan shabd ho, cache saaf karo, aur
    wo shabd apne aap "jaana hua" ho jaata hai — yaani guard us par nahi girta.
    """
    word = "zzqqx"
    query = f"{word} song lyrics"
    assert sc.is_lyrics_hunt(query) is True         # abhi anjaan hai
    original_seeds = sc.CRAFT_STUDY_SEEDS
    original_cache = sc._CRAFT_VOCAB_CACHE
    try:
        sc.CRAFT_STUDY_SEEDS = tuple(original_seeds) + (
            (f"{word} songwriting technique study", "craft", "test"),)
        sc._CRAFT_VOCAB_CACHE = None
        assert word in sc.craft_vocabulary()
        assert sc.is_lyrics_hunt(query) is False    # ab jaana hua shabd hai
    finally:
        sc.CRAFT_STUDY_SEEDS = original_seeds
        sc._CRAFT_VOCAB_CACHE = original_cache
    assert sc.is_lyrics_hunt(query) is True         # bahaal
    assert len(sc.craft_vocabulary()) >= 300
    assert sc.CRAFT_FRAME_LIST_IS_NOT_EXHAUSTIVE is True


def test_d_a_craft_ask_made_of_the_apps_own_words_is_never_a_title_hunt():
    """
    Craft ki baat karne wale shabd (`_CRAFT_FRAME_WORDS`) vocabulary ka BOJH
    uthaate hain — sirf saja nahi hain.

    Naapa gaya: in 41 shabd me se 41 sirf isi table se aate hain (baaki table
    style/bhasha ke naam rakhte hain). Table hata do to neeche ki chhah ASLI
    craft farmaish "naam jaisa shabd-jhund" ban jaati hai aur teeno song lane
    (craft + listener + music) chup-chaap band ho jaati hain — yaani padhna
    band, gaana kamzor. Isliye ye baat behaviour par pin ki gayi hai, table ke
    naam par nahi.
    """
    for question in ("songwriter notes lyrics analysis",
                     "study notes lyrics writing",
                     "music theory book lyrics structure",
                     "composing techniques lyrics ke saath samjhao",
                     "kavita kitaab lyrics convention",
                     "poem examples lyrics structure"):
        assert sc.title_hunt_reason(question) == "", question
        assert sc.is_lyrics_hunt(question) is False, question
    # ...aur app ke apne shabd app ki apni vocabulary me hon
    vocab = sc.craft_vocabulary()
    missing = [w for w in sc._CRAFT_FRAME_WORDS if w.lower() not in vocab]
    assert missing == [], missing



def test_d_the_remaining_limit_is_written_down_not_hidden():
    """
    Ek anjaan shabd + koi teesra shabd — ye shakal aaj bhi nahi pakdi jaati.

    Kyun jaan-boojh kar: "monsoon song lyrics likho" ki shakal bilkul wahi hai
    aur wo ASLI banane ki farmaish hai. Galat pakadne par craft + listener +
    music teen lane band ho jaati aur gaana kamzor banta. Do buraiyon me ye
    chhoti hai, isliye seema LIKHI gayi hai — chupi nahi.
    """
    for question in ("chaleya song lyrics chahiye", "kesariya song lyrics likho"):
        assert sc.is_lyrics_hunt(question) is False, question
    limit = sc.LYRICS_HUNT_KNOWN_LIMIT
    assert isinstance(limit, str) and len(limit) > 120
    for needle in ("anjaan shabd", "TOPIC"):
        assert needle in limit, needle


def test_d_the_old_regex_behaviour_is_a_strict_subset():
    """
    #186e ne guard sirf CHAUDA kiya — purana jo True tha wo True hi rahe.

    `is_lyrics_hunt` pehle regex chalata hai, phir naam wali parat. Isliye jo
    string pehle pakdi jaati thi wo aaj bhi pakdi jaati hai, aur ye niyam
    yahan naapa jaata hai (dono raste alag-alag).
    """
    for question in ("gaane ke bol download", "song download free",
                     "tum hi ho mp3", "karaoke track hindi",
                     "lyrics of tum hi ho", "full lyrics tum hi ho"):
        assert sc._LYRICS_HUNT_RE.search(question) or sc.title_hunt_reason(question)
        assert sc.is_lyrics_hunt(question) is True, question
    # regex wali baat naam-parat par nirbhar na ho
    assert sc._LYRICS_HUNT_RE.search("gaane ke bol download") is not None


def test_d_the_guard_is_a_wall_in_all_three_song_lanes():
    """
    Ek hi faisla, teen lane: craft, listener, music. `title_hunt_reason` se
    khula naya raasta bhi in teeno ko band karta hai — kyunki teeno `is_lyrics_
    hunt` hi poochhte hain. Agar kal kisi ne ek lane ko seedha regex par laga
    diya, ye test us lane ko pakad lega.
    """
    from research_engine import depth as depth_mod  # noqa: WPS433
    from research_engine.planner import ResearchPlanner  # noqa: WPS433

    planner = ResearchPlanner()
    config = depth_mod.get_depth_config("DEEP")
    hunted = "arijit singh tum hi ho song lyrics likho"
    assert sc.title_hunt_reason(hunted), "ye string naam-parat se hi pakdi jani thi"
    plan = planner.connector_plan({"question": hunted}, config, hunted)
    for key in ("craft_study", "listener_study", "music_study"):
        assert plan[key] == [], (key, plan[key])
        lane = plan[key + "_lane"]
        assert lane["wanted"] is False
        assert lane["lyrics_hunt_blocked"] is True
        assert "BOL" in lane["reason"], (key, lane["reason"])
    # ...aur banane wali farmaish par teeno lane zinda rehti hain
    alive_q = "hindi me tanhai par sad gaana likho"
    alive = planner.connector_plan({"question": alive_q}, config, alive_q)
    for key in ("craft_study", "listener_study", "music_study"):
        assert alive[key], key
        assert alive[key + "_lane"]["wanted"] is True, key










