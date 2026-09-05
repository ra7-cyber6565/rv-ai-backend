"""One isolated specialist process. No direct provider SDK generation bypass."""
from __future__ import annotations

import contextlib
import json
import os
import sys


def execute(payload, brain_factory=None):
    from .research_company import ROLES, _safe_accounting, worker_prompt
    if not isinstance(payload, dict) or payload.get("role") not in dict(ROLES):
        return {"error": "invalid_worker_input", "accounting_complete": True, "accounting": {}}
    question, evidence = payload.get("question"), payload.get("evidence")
    if (not isinstance(question, str) or not question.strip() or len(question) > 20000
            or not isinstance(evidence, str) or len(evidence) > 400000):
        return {"error": "invalid_worker_input", "accounting_complete": True, "accounting": {}}
    if brain_factory is None:
        # Absence of eligible models is a zero-call failure, not an SDK discovery
        # attempt. Child-local policy cannot enable paid fallbacks accidentally.
        from dotenv import load_dotenv
        from utils.reasoning_status import reasoning_status
        load_dotenv()
        os.environ["ZERO_COST_ONLY"] = "true"
        if not reasoning_status().get("has_model_layer_usable_now"):
            return {"error": "no_model_output", "accounting_complete": True,
                    "accounting": _safe_accounting({})}
        from .reasoning_router_integrated import ResilientReasoning
        brain_factory = ResilientReasoning
    brain = None
    try:
        brain = brain_factory(budget=1)
        answer = brain.generate(worker_prompt(payload["role"], question, evidence),
                                label="company_" + payload["role"])
        return {"answer": answer[:24000] if isinstance(answer, str) else "",
                "error": "" if answer else "no_model_output",
                "response_chars": len(answer) if isinstance(answer, str) else 0,
                "output_truncated": isinstance(answer, str) and len(answer) > 24000,
                "accounting": _safe_accounting(brain.api_accounting()), "accounting_complete": True}
    except Exception:
        # Never serialize credentials, provider bodies, local paths or tracebacks.
        return {"error": "worker_unavailable", "accounting_complete": False}


def main():
    try:
        raw = sys.stdin.read(500001)
        if len(raw) > 500000:
            raise ValueError("input_limit")
        payload = json.loads(raw)
        # SDK logging cannot corrupt the JSON protocol or leak errors to the parent.
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            result = execute(payload)
    except Exception:
        result = {"error": "worker_unavailable", "accounting_complete": False}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
