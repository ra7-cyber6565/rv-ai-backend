import fitz  # PyMuPDF
import chromadb
from dotenv import load_dotenv
import os
import re

load_dotenv()

# ── LAZY LOADING (crash-proof boot) ──────────────────────────────────────────
_embedding_model = None
_client = None


def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        cache_folder = os.getenv("SENTENCE_TRANSFORMERS_HOME") or None
        _embedding_model = SentenceTransformer(
            "all-MiniLM-L6-v2",
            cache_folder=cache_folder,
        )
    return _embedding_model


def get_client():
    global _client
    if _client is None:
        db_path = os.getenv("CHROMA_DB_DIR", "./chroma_db")
        os.makedirs(db_path, exist_ok=True)
        _client = chromadb.PersistentClient(path=db_path)
    return _client


def _reason(prompt: str) -> tuple[str, dict]:
    """One logical reasoning pass through the same ₹0-safe provider router.

    This replaces the legacy `google.generativeai` direct call. A RAG caller can
    no longer bypass Gemini zero-cost confirmation/provider fallback policy.
    Raw provider exceptions never leave this helper.
    """
    from research_engine.reasoning_router_integrated import ResilientReasoning

    brain = ResilientReasoning(budget=1, model_name=os.getenv(
        "GEMINI_MODEL", "gemini-flash-latest"
    ))
    try:
        text = brain.generate(prompt, "rag_answer")
    except Exception:
        text = ""
    try:
        accounting = brain.api_accounting()
    except Exception:
        accounting = {}
    safe = {
        key: accounting.get(key)
        for key in (
            "logical_reasoning_calls", "passes_with_output", "actual_http_attempts",
            "same_model_retries", "model_switches", "provider_fallbacks",
        )
        if key in accounting
    }
    return str(text or "").strip(), safe


def ingest_pdf(pdf_bytes: bytes, filename: str, project_id: str) -> dict:
    """PDF ko chunks mein todo aur ChromaDB mein store karo."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    chunks, metadatas, ids = [], [], []

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text()
        page_chunks = split_text(text, chunk_size=500)

        for i, chunk in enumerate(page_chunks):
            if chunk.strip():
                chunk_id = f"{filename}_p{page_num+1}_c{i}"
                chunks.append(chunk)
                metadatas.append({"source": filename, "page": page_num + 1})
                ids.append(chunk_id)

    if not chunks:
        return {"chunks": 0}
    collection = get_client().get_or_create_collection(name=f"project_{project_id}")
    embeddings = get_embedding_model().encode(chunks).tolist()
    collection.add(
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
        ids=ids,
    )
    return {"chunks": len(chunks)}


def _short_extract(text: str, words: int = 36) -> str:
    clean = " ".join(str(text or "").split())
    parts = clean.split()
    clipped = " ".join(parts[:words])
    return clipped + ("…" if len(parts) > words else "")


def _document_only_answer(context_rows: list[tuple[str, dict]]) -> str:
    """No-model fallback using only retrieved document chunks.

    This is intentionally extractive/conservative. It never fabricates a general
    knowledge answer when all model providers are unavailable.
    """
    if not context_rows:
        return ""
    lines = [
        "Reasoning model available nahi tha, lekin uploaded documents se ye relevant "
        "hisse mile. Inhe final synthesis nahi, evidence extract samjhein:"
    ]
    for doc, meta in context_rows[:4]:
        source = (meta or {}).get("source", "unknown")
        page = (meta or {}).get("page", "?")
        lines.append(f"- {_short_extract(doc)} [Source: {source}, Page {page}]")
    return "\n".join(lines)


def ask_question(question: str, project_id: str) -> dict:
    """Legacy document-Q&A helper, now quota-resilient and fail-closed.

    Normal public `/api/v1/ask` already uses the full research manager. This
    helper remains for backwards compatibility but no longer calls Gemini
    directly or exposes raw SDK exceptions.
    """
    collection = get_client().get_or_create_collection(name=f"project_{project_id}")

    q_embedding = get_embedding_model().encode([question]).tolist()
    results = collection.query(query_embeddings=q_embedding, n_results=5)
    documents = (results.get("documents") or [[]])[0] or []
    metadatas = (results.get("metadatas") or [[]])[0] or []

    if not documents:
        prompt = f"""Tum ek helpful assistant ho. Is sawal ke liye uploaded document context nahi mila.
