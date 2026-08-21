# WORK_STATUS — do agent, ek repo (Claude + ChatGPT)

Niyam (intel ka instruction, 2026-08-20):

1. **Naya task shuru karne se PEHLE ye file padho.** Jo task/file doosre agent
   ke naam par hai, use edit mat karo.
2. Ek hi file par dono agent ek saath kaam nahi karenge.
3. Batch complete hone par: commit + push, phir commit SHA + changed files +
   test results report karo.
4. **₹0 hard rule** — koi paid API/model/service add ya enable nahi. Sirf
   free / open-source / free-tier. Koi chhupa hua paid fallback nahi.
5. Test offline chalte hain: `python3 test_research_engine.py` aur
   `python3 tests/test_*.py` (na pytest, na network, na API key).

Owner column: `Claude` = is session ka agent, `ChatGPT` = doosra agent,
`intel` = jo sirf intel ke computer/Railway se ho sakta hai.

## Current batch — 17-point superconductivity bug report (Owner: Claude)

| Task | Owner | Status | Files | Commit |
|---|---|---|---|---|
| §2/§5 relevance: semantic + domain-aware + hard rejection | Claude | done | `research_engine/relevance.py`, `research_engine/semantic.py`, `research_engine/domain.py` | (is batch mein) |
| §3 domain-aware connector routing | Claude | done | `research_engine/domain.py`, `research_engine/planner.py` | (is batch mein) |
| §4 structured query expansion + deterministic fallback planner | Claude | done | `research_engine/query_builder.py`, `research_engine/planner.py` | (is batch mein) |
| §6 content-based source type classification | Claude | done | `research_engine/source_kind.py`, `research_engine/connectors/paper_connector.py` | (is batch mein) |
| §7/§8 model fallback: error taxonomy + dynamic model discovery | Claude | done | `research_engine/model_errors.py`, `research_engine/gemini_reasoning.py`, `research_engine/gemini_model.py`, `tests/test_gemini_retry.py` | (is batch mein) |
| §1/§9/§10 RESEARCH INCOMPLETE status, no raw errors, no empty sections | Claude | done | `research_engine/run_status.py`, `research_engine/synthesizer.py`, `research_engine/orchestrator.py`, `research_engine/models.py`, `tests/test_pipeline_offline.py`, `tests/test_answer_structure.py`, `test_research_engine.py` | (is batch mein) |
| §11 consensus gate (6 preconditions) | Claude | done | `research_engine/consensus_gate.py`, `contradiction.py`, `synthesizer.py`, `orchestrator.py`, `models.py`, `evidence.py`, `relevance.py`, `planner.py`, `tests/test_consensus_gate.py` | (is batch mein) |
| §12 chunked/streaming large-PDF reading | Claude | done | `research_engine/content_fetcher.py`, `research_engine/processing/pdf_chunker.py` (naya), `research_engine/processing/pdf_processor.py`, `research_engine/processing/document_processor.py`, `research_engine/models.py`, `tests/test_pdf_chunking.py` (naya) | (is batch mein) |
| §13 verification checks A–E (citation/relevance/entailment/depth/quality) | Claude | done | `research_engine/claim_verification.py` (naya), `claim_labels.py`, `citation.py`, `synthesizer.py`, `orchestrator.py`, `tests/test_claim_verification.py` (naya) | (agle batch mein) |
| §14 audit denominators + honest API accounting | Claude | partly done | `research_engine/synthesizer.py`, `research_engine/gemini_reasoning.py` | — |
| §15 search rounds LLM ke bina bhi chalein | Claude | done | `research_engine/orchestrator.py`, `research_engine/planner.py`, `tests/test_search_rounds.py` (naya) | (is batch mein) |
| §16 automated tests A–I + full regression | Claude | A–I done (regression green) | `tests/test_gemini_retry.py`, `tests/test_pipeline_offline.py`, `tests/test_consensus_gate.py`, `tests/test_relevance_domain.py`, `tests/test_pdf_chunking.py` | (is batch mein) |
| §17 nine-part report back | Claude | pending | — | — |

## Naya batch — 15-point "Research Quality Hardening + Benchmark V2" (Owner: Claude)

