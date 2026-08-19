import fitz  # PyMuPDF
import chromadb
from sentence_transformers import SentenceTransformer
import google.generativeai as genai
from dotenv import load_dotenv
import os
import re

load_dotenv()

# Models initialize करो
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
client = chromadb.PersistentClient(path="./chroma_db")

genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))
gemini = genai.GenerativeModel('gemini-flash-latest')


def ingest_pdf(pdf_bytes: bytes, filename: str, project_id: str) -> dict:
    """
    PDF को chunks में तोड़ो और ChromaDB में store करो
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

    collection = client.get_or_create_collection(name=f"project_{project_id}")
    embeddings = embedding_model.encode(chunks).tolist()
    collection.add(
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
        ids=ids
    )
    return {"chunks": len(chunks)}


def ask_question(question: str, project_id: str) -> dict:
    """
    सवाल पूछो — relevant chunks ढूंढो — Gemini से जवाब लो
    """
    collection = client.get_or_create_collection(name=f"project_{project_id}")

    q_embedding = embedding_model.encode([question]).tolist()
    results = collection.query(query_embeddings=q_embedding, n_results=5)

    if not results["documents"][0]:
        # Koi document nahi mila -> General Knowledge se jawab do
        fallback_prompt = f"""Tum ek research assistant ho. Tumhare paas is sawal ke liye koi document/PDF nahi hai.
Apne general knowledge se jawab do, lekin:
1. Saaf batao ki ye jawab documents se nahi, tumhare general knowledge se hai
2. Agar tumhe confidence kam hai, to wo bhi batao
3. Anuman ko fact ki tarah pesh mat karo

Sawal: {question}

Jawab:"""
        fallback_response = gemini.generate_content(fallback_prompt)
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

    prompt = f"""तुम एक research assistant हो। नीचे दिए गए documents के आधार पर सवाल का जवाब दो।
हर बात के साथ source और page number ज़रूर बताओ।
अगर जवाब documents में नहीं है तो साफ़ बोलो।

Documents:
{context}

सवाल: {question}

जवाब (source + page number के साथ):"""

    response = gemini.generate_content(prompt)

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
    collection = client.get_or_create_collection(name=f"project_{project_id}")
    q_embedding = embedding_model.encode([question]).tolist()
    results = collection.query(query_embeddings=q_embedding, n_results=n_results)

    if not results["documents"][0]:
        return {"context": "", "sources": []}

    context_parts = []
    sources = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        # .get() jaan-boojh kar: metadata ab do jagah se aata hai — purana
        # ingest_pdf ({"source","page"}) aur naya ingest_chunks (jahan "page"
        # mein timestamp jaisa locator ho sakta hai). Direct meta['page'] karne
        # se ek missing key poori retrieval gira deti thi.
        meta = meta or {}
        source_name = meta.get("source", "unknown")
        page = meta.get("page", "?")
        context_parts.append(f"[Source: {source_name}, Page {page}]\n{doc}")
        entry = {"file": source_name, "page": page}
        if entry not in sources:
            sources.append(entry)

    return {"context": "\n\n".join(context_parts), "sources": sources}