General knowledge use kar sakte ho, lekin unverified/current baat ko pakka fact mat bolo.
Agar reliable answer nahi ban raha to saaf bolo.

Sawal: {question}\n\nJawab:"""
        text, accounting = _reason(prompt)
        if text:
            return {
                "answer": text,
                "sources": [],
                "evidence_level": "⚠️ General knowledge (uploaded documents se nahi)",
                "reasoning_accounting": accounting,
                "degraded": bool(accounting.get("provider_fallbacks")),
            }
        return {
            "answer": (
                "Is project ke uploaded documents mein is sawal ka relevant context nahi "
                "mila aur koi configured reasoning model bhi is pass mein available nahi "
                "tha. Guess ko fact ki tarah dene ke bajay answer UNKNOWN rakha gaya."
            ),
            "sources": [],
            "evidence_level": "UNKNOWN",
            "reasoning_accounting": accounting,
            "degraded": True,
        }

    context_parts = []
    sources = []
    rows: list[tuple[str, dict]] = []
    for doc, meta in zip(documents, metadatas):
        meta = meta or {}
        source_name = meta.get("source", "unknown")
        page = meta.get("page", "?")
        context_parts.append(f"[Source: {source_name}, Page {page}]\n{doc}")
        rows.append((doc, meta))
        entry = {"file": source_name, "page": page}
        if entry not in sources:
            sources.append(entry)

    context = "\n\n".join(context_parts)
    prompt = f"""Tum ek research assistant ho. Sirf neeche diye uploaded-document context ke base par jawab do.
Har important baat ke saath source/page do. Document mein jawab nahi ho to saaf bolo.

Documents:\n{context}\n\nSawal: {question}\n\nJawab:"""

    text, accounting = _reason(prompt)
    if not text:
        text = _document_only_answer(rows)

    return {
        "answer": text or "Available document text se reliable answer establish nahi hua.",
        "sources": sources,
        "evidence_level": "✅ Document-based" if accounting.get("passes_with_output") else "⚠️ Document extract only",
        "reasoning_accounting": accounting,
        "degraded": not bool(accounting.get("passes_with_output")),
    }


def split_text(text: str, chunk_size: int = 500) -> list:
    """Text ko chhote chunks mein todo."""
    sentences = re.split(r"(?<=[।.!?]) +", text)
    chunks, current = [], ""
    for sentence in sentences:
        if len(current) + len(sentence) <= chunk_size:
            current += " " + sentence
        else:
            if current:
                chunks.append(current.strip())
            current = sentence
    if current:
        chunks.append(current.strip())
    return chunks


def get_context_only(question: str, project_id: str, n_results: int = 8) -> dict:
    """Sirf relevant documents dhoondo, koi reasoning provider call NAHI."""
    collection = get_client().get_or_create_collection(name=f"project_{project_id}")
    q_embedding = get_embedding_model().encode([question]).tolist()
    results = collection.query(query_embeddings=q_embedding, n_results=n_results)

    documents = (results.get("documents") or [[]])[0] or []
    metadatas = (results.get("metadatas") or [[]])[0] or []
    if not documents:
        return {"context": "", "sources": []}

    context_parts = []
    sources = []
    for doc, meta in zip(documents, metadatas):
        meta = meta or {}
        source_name = meta.get("source", "unknown")
        page = meta.get("page", "?")
        context_parts.append(f"[Source: {source_name}, Page {page}]\n{doc}")
        entry = {"file": source_name, "page": page}
        if entry not in sources:
            sources.append(entry)

    return {"context": "\n\n".join(context_parts), "sources": sources}
