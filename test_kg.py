from knowledge.graph import extract_and_store, get_entity_graph, get_related_knowledge
import json

sample_answer = """Pabuji Rajasthan ke lok devta hain. Unka janam Kolu gaon mein hua tha, jo Jodhpur ke paas hai.
Unke pita ka naam Dhandalji tha. Pabuji ne apni ghodi Kesar Kalami par sawar hokar Jindrao Khichi se yudh kiya.
Ye ghatna Rajasthan ke itihas mein bahut mashoor hai."""

result = extract_and_store("Pabuji ke baare mein bataiye", sample_answer, "kgtest2")
print("=== Extraction Result ===")
print(json.dumps(result, indent=2, ensure_ascii=False))

print("\n=== Full Knowledge Graph ===")
print(json.dumps(get_entity_graph("kgtest2"), indent=2, ensure_ascii=False))