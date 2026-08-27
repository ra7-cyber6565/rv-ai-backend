"""
#115 — do cheezein: (1) uploaded document ka ingest asli me chalta hai,
(2) kachcha library error kabhi user ke saamne nahi jaata.

Asli bug jo ye file pin karti hai: `rag/pipeline.py` lazy ho gaya tha
(`get_client()` / `get_embedding_model()`), par `vector_search.ingest_chunks`
purane module-attribute `pipeline.client` / `pipeline.embedding_model` maang
raha tha — jo wahan ab hai hi nahi. Nateeja: HAR chunk-ingest `AttributeError`
deta tha, upload chup-chaap fail hota tha, aur wahi raw line
`AttributeError: module 'rag.pipeline' has no attribute 'client'`ban kar
report me user ko dikh jaati thi.

Purana test isliye green tha ki uska stub NAKLI shape ka tha (usme `client`
attribute maujood tha). Isliye yahan **dono** shape hain, aur ek static
contract bhi hai jo source padh kar naam milata hai — taaki agli baar naam
badle to test khud pakde, stub nahi bachaye.

Offline: koi network, koi chromadb, koi Gemini.
"""
from __future__ import annotations

import ast
import os
import re
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.vector_search import (VEC_DB_MISSING,       # noqa: E402
                                           VEC_DB_SHAPE,
                                           VEC_NO_TEXT,
                                           VEC_NOTHING_LEFT,
                                           VEC_READ_FAILED,
                                           VEC_REASON_CODES,
                                           VEC_REASON_WHY,
                                           VEC_WRITE_FAILED,
                                           VectorSearch,
                                           _clean_processing_error)

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHUNK = {"locator": "p.1", "text": "yahan asli padhne layak text hai"}


class _Coll:
    def __init__(self):
        self.calls = []

    def add(self, **kwargs):
        self.calls.append(("add", kwargs))

    def upsert(self, **kwargs):
        self.calls.append(("upsert", kwargs))


class _Emb:
    def encode(self, documents):
        class Encoded:
            def tolist(self):
                return [[0.1] for _ in documents]
        return Encoded()


def _pipeline(shape: str, collection=None):
    """`shape` = 'lazy' (asli 2026 shape), 'legacy' (purane attribute), 'gone'."""
    module = types.ModuleType("rag.pipeline")
    module.split_text = lambda text, chunk_size=500: [text]
    coll = collection if collection is not None else _Coll()
    module.collection = coll
    client = types.SimpleNamespace(get_or_create_collection=lambda name: coll)
    if shape == "lazy":
        module.get_client = lambda: client
        module.get_embedding_model = lambda: _Emb()
    elif shape == "legacy":
        module.client = client
        module.embedding_model = _Emb()
    return module


def _read(rel: str) -> str:
    with open(os.path.join(_BACKEND, rel), "r", encoding="utf-8",
              errors="replace") as handle:
        return handle.read()


# ── A. asli bug ka pin ───────────────────────────────────────────────────────

def test_ingest_works_against_the_real_lazy_pipeline_shape():
    """
    Sabse zaroori pin: `rag/pipeline.py` ke asli shape (sirf `get_client()` /
    `get_embedding_model()`) par ingest sach me chalta hai. Isi jagah #115 ka
    bug tha — aur yahi test pehle nahi tha.
    """
    coll = _Coll()
    vs = VectorSearch()
    vs._pipeline = _pipeline("lazy", coll)
    report = vs.ingest_chunks([CHUNK], "meri.pdf", "p1")
    assert report["ok"] is True, report
    assert report["chunks"] == 1
    assert report["error"] == "" and report["reason_code"] == ""
    assert vs.last_reason_code == ""
    assert [name for name, _ in coll.calls] == ["add"]


def test_ingest_still_works_on_the_older_attribute_shape():
    """Purana shape bhi chalta rahe — kuch hataya nahi gaya, sirf joda gaya."""
    vs = VectorSearch()
    vs._pipeline = _pipeline("legacy")
    assert vs.ingest_chunks([CHUNK], "meri.pdf", "p1")["ok"] is True


