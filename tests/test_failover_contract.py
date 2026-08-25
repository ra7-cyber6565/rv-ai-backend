"""
Failover contract — Railway (primary) + Render (backup) + Cloudflare Worker.

Yeh tests us behaviour ko pakadte hain jispar "app band nahi hoga" tika hai, aur
un teen jhooth ko rokte hain jo aise setup me sabse aasani se ghus jaate hain:

  1. backup host par app boot hi na ho (bhaari dependency slim list me reh jaye),
  2. app ke khud ke 500 par bhi backup par dobara bhej dena — ek hi kaam do baar,
  3. switch chupke se ho jaye aur user ko pata na chale ki uska lamba research
     us server par maujood hi nahi hai.

Koi network nahi, koi host nahi — sab kuch repo ke andar ke faislon par hai.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_HEAVY = ("chromadb", "sentence-transformers", "sentence_transformers", "torch")


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _pins(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, _, version = line.partition("==")
        out[name.strip().casefold()] = version.strip()
    return out


def _worker() -> str:
    return _read("deploy", "cloudflare_worker.js")


def _index() -> str:
    return _read("web", "index.html")


# ---------------------------------------------------------------- slim install

def test_slim_list_drops_the_two_heavy_packages_and_nothing_else():
    """Backup host 512 MB par hai. chromadb/torch wahan OOM karte hain, isliye
    slim list se sirf yehi do nikalte hain — baaki ek bhi package nahi."""
    base = _pins(_read("requirements.txt"))
    slim = _pins(_read("requirements-slim.txt"))
    missing = sorted(set(base) - set(slim))
    assert missing == ["chromadb", "sentence-transformers"]
    assert not set(slim) - set(base)          # slim me koi naya package nahi


def test_slim_list_keeps_every_pin_identical_to_the_base_file():
    """Dono host ek hi code chalate hain. Version alag hue to bug ek host par
    dikhega aur doosre par nahi — wahi debug ka sabse mehnga jhooth hai."""
    base = _pins(_read("requirements.txt"))
    slim = _pins(_read("requirements-slim.txt"))
    for name, version in slim.items():
        assert version == base[name], name


def test_slim_list_can_still_boot_the_web_app():
    """Slim karte-karte fastapi/uvicorn nikal jaana = backup host boot hi nahi
    hoga. Yeh test us fisalne ko pakadta hai."""
    slim = _pins(_read("requirements-slim.txt"))
    for need in ("fastapi", "uvicorn[standard]", "pydantic", "google-generativeai"):
        assert need in slim


def test_slim_header_states_the_lost_feature_in_plain_words():
    """Feature chup-chaap gayab nahi hota: file khud likhti hai ki is host par
    user ki apni PDF ka search band rahega."""
    head = _read("requirements-slim.txt").split("fastapi==")[0].casefold()
    assert "pdf" in head
    assert "band" in head
    assert "requirements.txt" in head          # base file ki jagah nahi leta


# ------------------------------------------- slim host par app zinda rehta hai

class _NoRag:
    """`from rag import pipeline` ko us host jaisa fail karata hai jahan
    chromadb/sentence-transformers install hi nahi hue."""

    def __enter__(self):
        self._had = "rag" in sys.modules
        self._old = sys.modules.get("rag")
        sys.modules["rag"] = None              # import ko halt karta hai
        return self

    def __exit__(self, *exc):
        if self._had:
            sys.modules["rag"] = self._old
        else:
            sys.modules.pop("rag", None)
        return False


def test_without_the_heavy_packages_retrieval_degrades_instead_of_crashing():
    """Yeh slim list ka asli sabooot: bhaari package na hone par bhi research
    chalta rehta hai, bas document-context khaali aata hai."""
    from research_engine.vector_search import VectorSearch

    with _NoRag():
        vs = VectorSearch()
        assert vs.available is False
        out = vs.retrieve("kya likha hai", "proj-1")
        assert out == {"context": "", "sources": []}
        assert vs.last_error                    # chupke se nahi — wajah likhi hai


def test_without_the_heavy_packages_ingest_reports_failure_not_success():
    """Sabse khatarnak jhooth: upload "ho gaya" bol dena jab store hua hi nahi.
    Backup host par upload saaf-saaf fail hona chahiye."""
    from research_engine.vector_search import VectorSearch

    with _NoRag():
        report = VectorSearch().ingest_chunks(
            [{"locator": "p.1", "text": "kuch likha hua hai yahan"}],
            "mera.pdf", "proj-1")
        assert report["ok"] is False
        assert report["chunks"] == 0
        assert "available nahi" in report["error"]


def test_uploaded_document_records_are_never_born_verified():
    """Backup ho ya primary — user ki apni di hui copy khud ko saboot nahi
    bana sakti; wo DOCUMENT hi rehti hai."""
    from research_engine.models import SourceType
    from research_engine.vector_search import VectorSearch

    records = VectorSearch().as_records(
        {"context": "yahan asli text hai", "sources": [{"file": "mera.pdf", "page": 3}]})
    assert len(records) == 1
    assert records[0].source_type == SourceType.DOCUMENT
    assert records[0].connector == "vector_search"


# ------------------------------------------------------------------ render.yaml

def test_render_builds_the_slim_list_not_the_full_one():
    """Render free 512 MB hai. Poori list wahan build/boot par mar jaati hai.
    Header me naam likha hona kaafi nahi — buildCommand khud slim padhe."""
    yaml = _read("render.yaml")
    assert re.search(r"buildCommand:.*requirements-slim\.txt", yaml)
    assert not re.search(r"-r\s+requirements\.txt", yaml)


def test_render_exposes_the_health_path_the_worker_reads():
    """Worker `/health` dekh kar tay karta hai kaun zinda hai. Path badla —
    `/healthz` bhi — to failover andha ho jaata hai."""
    yaml = _read("render.yaml")
    assert re.search(r"healthCheckPath:\s*/health\s*$", yaml, re.M)
    assert re.search(r"startCommand:.*uvicorn main:app", yaml)
    assert re.search(r"plan:\s*free", yaml)


def test_render_config_holds_no_secret_values():
    """Keys sirf naam se aati hain (`sync: false`), value repo me kabhi nahi."""
    yaml = _read("render.yaml")
    assert "GEMINI_API_KEY" in yaml
    assert yaml.count("sync: false") >= 2
    assert "AIza" not in yaml                  # Google key ka prefix
    for line in yaml.splitlines():
        if "GEMINI" in line and "value:" in line:
            assert "true" in line.casefold()   # sirf zero-cost flag, koi key nahi


def test_zero_cost_flags_travel_to_the_backup_host():
    """Backup par ZERO_COST_ONLY chhoot gaya to wahan kharcha ho sakta hai —
    aur intel ki ek hi sakht shart hai: total cost ₹0."""
    yaml = _read("render.yaml")
    assert re.search(r"-\s*key:\s*ZERO_COST_ONLY", yaml)
    assert re.search(r"-\s*key:\s*GEMINI_ZERO_COST_CONFIRMED", yaml)


# ----------------------------------------------------- cloudflare worker ka niyam

def test_worker_fails_over_only_on_gateway_level_failure():
    """502/503/504 ka matlab: app ne request PADHI hi nahi. Sirf tab dobara
    bhejna safe hai."""
    js = _worker()
    found = re.search(r"GATEWAY_DOWN\s*=\s*new Set\(\[([^\]]*)\]\)", js)
    assert found
    codes = sorted(int(x) for x in re.findall(r"\d+", found.group(1)))
    assert codes == [502, 503, 504]


def test_worker_never_retries_an_app_level_500():
    """App ka khud ka 500 matlab code andar tak chala. Dobara bhejna = ek hi
    research do baar = quota aur jhootha doosra jawab."""
    js = _worker()
    found = re.search(r"GATEWAY_DOWN\s*=\s*new Set\(\[([^\]]*)\]\)", js)
    assert "500" not in re.findall(r"\d+", found.group(1))
    # aur code me kahin 500 ko down-list me jodne ka doosra rasta na ho
    assert not re.search(r"GATEWAY_DOWN\.add", js)


def test_worker_tags_every_answer_with_the_host_that_gave_it():
    """Chupke se switch hona hi sabse bada jhooth hota. Har jawab par likha
    rehta hai kaun bola."""
    js = _worker()
    assert 'set("X-RV-Origin"' in js
    assert 'tagged(response, "primary"' in js
    assert 'tagged(response, "backup"' in js


def test_worker_refuses_to_replay_an_upload_it_could_not_buffer():
    """Body buffer nahi hui to backup par wahi file dobara bhejna possible nahi.
    Chup-chaap adhoora bhejne se behtar hai saaf mana karna."""
    js = _worker()
    assert "failover_body_too_large" in js
    assert re.search(r"if\s*\(!replayable\)", js)
    assert re.search(r"MAX_BUFFERED_BODY\s*=", js)


def test_worker_carries_no_secret_of_any_kind():
    """Worker sirf do public URL padhta hai. Koi teesra env — jaise koi key —
    edge par nahi aana chahiye; keys server ke environment me hi rehti hain."""
    js = _worker()
    for banned in ("GEMINI_API_KEY", "TAVILY_API_KEY", "USPTO_ODP_API_KEY",
                   "AIza", "Authorization", "Bearer "):
        assert banned not in js
    assert set(re.findall(r"env\.([A-Za-z0-9_]+)", js)) == {
        "RV_PRIMARY_BASE", "RV_BACKUP_BASE"}


def test_worker_keeps_the_sleepy_backup_awake():
    """Render free 15 minute me so jaata hai aur uthne me 30-60 second leta hai.
    Cron dono ka /health chhoo kar us intezaar ko hata deta hai."""
    js = _worker()
    assert re.search(r"async scheduled\(", js)
    assert '"/health"' in js or "'/health'" in js or '+ "/health"' in js


def test_worker_does_not_leak_the_client_ip_or_host_header_onward():
    js = _worker()
    assert 'headers.delete("host")' in js
    assert 'headers.delete("cf-connecting-ip")' in js


# ------------------------------------------------------ website ki apni parat

def test_page_switches_only_on_the_same_gateway_codes_as_the_worker():
    """Do jagah do niyam ho gaye to ek parat 500 par bhi switch kar degi. Dono
    list ek honi chahiye, aur 500 kisi me nahi."""
    page = _index()
    found = re.search(r"DEAD_GATEWAY\s*=\s*\[([^\]]*)\]", page)
    assert found
    codes = sorted(int(x) for x in re.findall(r"\d+", found.group(1)))
    assert codes == [0, 502, 503, 504]
    worker_codes = re.search(r"GATEWAY_DOWN\s*=\s*new Set\(\[([^\]]*)\]\)", _worker())
    assert set(re.findall(r"\d+", worker_codes.group(1))) <= set(str(c) for c in codes)


def test_page_tells_the_user_that_a_long_research_must_be_resent():
    """intel ka chuna hua rasta: saaf batao aur dobara shuru karo. Adhoore
    jawab ko poora dikhana mana hai."""
    page = _index()
    body = re.search(r"function announceFailover\(\)\{.*?\n\}", page, re.S).group(0)
    low = body.casefold()
    assert "backup" in low
    assert "dobara" in low                     # dobara bhejna padega
    assert "pdf" in low                        # kaunsa feature band hai


def test_page_resets_the_project_session_when_it_switches_hosts():
    """Purane host ka project id backup par maujood nahi. Use pakad kar rakhna
    "tumhaari file mil gayi" jaisa jhooth banata."""
    page = _index()
    body = re.search(r"function switchToBackup\(\)\{.*?\n\}", page, re.S).group(0)
    assert "resetProjectSession()" in body
    assert "announceFailover()" in body
    assert "API=FAILOVER.backup" in body


def test_page_never_treats_itself_as_its_own_backup():
    """Worker na ho ya galat value aaye to page khud par loop maar sakta tha."""
    page = _index()
    body = re.search(r"async function loadFailoverInfo\(\)\{.*?\n\}", page, re.S).group(0)
    assert "safeHttpUrl(" in body
    assert "location.origin" in body


def test_page_boots_the_failover_lookup_but_does_not_depend_on_it():
    """Worker na ho to yeh call fail hoti hai aur page bilkul aaj jaisa chalta
    hai — isliye API khaali string se shuru hota hai, koi hard-coded host nahi."""
    page = _index()
    assert re.search(r"^let API=\"\";", page, re.M)
    assert "loadFailoverInfo();" in page
    assert "onrender.com" not in page          # host ka pata code me nahi
    assert "up.railway.app" not in page


def test_setup_doc_states_the_two_deliberate_limits():
    doc = _read("docs", "FAILOVER_SETUP.md").casefold()
    assert "500" in doc                        # 500 par failover nahi
    assert "pip install -r requirements-slim.txt" in doc
    assert "x-rv-origin" in doc
    assert "aiza" not in doc                   # doc me bhi koi key nahi
