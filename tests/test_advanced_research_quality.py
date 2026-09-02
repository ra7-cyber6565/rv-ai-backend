"""Regression tests for failures exposed by the Grand Unified stress run.

These tests are intentionally about *classes of failure*, not one benchmark
answer: cross-domain axis contamination, ambiguous-keyword relevance, fake
contradictions, heading-only coverage and overconfident hypotheses.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research_engine  # noqa: F401,E402  # installs quality hardening
from research_engine import advanced_research_quality as Q  # noqa: E402
from research_engine.advanced_semantic_coverage import substantive_coverage  # noqa: E402
from research_engine.contradiction import ContradictionEngine  # noqa: E402
from research_engine.evidence_axes import axes_for  # noqa: E402
from research_engine.hypothesis import (CONF_VERY_LOW, Hypothesis,
                                        HypothesisEngine)  # noqa: E402
from research_engine.models import SourceRecord, SourceType  # noqa: E402
from research_engine.relevance import RelevanceEngine  # noqa: E402


BIG_Q = """### 1. Brain, Attention and Behaviour
Explain human dopamine reward prediction, sustained attention, digital distraction,
flow state, neuroplasticity, compulsive reward loops, cognition, learning and
long-term behaviour. Compare human experiments, longitudinal evidence, mechanisms,
limitations and counter-evidence rather than software analogies.

### 2. Consciousness, Jung and Spiritual Claims
Compare consciousness research with Jungian individuation, shadow integration,
Hermeticism, Neville Goddard and spiritual traditions. Separate subjective reports,
philosophical interpretation, neuroscience, falsifiable evidence and speculation.

### 3. Power, Strategy and Institutions
Use game theory, signalling, incentives, cooperation, elite networks, Freemasonry,
secret societies, geopolitical realism and cultural evolution. Distinguish documented
coordination from emergent incentives and unsupported conspiracy claims.

### 4. Official Records, Books and Epistemic Discipline
Examine CIA/declassified altered-consciousness records, censored or controversial
books, primary historical texts and scholarly criticism. CIA investigated X is not
CIA proved X; a banned book is not automatically true. Include source provenance.

