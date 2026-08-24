"""Guarded one-shot patcher for question-bound evidence-manifest identity.

Run only on branch chatgpt-evidence-before-generation-20260824. It refuses to
patch an unexpected source shape and never touches claim-verification thresholds.
"""
from __future__ import annotations

from pathlib import Path

TARGET = Path("research_engine/evidence_drafting.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"STOP: {label} guard expected exactly 1 match, got {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    original = text

    text = replace_once(
        text,
        "DEFAULT_MAX_SEGMENTS = 18\n",
        "DEFAULT_MAX_SEGMENTS = 18\nMANIFEST_IDENTITY_VERSION = \"p0b-id-2\"\n",
        "identity constant",
    )

    text = replace_once(
        text,
        """class EvidenceDraftManifest:\n    question: str\n    spans: List[EvidenceDraftSpan] = field(default_factory=list)\n    evidence_first_required: bool = True\n""",
        """class EvidenceDraftManifest:\n    question: str\n    spans: List[EvidenceDraftSpan] = field(default_factory=list)\n    evidence_first_required: bool = True\n    segment_chars: int = DEFAULT_SEGMENT_CHARS\n    max_segments_per_source: int = DEFAULT_SEGMENTS_PER_SOURCE\n    max_segments: int = DEFAULT_MAX_SEGMENTS\n""",
        "manifest dataclass fields",
    )

    text = replace_once(
        text,
        """    @property\n    def manifest_sha256(self) -> str:\n        payload = [\n            (s.span_id, s.source_id, s.locator, s.passage_sha256,\n             s.passage_provenance, s.read_level_at_capture,\n             bool(s.strong_claim_eligible))\n            for s in self.spans\n        ]\n        raw = json.dumps(payload, ensure_ascii=False, separators=(\",\", \":\"))\n        return hashlib.sha256(raw.encode(\"utf-8\")).hexdigest()\n""",
        """    @property\n    def question_sha256(self) -> str:\n        \"\"\"Bind the manifest identity to the question without exposing its text.\"\"\"\n        return passage_sha256(self.question)\n\n    @property\n    def selection_policy(self) -> Dict[str, int]:\n        return {\n            \"segment_chars\": int(self.segment_chars),\n            \"max_segments_per_source\": int(self.max_segments_per_source),\n            \"max_segments\": int(self.max_segments),\n        }\n\n    @property\n    def manifest_sha256(self) -> str:\n        # Identity covers not only passage bytes but the question, selection\n        # policy and the complete compact eligibility basis. Otherwise two\n        # different research questions or quality/relevance states could share\n        # one manifest ID while meaning different things in the audit trail.\n        payload = {\n            \"identity_version\": MANIFEST_IDENTITY_VERSION,\n            \"question_sha256\": self.question_sha256,\n            \"selection_policy\": self.selection_policy,\n            \"spans\": [s.compact_dict() for s in self.spans],\n        }\n        raw = json.dumps(\n            payload, ensure_ascii=False, sort_keys=True, separators=(\",\", \":\")\n        )\n        return hashlib.sha256(raw.encode(\"utf-8\")).hexdigest()\n""",
        "manifest hash implementation",
    )

    text = replace_once(
        text,
        """        return {\n            \"schema_version\": \"p0b-1\",\n            \"evidence_first_required\": bool(self.evidence_first_required),\n            \"manifest_sha256\": self.manifest_sha256,\n""",
        """        return {\n            \"schema_version\": \"p0b-1\",\n            \"identity_version\": MANIFEST_IDENTITY_VERSION,\n            \"evidence_first_required\": bool(self.evidence_first_required),\n            \"question_sha256\": self.question_sha256,\n            \"selection_policy\": self.selection_policy,\n            \"manifest_sha256\": self.manifest_sha256,\n""",
        "compact manifest identity fields",
    )

    text = replace_once(
        text,
        """            f\"manifest_sha256={self.manifest_sha256}\",\n            \"BEGIN_PRESELECTED_EVIDENCE\",\n""",
        """            f\"identity_version={MANIFEST_IDENTITY_VERSION}\",\n            f\"question_sha256={self.question_sha256}\",\n            f\"manifest_sha256={self.manifest_sha256}\",\n            \"BEGIN_PRESELECTED_EVIDENCE\",\n""",
        "prompt identity stamps",
    )

    text = replace_once(
        text,
        """    \"\"\"Build the bounded manifest before any model-generated factual prose exists.\"\"\"\n    manifest = EvidenceDraftManifest(question=(question or \"\").strip())\n""",
        """    \"\"\"Build the bounded manifest before any model-generated factual prose exists.\"\"\"\n    # Record the effective selection policy in the manifest itself. This keeps\n    # its cryptographic identity reproducible and prevents two different\n    # preselection policies from producing an ambiguous audit ID when the\n    # selected text happens to be the same.\n    segment_chars = max(260, int(segment_chars or DEFAULT_SEGMENT_CHARS))\n    max_segments_per_source = max(1, int(\n        max_segments_per_source or DEFAULT_SEGMENTS_PER_SOURCE))\n    max_segments = max(1, int(max_segments or DEFAULT_MAX_SEGMENTS))\n    manifest = EvidenceDraftManifest(\n        question=(question or \"\").strip(),\n        segment_chars=segment_chars,\n        max_segments_per_source=max_segments_per_source,\n        max_segments=max_segments,\n    )\n""",
        "builder policy capture",
    )

    if text == original:
        raise SystemExit("STOP: no changes produced")

    # Safety guards: this patch must not alter P0-A thresholds or network behavior.
    for forbidden in ("_ENTAIL_SIM =", "_MIN_RELEVANCE =", "_MIN_QUALITY =", "requests.", "httpx"):
        if forbidden in text and forbidden not in original:
            raise SystemExit(f"STOP: unexpected forbidden token introduced: {forbidden}")

    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print("Evidence manifest identity hardening applied safely.")
    print("Identity binds: question hash + selection policy + compact eligibility basis.")
    print("Raw question/passage remain excluded from compact manifest.")


if __name__ == "__main__":
    main()
