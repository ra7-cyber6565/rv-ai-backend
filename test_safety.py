from safety.checks import check_safety
import json

print(json.dumps(check_safety("Cancer ki dawa kya hai?"), indent=2, ensure_ascii=False))
print(json.dumps(check_safety("Bharat ki rajdhani kya hai?"), indent=2, ensure_ascii=False))