def test_a_resumable_namespace_still_upserts_instead_of_adding():
    """#115 ka fix idempotent raste ko nahi toda."""
    coll = _Coll()
    vs = VectorSearch()
    vs._pipeline = _pipeline("lazy", coll)
    first = vs.ingest_chunks([CHUNK], "book.pdf", "p1", id_namespace="read_x:7")
    second = vs.ingest_chunks([CHUNK], "book.pdf", "p1", id_namespace="read_x:7")
    assert first["ok"] and second["ok"]
    assert [name for name, _ in coll.calls] == ["upsert", "upsert"]
    assert coll.calls[0][1]["ids"] == coll.calls[1][1]["ids"]


def test_a_renamed_pipeline_is_reported_as_our_bug_not_as_a_file_problem():
    vs = VectorSearch()
    vs._pipeline = _pipeline("gone")
    report = vs.ingest_chunks([CHUNK], "meri.pdf", "p1")
    assert report["ok"] is False and report["chunks"] == 0
    assert report["reason_code"] == VEC_DB_SHAPE
    assert "tumhari file ki nahi" in report["error"]
    # raw wajah gayab nahi hui — bas andar rahi
    assert "AttributeError" in vs.last_error


# ── B. kachcha error bahar nahi jaata ────────────────────────────────────────

_RAW_MARKERS = ("Error:", "Exception", "Traceback", "chromadb", "rag.pipeline",
                "sqlite", "get_client", "attribute", "/", "\\")


def _assert_user_safe(text: str):
    for marker in _RAW_MARKERS:
        assert marker not in text, (marker, text)


def test_every_user_facing_reason_is_human_and_carries_no_library_text():
    assert len(VEC_REASON_CODES) == len(set(VEC_REASON_CODES)) == 6
    assert set(VEC_REASON_CODES) == set(VEC_REASON_WHY)
    for code in VEC_REASON_CODES:
        why = VEC_REASON_WHY[code]
        assert len(why.strip()) > 60, code
        _assert_user_safe(why)
    assert len({v.strip() for v in VEC_REASON_WHY.values()}) == 6


def test_a_database_write_failure_hides_the_path_but_admits_the_failure():
    """
    Sabse khatarnak jhooth "save ho gaya" hai, isliye ok=False rehna chahiye —
    par message me na sqlite ka naam jaaye na server ka path.
    """
    module = _pipeline("lazy")
    module.get_client = lambda: types.SimpleNamespace(
        get_or_create_collection=lambda name: (_ for _ in ()).throw(
            RuntimeError("attempt to write a readonly database: "
                         "/data/chroma_db/chroma.sqlite3")))
    vs = VectorSearch()
    vs._pipeline = module
    report = vs.ingest_chunks([CHUNK], "meri.pdf", "p1")
    assert report["ok"] is False
    assert report["reason_code"] == VEC_WRITE_FAILED
    _assert_user_safe(report["error"])
    assert "save nahi ho paayi" in report["error"]
    assert "/data/chroma_db" in vs.last_error      # debugging ke liye andar hai


def test_a_missing_vector_database_says_available_nahi_without_the_import_text():
    class _NoRag:
        def find_module(self, name, path=None):
            return self if name == "rag" or name.startswith("rag.") else None

        def load_module(self, name):
            raise ImportError("No module named 'chromadb'")

    hook = _NoRag()
    saved = sys.modules.pop("rag", None)
    sys.meta_path.insert(0, hook)
    try:
        vs = VectorSearch()
        report = vs.ingest_chunks([CHUNK], "meri.pdf", "p1")
    finally:
        sys.meta_path.remove(hook)
        if saved is not None:
            sys.modules["rag"] = saved
    assert report["ok"] is False
    assert report["reason_code"] == VEC_DB_MISSING
    assert "available nahi" in report["error"]     # purana contract kayam
    _assert_user_safe(report["error"])


def test_an_empty_file_is_not_blamed_on_the_database():
    vs = VectorSearch()
    vs._pipeline = _pipeline("lazy")
    report = vs.ingest_chunks([{"locator": "p.1", "text": "   "}], "khali.pdf", "p1")
    assert report["ok"] is False
    assert report["reason_code"] == VEC_NO_TEXT
    assert report["skipped_empty"] == 1
    _assert_user_safe(report["error"])


