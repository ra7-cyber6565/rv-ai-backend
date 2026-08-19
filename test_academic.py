from rag.academic_sources import (
    search_openalex, search_semantic_scholar, search_pubmed,
    search_crossref, search_doaj, search_internet_archive, search_google_books
)
import json

query = "battery technology energy storage"

print("=== OpenAlex ===")
r = search_openalex(query, 2)
print(f"Found: {len(r)}")
print(json.dumps(r, indent=2, ensure_ascii=False))

print("\n=== Semantic Scholar ===")
r = search_semantic_scholar(query, 2)
print(f"Found: {len(r)}")
print(json.dumps(r, indent=2, ensure_ascii=False))

print("\n=== PubMed ===")
r = search_pubmed(query, 2)
print(f"Found: {len(r)}")
print(json.dumps(r, indent=2, ensure_ascii=False))

print("\n=== Crossref ===")
r = search_crossref(query, 2)
print(f"Found: {len(r)}")
print(json.dumps(r, indent=2, ensure_ascii=False))

print("\n=== DOAJ ===")
r = search_doaj(query, 2)
print(f"Found: {len(r)}")
print(json.dumps(r, indent=2, ensure_ascii=False))

print("\n=== Internet Archive ===")
r = search_internet_archive(query, 2)
print(f"Found: {len(r)}")
print(json.dumps(r, indent=2, ensure_ascii=False))

print("\n=== Google Books ===")
r = search_google_books(query, 2)
print(f"Found: {len(r)}")
print(json.dumps(r, indent=2, ensure_ascii=False))