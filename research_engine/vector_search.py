"""
VectorSearch — Spec Section 16 (vector_search.py)

Ye naya vector DB nahi banata. Project mein already ChromaDB + MiniLM ka
pipeline hai (rag/pipeline.py) jo test ho chuka hai — ye uske upar ek saaf
adapter hai, taaki research_engine ka baaki code rag/ ke internals se juda na ho.

Fayda: kal ChromaDB badal do, sirf ye file badlegi.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .models import SourceRecord, SourceType


class VectorSearch:
    def __init__(self, default_results: int = 8):
        self.default_results = default_results
        self._pipeline = None
        self.last_error: str = ""

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
            self.last_error = f"{type(exc).__name__}: {exc}"
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
            return self._rag().get_context_only(
                question, project_id, n_results=n_results or self.default_results)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return {"context": "", "sources": []}

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
            self.last_error = f"{type(exc).__name__}: {exc}"
            return {"ok": False, "error": self.last_error, "chunks": 0}

    # ── ingestion (Spec Section 3/4/5 — processing/ ko DB se jodta hai) ───────
    def ingest_chunks(self, chunks: List[Dict], filename: str,
                      project_id: str) -> Dict:
        """
        processing/ se aaye chunks ko ChromaDB mein daalo.

        chunks ka shape DocumentProcessor/TranscriptProcessor wala hai:
            {"locator": "p.7" | "12:30–14:30", "text": "...", "header": "..."}

        Metadata jaan-boojh kar rag/pipeline.py ke shape mein likha jaata hai
        ({"source", "page"}), kyunki get_context_only() usi ko padhta hai.
        Transcript ke liye "page" mein timestamp jaata hai — isse citation
        "[Source: talk.vtt, Page 12:30]" jaisi banti hai, jo sach hai.
        """
        report = {"ok": False, "chunks": 0, "error": "", "skipped_empty": 0}
        usable = [c for c in (chunks or []) if (c.get("text") or "").strip()]
        report["skipped_empty"] = len(chunks or []) - len(usable)
        if not usable:
            report["error"] = "koi non-empty chunk nahi mila"
            return report

        try:
            pipeline = self._rag()
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            report["error"] = f"vector DB available nahi: {self.last_error}"
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
                ids.append(f"{filename}_{index}_{part_no}_{abs(hash(piece)) % 10**6}")

        if not documents:
            report["error"] = "split ke baad kuch nahi bacha"
            return report

        try:
            collection = pipeline.client.get_or_create_collection(
                name=f"project_{project_id}")
            embeddings = pipeline.embedding_model.encode(documents).tolist()
            collection.add(documents=documents, embeddings=embeddings,
                           metadatas=metadatas, ids=ids)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            report["error"] = f"ChromaDB write fail: {self.last_error}"
            return report

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
               "chars": len(processed.get("text") or ""), "error": ""}

        if not processed.get("ok"):
            out["error"] = processed.get("error") or "file process nahi hui"
            return out

        stored = self.ingest_chunks(processed.get("chunks") or [], name, project_id)
        out["chunks"] = stored.get("chunks", 0)
        out["ok"] = stored.get("ok", False)
        if not out["ok"]:
            out["error"] = stored.get("error", "")
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
