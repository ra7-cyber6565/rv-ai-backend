from rag.web_search import search_web
import json
results = search_web("Pabuji Rajasthan lok devta", max_results=5)
print(json.dumps(results, indent=2, ensure_ascii=False))