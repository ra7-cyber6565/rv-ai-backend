import fitz  # PyMuPDF
import chromadb
import google.generativeai as genai
from dotenv import load_dotenv
import os
import re

load_dotenv()

# ── LAZY LOADING (crash-proof boot) ──────────────────────────────────────────
# Pehle yahan module import hote hi SentenceTransformer('all-MiniLM-L6-v2') load
# ho jaata tha. Iska matlab: app start hote hi torch + model (~300MB+) memory
# mein aa jaate the — free-tier server par ye slow boot ya OOM crash karta tha.
_embedding_model = None
_client = None
_gemini = None


def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        cache_folder = os.getenv("SENTENCE_TRANSFORMERS_HOME") or None
        _embedding_model = SentenceTransformer(
            'all-MiniLM-L6-v2',
            cache_folder=cache_folder,
        )
    return _embedding_model


def get_client():
    global _client
    if _client is None:
        # main.py configures CHROMA_DB_DIR from INFINITY_DATA_ROOT before this
        # module is imported. Standalone use still has a backwards-compatible
        # repository-local fallback.
        db_path = os.getenv("CHROMA_DB_DIR", "./chroma_db")
        os.makedirs(db_path, exist_ok=True)
        _client = chromadb.PersistentClient(path=db_path)
    return _client


def get_gemini():
    global _gemini
    if _gemini is None:
        from research_engine.gemini_model import resolve

        genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))
        # Model ka naam Google ki asli list se — hard-coded naam kai keys par
        # InvalidArgument/NotFound deta hai.
        _gemini = genai.GenerativeModel(resolve(genai))
    return _gemini


def ingest_pdf(pdf_bytes: bytes, filename: str, project_id: str) -> dict:
    """
    PDF ko chunks mein todo aur ChromaDB mein store karo.
    """
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

    collection = get_client().get_or_create_collection(name=f"project_{project_id}")
    embeddings = get_embedding_model().encode(chunks).tolist()
    collection.add(
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
        ids=ids
    )
    return {"chunks": len(chunks)}


def ask_question(question: str, project_id: str) -> dict:
    """
    Sawal poocho — relevant chunks dhoondo — Gemini se jawab lo.
    """
    collection = get_client().get_or_create_collection(name=f"project_{project_id}")

    q_embedding = get_embedding_model().encode([question]).tolist()
    results = collection.query(query_embeddings=q_embedding, n_results=5)

    if not results["documents"][0]:
        fallback_prompt = f"""Tum ek research assistant ho. Tumhare paas is sawal ke liye koi document/PDF nahi hai.
Apne general knowledge se jawab do, lekin:
1. Saaf batao ki ye jawab documents se nahi, tumhare general knowledge se hai
2. Agar tumhe confidence kam hai, to wo bhi batao
3. Anuman ko fact ki tarah pesh mat karo

Sawal: {question}

Jawab:"""
        fallback_response = get_gemini().generate_content(fallback_prompt)
        return {
            "answer": fallback_response.text,
            "sources": [],
            "evidence_level": "⚠️ General Knowledge (documents se nahi)"
        }
    context_parts = []
    sources = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        meta = meta or {}
        source_name = meta.get("source", "unknown")
        page = meta.get("page", "?")
        context_parts.append(f"[Source: {source_name}, Page {page}]\n{doc}")
        entry = {"file": source_name, "page": page}
        if entry not in sources:
            sources.append(entry)

    context = "\n\n".join(context_parts)

    prompt = f"""Tum ek research assistant ho. Neeche diye gaye documents ke base par sawal ka jawab do.
Har important baat ke saath source aur page number batao.
Agar jawab documents mein nahi hai to saaf bolo.

Documents:
{context}

Sawal: {question}

Jawab (source + page number ke saath):"""

    response = get_gemini().generate_content(prompt)

    return {
        "answer": response.text,
        "sources": sources,
        "evidence_level": "✅ Document-based"
    }


def split_text(text: str, chunk_size: int = 500) -> list:
    """Text ko chhote chunks mein todo"""
    sentences = re.split(r'(?<=[।.!?]) +', text)
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
    """
    Sirf relevant documents dhoondo, Gemini ko call NAHI karo (free operation)
    """
    collection = get_client().get_or_create_collection(name=f"project_{project_id}")
    q_embedding = get_embedding_model().encode([question]).tolist()
    results = collection.query(query_embeddings=q_embedding, n_results=n_results)

    if not results["documents"][0]:
        return {"context": "", "sources": []}

    context_parts = []
    sources = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        meta = meta or {}
        source_name = meta.get("source", "unknown")
        page = meta.get("page", "?")
        context_parts.append(f"[Source: {source_name}, Page {page}]\n{doc}")
        entry = {"file": source_name, "page": page}
        if entry not in sources:
            sources.append(entry)

    return {"context": "\n\n".join(context_parts), "sources": sources}