def test_text_that_vanishes_in_splitting_has_its_own_reason():
    module = _pipeline("lazy")
    module.split_text = lambda text, chunk_size=500: ["   "]
    vs = VectorSearch()
    vs._pipeline = module
    report = vs.ingest_chunks([CHUNK], "meri.pdf", "p1")
    assert report["reason_code"] == VEC_NOTHING_LEFT
    assert report["ok"] is False


def test_retrieval_failures_are_separated_and_never_leak_the_exception():
    module = _pipeline("lazy")
    module.get_context_only = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("chromadb collection corrupt at /data/chroma_db"))
    vs = VectorSearch()
    vs._pipeline = module
    assert vs.retrieve("kya likha hai", "p1") == {"context": "", "sources": []}
    assert vs.last_reason_code == VEC_READ_FAILED
    _assert_user_safe(vs.problem_note())

    gone = _pipeline("lazy")            # get_context_only hi nahi hai
    vs2 = VectorSearch()
    vs2._pipeline = gone
    assert vs2.retrieve("kya likha hai", "p1") == {"context": "", "sources": []}
    assert vs2.last_reason_code == VEC_DB_SHAPE


def test_a_successful_retrieval_clears_the_old_complaint():
    """Purani dikkat ka note baad ke saaf jawab ke saath na chipke."""
    module = _pipeline("lazy")
    module.get_context_only = lambda *a, **k: {"context": "text", "sources": []}
    vs = VectorSearch()
    vs._pipeline = module
    vs.last_reason_code = VEC_READ_FAILED
    vs.retrieve("kya likha hai", "p1")
    assert vs.last_reason_code == ""
    assert vs.problem_note() == ""


def test_a_good_ingest_after_a_bad_one_drops_the_old_reason():
    """
    Ek khaali file ke baad achhi file aaye to report me purani shikayat na
    chipke — warna user ko saaf-suthre upload par bhi dikkat dikhegi.
    """
    vs = VectorSearch()
    vs._pipeline = _pipeline("lazy")
    bad = vs.ingest_chunks([{"locator": "p.1", "text": "  "}], "khali.pdf", "p1")
    assert bad["reason_code"] == VEC_NO_TEXT
    good = vs.ingest_chunks([CHUNK], "meri.pdf", "p1")
    assert good["ok"] is True
    assert vs.last_reason_code == ""
    assert vs.problem_note() == ""


def test_processing_errors_lose_the_path_and_the_exception_class_only():
    raw = "PDF khul nahi rahi: FileDataError: cannot open C:\\Users\\intel\\a.pdf"
    clean = _clean_processing_error(raw)
    assert "PDF khul nahi rahi" in clean
    assert "C:\\Users" not in clean and "FileDataError" not in clean
    assert _clean_processing_error("") == ""
    # asli wajah poori nahi kaati jaati — warna user ko kuch pata hi na chale
    assert "cannot open" in clean


# ── B2. ingest_file — asli file, asli processing (offline) ───────────────────

def _tmp_file(name: str, body: str) -> str:
    import tempfile
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return path


def test_a_real_text_file_travels_all_the_way_into_the_database():
    """
    Poora rasta: DocumentProcessor → chunks → lazy pipeline → collection.add.
    #115 se pehle ye rasta chalta hi nahi tha, isliye ek asli file par pin.
    """
    coll = _Coll()
    vs = VectorSearch()
    vs._pipeline = _pipeline("lazy", coll)
    path = _tmp_file("notes.txt", "yahan asli padhne layak text hai, "
                                  "aur ye kaafi lamba bhi hai taaki chunk bane.")
    out = vs.ingest_file(path, "p1", use_ocr=False)
    assert out["ok"] is True, out
    assert out["chunks"] >= 1
    assert out["error"] == "" and out["reason_code"] == ""
    assert [name for name, _ in coll.calls] == ["add"]


def test_a_file_that_cannot_be_opened_reports_the_reason_without_the_path():
    """
    processing/ ka message app ka hi likha hua hai (`file nahi mili: /tmp/...`),
    par usme local path hota hai. User ko wajah mile, path nahi.
    """
    vs = VectorSearch()
    vs._pipeline = _pipeline("lazy")
    out = vs.ingest_file("/tmp/aisi-koi-file-nahi-hai.pdf", "p1", use_ocr=False)
    assert out["ok"] is False
    assert out["chunks"] == 0
    assert out["reason_code"] == VEC_NO_TEXT
    assert out["error"].strip() != ""             # chup-chaap khaali nahi
    _assert_user_safe(out["error"])
    assert "aisi-koi-file-nahi-hai" in vs.last_error   # andar poori baat hai


