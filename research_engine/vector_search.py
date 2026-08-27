"""
VectorSearch — Spec Section 16 (vector_search.py)

Ye naya vector DB nahi banata. Project mein already ChromaDB + MiniLM ka
pipeline hai (rag/pipeline.py) jo test ho chuka hai — ye uske upar ek saaf
adapter hai, taaki research_engine ka baaki code rag/ ke internals se juda na ho.

Fayda: kal ChromaDB badal do, sirf ye file badlegi.
"""
from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Optional

from .models import SourceRecord, SourceType

# ── #115: kachcha error user ko nahi dikhega ──────────────────────────────────
# Pehle har fail par raw exception text hi report mein chala jaata tha, aur
# orchestrator use answer ke "Research process" note mein jod deta tha. User ko
# `AttributeError: module 'rag.pipeline' has no attribute 'client'` jaisi line
# dikhti thi — usme library ka naam hota, aur sqlite/permission fail par local
# path bhi aa sakta tha. Ab do alag cheezein hain:
#   * `last_error`       — raw text, SIRF server ke andar (debugging ke liye)
#   * `last_reason_code` — kya hua, ek naap-ne-yogya code
#   * `problem_note()`   — user ke liye saaf Hinglish line (code se banti hai,
#                          exception ke text se NAHI — isliye leak structurally
#                          possible hi nahi hai)
VEC_DB_MISSING = "VECTOR_DB_MISSING"
VEC_DB_SHAPE = "VECTOR_DB_SHAPE_CHANGED"
VEC_READ_FAILED = "VECTOR_READ_FAILED"
VEC_WRITE_FAILED = "VECTOR_WRITE_FAILED"
VEC_NO_TEXT = "VECTOR_NO_TEXT"
VEC_NOTHING_LEFT = "VECTOR_NOTHING_AFTER_SPLIT"

VEC_REASON_CODES = (VEC_DB_MISSING, VEC_DB_SHAPE, VEC_READ_FAILED,
                    VEC_WRITE_FAILED, VEC_NO_TEXT, VEC_NOTHING_LEFT)

VEC_REASON_WHY = {
    VEC_DB_MISSING:
        "Is server par document-search ka database available nahi hai "
        "(bhaari packages install nahi hain), isliye uploaded document is baar "
        "padha nahi ja saka.",
    VEC_DB_SHAPE:
        "Document-search ka andar ka hissa badal gaya hai, isliye ye adapter "
        "usse baat nahi kar paaya — ye app ki apni galti hai, tumhari file ki "
        "nahi. File kahin delete nahi hui.",
    VEC_READ_FAILED:
        "Document-search chala, par uploaded documents mein se kuch padha nahi "
        "ja saka, isliye ye jawab unke bina bana hai.",
    VEC_WRITE_FAILED:
        "Tumhari file process ho gayi thi, par document-search ke database "
        "mein save nahi ho paayi — isliye 'store ho gaya' nahi kaha ja sakta.",
    VEC_NO_TEXT:
        "Is file mein padhne layak text nahi mila (khaali ya sirf image-scan "
        "ho sakti hai), isliye store karne ke liye kuch tha hi nahi.",
    VEC_NOTHING_LEFT:
        "Text tha, par chunk banane ke baad kuch bacha nahi — isliye database "
        "mein kuch nahi gaya aur ye jawab is file ke bina bana hai.",
}


# processing/ ke message app ke hi likhe hue hain, par unme raw exception
# (`AttributeError: ...`) aur kabhi local path (`file nahi mili: C:\Users\...`)
# jud jaata hai. Ye function sirf wahi tokens hataata hai — baaki Hinglish
# wajah user tak jaati hai, kyunki "kuch nahi hua" bolna jhooth hota.
_EXC_TOKEN = re.compile(r"^[A-Za-z_]*(Error|Exception|Warning)$")


def _clean_processing_error(text: str, limit: int = 220) -> str:
    kept = []
    for token in " ".join(str(text or "").split()).split(" "):
        bare = token.rstrip(":,;.")
        if _EXC_TOKEN.match(bare):
            continue
        if "/" in token or "\\" in token or re.match(r"^[A-Za-z]:$", bare):
            continue
        kept.append(token)
    clean = " ".join(kept).strip(" :,-;")
    return clean[:limit]