| Task | Owner | Status | Files | Commit |
|---|---|---|---|---|
| point 3 domain-aware query planning (alag search intents per sub-domain) | Claude | done | `research_engine/planner.py`, `research_engine/query_builder.py`, `research_engine/domain.py` | (pichhle batch mein) |
| point 7 verification A–E enforce | Claude | done | `research_engine/claim_verification.py`, `research_engine/claim_labels.py`, `research_engine/synthesizer.py`, `tests/test_claim_verification.py` | (pichhle batch mein) |
| point 10/11 hypothesis quality + evidence gate | Claude | done | `research_engine/hypothesis.py`, `research_engine/synthesizer.py`, `research_engine/orchestrator.py`, `tests/test_hypothesis_quality.py` (naya) | (is batch mein) |
| point 12 maths/physics sanity checks | Claude | done | `research_engine/physics_checks.py` (naya), `research_engine/verification.py`, `research_engine/orchestrator.py`, `research_engine/synthesizer.py`, `tests/test_physics_sanity.py` (naya) | (is batch mein) |
| §15 / point 9 search round crash-safety (ek round gire to run zinda) | Claude | done | `research_engine/orchestrator.py`, `tests/test_search_rounds.py` (naya) | (is batch mein) |
| point 14 baaki regression tests (relevance, false consensus, raw-error leak, quota, incomplete) | Claude | in progress | `tests/` | — |
| point 1 superconductivity Benchmark V2 (offline runner, 10-point scorecard, 146 checks) | Claude | done | `tests/benchmark_superconductivity.py` (naya) | (is batch mein) |
| point 12 fix: "250-288 K" range ko negative temperature samajhna band | Claude | done | `research_engine/physics_checks.py` | (is batch mein) |
| point 13 fix: ledger ki wajah do-teen baar repeat hona band | Claude | done | `research_engine/requested.py` | (is batch mein) |
| point 14 §14 audit denominators + honest API accounting | Claude | partly done | `research_engine/synthesizer.py`, `research_engine/gemini_reasoning.py` | — |

Benchmark V2 chalane ka tareeka: `python3 tests/benchmark_superconductivity.py`
(poora offline — koi network, koi API key, koi paisa). Wahi superconductivity
sawal fixed fixtures par chalta hai aur 10 cheezein pakadta hai: junk source
rejection, ranking, imaandaar read-level labels, raw 429/protobuf leak, honest
status, consensus gate (support-only run par "Consensus evaluate nahi kiya ja
saka"), unit-conversion/comparison sanity, 3 poori hypotheses vs LLM-dead plan,
report ka kram (insaan pehle, audit aakhir) aur determinism (do run ka jawab
shabd-ba-shabd same).

## intel ke haath ka kaam
| Task | Owner | Status | Files | Commit |
|---|---|---|---|---|
| `git push` (sandbox GitHub tak nahi pahunch sakta) | intel | recurring | — | — |
| Railway mein naya `GEMINI_API_KEY` + live MAXIMUM test | intel | pending | Railway Variables | — |
| Android `RetrofitClient.kt` ka `BASE_URL` Railway URL par | intel | optional | `InfinityResearchAI/.../RetrofitClient.kt` | — |

## ChatGPT ke liye (is batch ke baad)

| Task | Owner | Status | Files | Commit |
|---|---|---|---|---|
| GitHub se is batch ka review + superconductivity benchmark retest | ChatGPT | waiting for push | (read-only review) | — |

## Queue — 17-point batch ke BAAD (abhi koi haath nahi lagayega)

intel ka apna instruction: *"DO NOT ADD NEW BIG FEATURES YET — fix these before
we add any advanced Scientific Discovery Engine features."* Isliye ye rows
`blocked` hain, owner khali hai — batch push aur ChatGPT review ke baad intel
tay karega kaun uthayega.

| Task | Owner | Status | Files | Commit |
|---|---|---|---|---|
| Knowledge graph mein cross-field relationships (advanced) | — (tay nahi) | blocked — 17-point batch ke baad | `research_engine/knowledge_graph.py`, `research_engine/knowledge_graph_improved.py`, `knowledge/graph.py` | — |

Jo pehle se maujood hai (nayi shuruaat nahi karni padegi): `knowledge_graph_improved.py`
mein `extract_entities_improved`, `extract_relationships_improved`,
`build_knowledge_graph` aur `find_cross_disciplinary_connections` already hain;
`knowledge_graph.py` sirf ek optional adapter hai (`related_note`, `store`,
`stats`) jo missing module par chup-chaap band ho jaata hai. Yaani "enhance" ka
matlab naya module nahi — inhi ke beech ki wiring + cross-field edges ka
scoring hai.

## Known gaps (jaan-boojh kar khule)

- **Patents connector nahi hai.** §3 "patents" ko priority connector maanta hai,
  par repo mein koi patent connector maujood nahi (papers/books/datasets/web hi
  hain). Naya connector add karna alag task hai — is batch ka hissa nahi.
- Kuch declared-but-unused packages `requirements.txt` mein hain. Inhe **hataya
  nahi gaya** (feature/dependency kabhi nahi hatate — intel ka rule).