# ── C. static contract — agli baar naam badla to yahin pakda jaaye ───────────

def test_vector_search_only_asks_rag_pipeline_for_names_that_exist():
    """
    #115 ka asli sabak: stub ne shape ka jhooth chhupa liya tha. Ye test kisi
    stub par nahi, source par chalta hai — `vector_search.py` jo bhi naam
    `rag.pipeline` se maangti hai, wo `rag/pipeline.py` me module level par
    hona chahiye.
    """
    tree = ast.parse(_read(os.path.join("research_engine", "vector_search.py")))
    wanted = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "pipeline":
                wanted.add(node.attr)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Call):
            call = node.value
            if (isinstance(call.func, ast.Attribute)
                    and call.func.attr == "_rag"):
                wanted.add(node.attr)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_resolve"):
            for arg in node.args[1:2]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    wanted.add(arg.value)
    assert {"get_client", "get_embedding_model", "split_text",
            "get_context_only"} <= wanted, sorted(wanted)

    pipeline_tree = ast.parse(_read(os.path.join("rag", "pipeline.py")))
    defined = set()
    for node in pipeline_tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined.add(target.id)
    missing = sorted(name for name in wanted if name not in defined)
    assert not missing, f"rag/pipeline.py me ye naam nahi hain: {missing}"


def _function(source: str, name: str) -> ast.AST:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} orchestrator me nahi mila")


def test_the_research_note_uses_the_clean_reason_not_the_raw_error():
    """
    orchestrator ka document-note answer me chhapta hai. Wo `problem_note()`
    padhe, `last_error` nahi — warna #115 wapas aa jaayega. Comment nahi,
    asli code padha jaata hai (AST), taaki comment ka shabd test na todein
    aur code ka shabd chhup na sake.
    """
    source = _read(os.path.join("research_engine", "orchestrator.py"))
    node = _function(source, "_document_records")
    used = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
    used |= {n.value for n in ast.walk(node)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "problem_note" in used
    assert "last_error" not in used, sorted(used)
    # naam sirf string me hai isliye asli class par bhi maujood hona chahiye
    assert callable(getattr(VectorSearch(), "problem_note", None))
    # aur wajah sach me note me judni chahiye — sirf padh kar phenk dena bhi
    # #115 hi hai (user ko pata na chale ki uski file kyun nahi padhi gayi)
    joined = False
    for n in ast.walk(node):
        if not (isinstance(n, ast.If) and isinstance(n.test, ast.Name)
                and n.test.id == "problem"):
            continue
        for inner in ast.walk(n):
            if (isinstance(inner, ast.AugAssign)
                    and isinstance(inner.target, ast.Name)
                    and inner.target.id == "note"
                    and any(isinstance(x, ast.Name) and x.id == "problem"
                            for x in ast.walk(inner.value))):
                joined = True
    assert joined, "saaf wajah note me judti hi nahi"
    # aur poore orchestrator me kahin bhi vectors.last_error na padha jaaye
    whole = ast.parse(source)
    for n in ast.walk(whole):
        if (isinstance(n, ast.Attribute) and n.attr == "last_error"
                and isinstance(n.value, ast.Attribute)):
            assert n.value.attr != "vectors", "orchestrator raw error padh raha hai"
    assert re.search(r"vector search error", source) is None


def test_a_vector_stub_without_the_new_method_does_not_break_research():
    """
    Benchmark/test ke chhote stub me `problem_note` nahi hota. Note na milna
    research rok de — ye #115 ka ilaaj nahi, naya bug hota.
    """
    class _Bare:
        def retrieve(self, *a, **k):
            return {"context": "", "sources": []}

    source = _read(os.path.join("research_engine", "orchestrator.py"))
    node = _function(source, "_document_records")
    calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "getattr"]
    assert calls, "problem_note seedha bulaya ja raha hai — stub par crash karega"
    reason = getattr(_Bare(), "problem_note", None)
    assert (reason() if callable(reason) else "") == ""