class VectorSearch:
    def __init__(self, default_results: int = 8):
        self.default_results = default_results
        self._pipeline = None
        self.last_error: str = ""
        self.last_reason_code: str = ""

    # ── error hygiene ────────────────────────────────────────────────────────
    def _fail(self, code: str, exc: Optional[BaseException] = None) -> str:
        """Raw wajah andar rakho, user ke liye saaf line lautao."""
        self.last_reason_code = code
        if exc is not None:
            self.last_error = f"{type(exc).__name__}: {exc}"
        return VEC_REASON_WHY[code]

    def problem_note(self) -> str:
        """User/report ke liye: aakhri dikkat kya thi. Raw text kabhi nahi."""
        return VEC_REASON_WHY.get(self.last_reason_code, "")

    # ── rag/pipeline.py se judne ke do naam ──────────────────────────────────
    # rag/pipeline.py lazy ho gaya (`get_client()` / `get_embedding_model()`),
    # par ye file purane module-attribute (`client` / `embedding_model`) maang
    # rahi thi — wo attribute wahan ab hai hi nahi. Nateeja: HAR chunk-ingest
    # AttributeError deta tha aur upload chup-chaap fail hota tha. Ab accessor
    # pehle, purana attribute fallback — dono shape chalte hain.
    @staticmethod
    def _resolve(pipeline, getter_name: str, legacy_name: str):
        getter = getattr(pipeline, getter_name, None)
        if callable(getter):
            return getter()
        legacy = getattr(pipeline, legacy_name, None)
        if legacy is not None:
            return legacy
        raise AttributeError(
            f"rag.pipeline: na {getter_name}() hai na {legacy_name}")

    def _client(self, pipeline):
        return self._resolve(pipeline, "get_client", "client")

    def _embedder(self, pipeline):
        return self._resolve(pipeline, "get_embedding_model", "embedding_model")

    def _rag(self):
        """Lazy import — chromadb + sentence-transformers bhaari hain."""
        if self._pipeline is None:
            from rag import pipeline  # noqa: WPS433 (intentional lazy import)
            self._pipeline = pipeline
        return self._pipeline

    @property
    def available(self) -> bool:
        try:
            self._rag()
            return True
        except Exception as exc:
            self._fail(VEC_DB_MISSING, exc)
            return False

    # ── retrieval ────────────────────────────────────────────────────────────
    def retrieve(self, question: str, project_id: str,
                 n_results: Optional[int] = None) -> Dict:
        """
        Returns rag.pipeline.get_context_only() ka shape:
            {"context": str, "sources": [{"file","page"}]}
        Error aaye to khaali context — research rukna nahi chahiye.
        """
        try:
            pipeline = self._rag()
        except Exception as exc:
            self._fail(VEC_DB_MISSING, exc)
            return {"context": "", "sources": []}
        try:
            out = pipeline.get_context_only(
                question, project_id, n_results=n_results or self.default_results)
        except AttributeError as exc:
            self._fail(VEC_DB_SHAPE, exc)
            return {"context": "", "sources": []}
        except Exception as exc:
            self._fail(VEC_READ_FAILED, exc)
            return {"context": "", "sources": []}
        # kaam ho gaya to purani dikkat ka note aage na jaaye
        self.last_reason_code = ""
        return out

    def ingest_pdf_bytes(self, content: bytes, filename: str,
                         project_id: str) -> Dict:
        """
        Purana seedha PDF path (rag.pipeline.ingest_pdf). Isme OCR nahi hai.

        NOTE: pehle is class mein `ingest(file_path, project_id)` tha jo
        `ingest_pdf(file_path, project_id)` call karta tha — par asli signature
        `ingest_pdf(pdf_bytes, filename, project_id)` hai. Wo call hamesha
        TypeError deta aur except block use chup-chaap kha jaata tha. Isliye
        naam aur signature theek kar diye.
        """
        try:
            return {"ok": True, **self._rag().ingest_pdf(content, filename, project_id)}
        except Exception as exc:
            return {"ok": False, "chunks": 0,
                    "error": self._fail(VEC_WRITE_FAILED, exc),
                    "reason_code": self.last_reason_code}

    # ── ingestion (Spec Section 3/4/5 — processing/ ko DB se jodta hai) ───────
    def ingest_chunks(self, chunks: List[Dict], filename: str,
                      project_id: str, id_namespace: str = "") -> Dict:
        """
        processing/ se aaye chunks ko ChromaDB mein daalo.

        chunks ka shape DocumentProcessor/TranscriptProcessor wala hai:
            {"locator": "p.7" | "12:30–14:30", "text": "...", "header": "..."}

        Metadata jaan-boojh kar rag/pipeline.py ke shape mein likha jaata hai
        ({"source", "page"}), kyunki get_context_only() usi ko padhta hai.
        Transcript ke liye "page" mein timestamp jaata hai — isse citation
        "[Source: talk.vtt, Page 12:30]" jaisi banti hai, jo sach hai.
        """
        report = {"ok": False, "chunks": 0, "error": "", "skipped_empty": 0,
                  "reason_code": ""}
        usable = [c for c in (chunks or []) if (c.get("text") or "").strip()]
        report["skipped_empty"] = len(chunks or []) - len(usable)
        if not usable:
            report["error"] = self._fail(VEC_NO_TEXT)
            report["reason_code"] = self.last_reason_code
            return report

        try:
            pipeline = self._rag()
        except Exception as exc:
            report["error"] = self._fail(VEC_DB_MISSING, exc)
            report["reason_code"] = self.last_reason_code
            return report

        documents: List[str] = []
        metadatas: List[Dict] = []
        ids: List[str] = []
        for index, chunk in enumerate(usable):
            text = chunk["text"].strip()
            locator = str(chunk.get("locator") or f"part {index + 1}")
            # bade chunk ko aur todo, taaki embedding quality na gire
            for part_no, piece in enumerate(pipeline.split_text(text, chunk_size=500)):
                if not piece.strip():
                    continue
                documents.append(piece.strip())
                metadatas.append({"source": filename, "page": locator})
                # Python's built-in hash is process-randomised and six digits
                # are collision-prone across resumed book batches.  A stable
                # namespace + locator + content digest makes retries and
                # multi-session ingestion deterministic without exposing a
                # raw project capability in the stored id.
                identity = "\0".join((
                    str(id_namespace or "one-shot"), filename, locator,
                    str(part_no), piece,
                ))
                digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
                ids.append(f"chunk_{digest}")

        if not documents:
            report["error"] = self._fail(VEC_NOTHING_LEFT)
            report["reason_code"] = self.last_reason_code
            return report

        try:
            collection = self._client(pipeline).get_or_create_collection(
                name=f"project_{project_id}")
            embeddings = self._embedder(pipeline).encode(documents).tolist()
            write = collection.upsert if id_namespace else collection.add
            write(documents=documents, embeddings=embeddings,
                  metadatas=metadatas, ids=ids)
        except AttributeError as exc:
            # naam badal gaya (jaise 2026-08-27 wala `pipeline.client` bug) —
            # ye app ka bug hai, user ko library ka naam dikhana bemaani hai
            report["error"] = self._fail(VEC_DB_SHAPE, exc)
            report["reason_code"] = self.last_reason_code
            return report
        except Exception as exc:
            report["error"] = self._fail(VEC_WRITE_FAILED, exc)
            report["reason_code"] = self.last_reason_code
            return report

        self.last_reason_code = ""
        report.update({"ok": True, "chunks": len(documents)})
        return report

    def ingest_file(self, file_path: str, project_id: str,
                    use_ocr: bool = True, filename: str = "") -> Dict:
        """
        Kisi bhi supported file ko process karke DB mein daalo:
        pdf (OCR fallback ke saath), docx, txt, md, html, vtt, srt.

        Ye wahi rasta hai jo pehle missing tha — processing/ ke modules ab
        yahan se actually chalte hain.
        """
        from .processing import DocumentProcessor

        name = filename or (file_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])
        processed = DocumentProcessor().process(file_path, use_ocr=use_ocr)
        out = {"ok": False, "file": name, "kind": processed.get("kind", ""),
               "notes": processed.get("notes", []), "chunks": 0,
               "chars": len(processed.get("text") or ""), "error": "",
               "reason_code": ""}

        if not processed.get("ok"):
            # processing/ ke message me raw exception aur kabhi local path bhi
            # hota hai (`file nahi mili: C:\...`) — user ke liye saaf karo,
            # raw baat `last_error` mein rakho.
            raw = str(processed.get("error") or "")
            self.last_error = raw or "DocumentProcessor: ok=False"
            self.last_reason_code = VEC_NO_TEXT
            out["error"] = (_clean_processing_error(raw)
                            or "Ye file padhi nahi ja saki — usme se text nahi mila.")
            out["reason_code"] = VEC_NO_TEXT
            return out

        stored = self.ingest_chunks(processed.get("chunks") or [], name, project_id)
        out["chunks"] = stored.get("chunks", 0)
        out["ok"] = stored.get("ok", False)
        if not out["ok"]:
            out["error"] = stored.get("error", "")
            out["reason_code"] = stored.get("reason_code", "")
        return out

    # ── convenience ──────────────────────────────────────────────────────────
    def as_records(self, retrieval: Dict, file_hint: str = "") -> List[SourceRecord]:
        """
        Document chunks ko SourceRecord banata hai. Detail parsing
        EvidenceEngine.records_from_retrieval() karta hai; ye sirf ek
        light-weight fallback hai jab context ek hi blob ho.
        """
        context = (retrieval or {}).get("context", "")
        if not context.strip():
            return []
        sources = (retrieval or {}).get("sources", []) or []
        name = sources[0].get("file") if sources else (file_hint or "uploaded document")
        return [SourceRecord(
            title=f"{name} (uploaded document)",
            url="",
            snippet=context[:1500],
            connector="vector_search",
            source_type=SourceType.DOCUMENT,
            locator=", ".join(
                f"p.{s.get('page')}" for s in sources[:6] if s.get("page")),
            is_primary=True,
            full_text_available=True,
            # ye file ingest ke waqt poori process hui thi — label yahan
            # explicitly lagta hai, models.py andaza nahi lagata
            read_level="full_text",
        )]