### 5. Information, Cosmology and Long-term Agency
Use information theory, language, quantum mechanics and cosmology only where their
scientific meanings actually apply. Build a twenty-year human agency model with
causal links, uncertainty, asymmetric decisions and meaningful wellbeing.
"""


def src(title, snippet, sid="S1", peer=True):
    return SourceRecord(
        title=title,
        snippet=snippet,
        source_id=sid,
        url=f"https://example.org/{sid}",
        source_type=SourceType.PAPER,
        peer_reviewed=peer,
        connector="test",
    )


def test_cosmology_mention_does_not_activate_dark_matter_axis_pack():
    ids = {a.axis_id for a in axes_for(BIG_Q)}
    assert "rotation_curves" not in ids
    assert "cmb" not in ids
    assert any(x.startswith("facet_") for x in ids)
    assert "counter_evidence" in ids and "replication" in ids


def test_real_dark_matter_question_still_gets_domain_axes():
    q = "What evidence supports dark matter: galaxy rotation curves, lensing and CMB?"
    ids = {a.axis_id for a in axes_for(q)}
    assert "rotation_curves" in ids
    assert "lensing" in ids


def test_bilstm_attention_analogy_is_rejected_for_human_attention_facet():
    paper = src(
        "An Efficient Hybrid Bi-LSTM Attention Model for Claims Extraction",
        "Attention mechanism and bidirectional LSTM improve research-article claims "
        "classification in a deep learning architecture.",
    )
    engine = RelevanceEngine()
    score = engine.score_relevance(paper, BIG_Q)
    assert score == 0.0
    assert paper.relevance_parts["hard_rejected"] is True
    assert paper.relevance_parts["reject_dimension"] == "facet_alignment"


def test_distinctive_human_attention_source_survives_facet_gate():
    paper = src(
        "Dopamine reward prediction and sustained attention under digital distraction",
        "A longitudinal experiment in human participants measures sustained attention, "
        "reward prediction, digital distraction and cognitive control. Results show "
        "changes in attention performance and discuss neuroplastic mechanisms.",
    )
    engine = RelevanceEngine()
    score = engine.score_relevance(paper, BIG_Q)
    assert score > 0.0
    assert paper.relevance_parts["facet_alignment"]["ok"] is True


def test_different_facets_cannot_become_a_contradiction_from_polarity_words():
    a = src(
        "Digital distraction significantly reduces sustained human attention",
        "Human participants show significantly reduced sustained attention under "
        "variable reward digital distraction and dopamine-linked reward cues.",
        "S1",
    )
    b = src(
        "Claim replicability does not guarantee social responsibility in machine learning",
        "Machine learning model performance does not establish social claims; claim "
        "replicability and responsibility require different evaluation procedures.",
        "S2",
    )
    engine = ContradictionEngine()
    assert engine._normalized_proposition(a, b, BIG_Q) == ""


def test_same_facet_requires_shared_distinctive_proposition_anchor():
    a = src(
        "Digital reward cues significantly reduce sustained attention in humans",
        "Human participants exposed to digital reward cues show significantly reduced "
        "sustained attention and cognitive control during distraction.",
        "S1",
    )
    b = src(
        "Digital reward cues show no significant effect on sustained attention",
        "In human participants, digital reward cues produced no significant effect on "
        "sustained attention or cognitive control under the tested condition.",
        "S2",
    )
    engine = ContradictionEngine()
    prop = engine._normalized_proposition(a, b, BIG_Q)
    assert prop
    assert "Same question facet" in prop


def test_heading_only_answer_fails_substantive_structured_coverage():
    answer = "\n\n".join(
        f"**{i}. {title}**\nMentioned." for i, title in [
            (1, "Brain, Attention and Behaviour"),
            (2, "Consciousness, Jung and Spiritual Claims"),
            (3, "Power, Strategy and Institutions"),
            (4, "Official Records, Books and Epistemic Discipline"),
            (5, "Information, Cosmology and Long-term Agency"),
        ]
    )
    audit = substantive_coverage(BIG_Q, answer)
    assert audit["required"] is True
    assert audit["surface_complete"] is True
    assert audit["complete"] is False
    assert len(audit["substantive_missing"]) == 5


def test_substantive_sections_need_evidence_or_uncertainty_signal():
    para = (
        "[EVIDENCE] This section gives a substantive explanation of the requested "
        "mechanism, states what the source actually supports, separates inference "
        "from uncertainty, gives a limitation and explains the practical meaning. "
        "Counter-evidence is also described so the section is not one-sided."
    )
    answer = "\n\n".join(
        f"**{i}. {title}**\n{para}" for i, title in [
            (1, "Brain, Attention and Behaviour"),
            (2, "Consciousness, Jung and Spiritual Claims"),
            (3, "Power, Strategy and Institutions"),
            (4, "Official Records, Books and Epistemic Discipline"),
            (5, "Information, Cosmology and Long-term Agency"),
        ]
    )
    audit = substantive_coverage(BIG_Q, answer)
    assert audit["complete"] is True
    assert audit["items_covered"] == 5


def test_one_source_plus_uncalibrated_numeric_hypothesis_is_very_low_confidence():
    h = Hypothesis(
        statement="Weekly digital isolation improves sustained attention by 20%.",
        prediction_text="After 3 years, 500 workers show a 20% attention increase.",
        experiment="Track 500 workers for 3 years and compare attention scores.",
        falsification="Reject if the preregistered attention endpoint does not improve.",
        mechanism="Digital reward cues alter attention allocation and recovery dynamics.",
    )
    h.facts_used = ["S1"]
    rec = HypothesisEngine._confidence(
        h, gate=None, contradictions=[{"summary": "mixed evidence"}],
        counter_search_performed=True, calculations_done=False,
    )
    assert rec.band == CONF_VERY_LOW
    assert "NO_CALCULATION" in rec.reason_codes
    assert "THIN_EVIDENCE" in rec.reason_codes


def test_advanced_synthesis_contract_requires_calibrated_math_and_source_family_diversity():
    text = Q._quality_prompt_appendix(BIG_Q)
    assert "source-family diversity" in text
    assert "formula" in text and "units/dimensions" in text
    assert "SAME proposition" in text
    assert "Arbitrary effect size" in text
