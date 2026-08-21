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
| §14 audit denominators + honest API accounting | Claude | done | `research_engine/gemini_reasoning.py`, `research_engine/synthesizer.py`, `research_engine/orchestrator.py`, `tests/test_audit_accounting.py` (naya), `tests/test_gemini_retry.py`, `test_research_engine.py` | (is batch mein) |
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
| point 14 baaki regression tests (relevance, false consensus, raw-error leak, quota, incomplete) | Claude | done | `tests/test_relevance_domain.py`, `tests/test_evidence_honesty.py`, `tests/test_consensus_gate.py`, `tests/test_pipeline_offline.py`, `tests/test_search_rounds.py`, `tests/test_hypothesis_quality.py`, `tests/test_requested_deliverables.py`, `tests/test_audit_accounting.py` (naya) | (is batch mein) |
| point 1 superconductivity Benchmark V2 (offline runner, 10-point scorecard, 146 checks) | Claude | done | `tests/benchmark_superconductivity.py` (naya) | (is batch mein) |
| point 12 fix: "250-288 K" range ko negative temperature samajhna band | Claude | done | `research_engine/physics_checks.py` | (is batch mein) |
| point 13 fix: ledger ki wajah do-teen baar repeat hona band | Claude | done | `research_engine/requested.py` | (is batch mein) |
| point 14 §14 audit denominators + honest API accounting | Claude | done | `research_engine/gemini_reasoning.py`, `research_engine/synthesizer.py`, `research_engine/orchestrator.py`, `tests/test_audit_accounting.py` (naya) | (is batch mein) |

Benchmark V2 chalane ka tareeka: `python3 tests/benchmark_superconductivity.py`
(poora offline — koi network, koi API key, koi paisa). Wahi superconductivity
sawal fixed fixtures par chalta hai aur 10 cheezein pakadta hai: junk source
rejection, ranking, imaandaar read-level labels, raw 429/protobuf leak, honest
status, consensus gate (support-only run par "Consensus evaluate nahi kiya ja
saka"), unit-conversion/comparison sanity, 3 poori hypotheses vs LLM-dead plan,
report ka kram (insaan pehle, audit aakhir) aur determinism (do run ka jawab
shabd-ba-shabd same).

## Naya batch — §8 "Quota-proof backup: app kabhi na ruke" (Owner: Claude)

intel ki shikayat (2026-08-21): *"gimini ko call krte h to quta khatam ho jaata h
... app ruke nhi, app me koi eror na aaye ... iska quta khatam ho gya, ye kaam
nhi kiya, iss wajah se jawab thoda week rah gya ... 100% pura app working."*

Asli root cause do the:
1. Free tier ki deewar `GenerateRequestsPerDayPerProject` hai — us halat mein us
   KEY ke saare model ek saath band ho jaate the, aur model rotation (§7) kuch
   nahi kar paati thi.
2. Quota marne par orchestrator `extractive_summary()` chalata tha, jo SIRF
   `## Seedha jawab` bharta tha — baaki teen insaani section ("Research se kya
   pata chala?", "Ye kyun hota hai?", "Kya abhi unknown hai?") "kaunse hisse
   nahi ban paaye" list mein chale jaate the. Yahi "jawab week rah gya" tha.

| Task | Owner | Status | Files | Commit |
|---|---|---|---|---|
| backup FREE key rotation (per-project quota ka ₹0 ilaaj) | Claude | done | `research_engine/key_pool.py` (naya), `research_engine/gemini_model.py`, `research_engine/gemini_reasoning.py`, `.env.example` | (is batch mein) |
| offline deterministic reasoning — quota marne par bhi saare section bharein | Claude | done | `research_engine/local_reasoning.py` (naya), `research_engine/orchestrator.py` | (is batch mein) |
| QUICK chat ka dead-end khatam (key rotation + offline backup) | Claude | done | `research_engine/chat.py`, `research_engine/local_reasoning.py` | (is batch mein) |
| §8 offline test suite (98 checks) | Claude | done | `tests/test_quota_backup.py` (naya), `test_research_engine.py` (1 expectation) | (is batch mein) |
| §8b `/chat/diag` mein `key_setup` — "key daali par backup nahi laga" ka seedha jawab | Claude | done | `research_engine/key_pool.py` (`describe`, `fingerprint`), `research_engine/gemini_model.py`, `tests/test_quota_backup.py` (122 checks) | (is batch mein) |

Kaise chalta hai (teen parat, sab ₹0):

1. **Model rotation** (§7, pehle se) — ek model ka quota mare to agla model.
2. **Key rotation** (naya) — is key ke SAB model mar jaayein (daily quota / auth)
   to `GEMINI_API_KEY_2..9` / `GEMINI_API_KEYS` se agli FREE key par shift. Nayi
   key par model-memory (`_cache`/`_seen`/`_dead`) aur run ke `blocked`/`stopped`
   saaf ho jaate hain, kyunki wo faisle purani key ke the.
3. **Offline reasoning** (naya) — saari key mar jaayein to `local_reasoning.compose()`
   engine ke apne padhe hue sources se poora sectioned jawab banata hai:
   deterministic (wahi pack → shabd-ba-shabd wahi jawab), har line par `[S#]`,
   label kabhi `[ESTABLISHED]` nahi (sirf `[SOURCE-REPORTED]` / `[INFERENCE]`).

Do niyam jaan-boojh kar pakke rakhe gaye:

- **Key badalna "retry" NAHI hai.** §14 ka hisaab isse alag ginta hai. Nayi
  identity: `actual_http_attempts == (1 + key_switches) + same_model_retries +
  model_switches`. Ek hi key wale setup mein `key_switches = 0`, yaani purana
  formula jaisa ka waisa (purane test bina badle pass hote hain).
- **Key ki VALUE kabhi bahar nahi jaati.** `note`/`usage_note`/`api_accounting`/
  `diagnose` — sab jagah sirf `"free key #2"` jaisa label.
- **STATUS nahi badla.** Reasoning pass sach mein nahi chala, to report ab bhi
  imaandaari se `RESEARCH INCOMPLETE` kehti hai (`reasoning_done`/`failures`/
  `run_status` ka ek shabd nahi chhua). Farak sirf itna hai ki koi section khaali
  nahi rehta.

Verify (sab offline): `python3 tests/test_quota_backup.py` → 122/0.
Dead-run probe: quota poori mari hui MAXIMUM run ab 20,164 char ka jawab deti hai,
saari 11 heading maujood, "Kaunse hisse nahi ban paaye" block gaayab, aur status
phir bhi `RESEARCH INCOMPLETE`.

§8b (intel ne live check kiya, 2026-08-21): `GEMINI_API_KEY_2` Railway mein daalne
par bhi `/api/v1/chat/diag` `keys_available: 1` dikha raha tha. Wajah andaaze se
nahi, ab endpoint khud batata hai — `diagnose()["key_setup"]` mein
`names_present` (kaunse env NAAM sach mein dikhe), `unique_keys`,
`duplicates_dropped` aur har unique key ka 8-hex `fingerprint` (sha256 ka prefix,
ulta nahi ho sakta) aata hai. Sabse aam wajah: dono variable mein WAHI EK key —
`load_keys()` duplicate hata deta hai, kyunki quota project par lagta hai, naam
par nahi. Key ki value yahan bhi kahin nahi jaati.

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

- **⚠️ ChatGPT-owned file mein §14 ka edit hua (intel ko report kiya gaya).**
  `research_engine/synthesizer.py` ke 4 helper (`_api_accounting_block`,
  `_access_block`, `_quality_line`, `_numbers_check`) aur
  `research_engine/orchestrator.py` ka `_confidence_note` badle gaye — kyunki naye
  imaandaar counters aur denominators report mein chhapte wahin se hain. Sirf ye
  helper badle, koi feature hataya nahi gaya. Merge conflict ho to §14 ka logic
  `gemini_reasoning.api_accounting()` mein poora maujood hai; presentation dobara
  banana aasan hai.
- **Claim-label strict rule ab lagu hai, par `claim_labels.py` chhua NAHI gaya.**
  Final rule ("poora text mila par support nahi mila" → `[UNVERIFIED]`, na ki
  `SOURCE-REPORTED`) `research_engine/claim_verification.py` ke naye
  `enforce_strict_labels()` / `strict_label_line()` mein hai, aur orchestrator
  usse depth-wale downgrade se PEHLE chalata hai. `claim_labels.py` ka default
  behaviour (`check_entailment=False`, sirf reading depth) bilkul waisa hi hai —
  us file mein ek line bhi nahi badli. Regression:
  `tests/test_claim_verification.py::test_strict_label_contract`.
- **`.github/workflows/foundation-tests.yml` (ChatGPT-owned) `pytest -q` chalata
  hai**, par in suites ke test `main()` ke andar hain — pytest 0 test collect
  karke exit 5 deta hai, aur workflow un test files ko bhi reference karta hai jo
  `main` par nahi hain. Fix aasan hai (`def test_all(): assert main() == 0`
  wrapper), par wo ChatGPT ki file hai — bina permission touch nahi kiya.
- **§8 ke liye ChatGPT-owned `synthesizer.py` JAAN-BOOJH KAR NAHI chhua.**
  `key_switches` / `active_key` ko audit block mein alag row banane ke liye
  `_api_accounting_block()` badalna padta — wo file ChatGPT ki hai, isliye rok
  diya. Info gaayab nahi hai: ye dono cheezein `gemini_reasoning.usage_note()`
  mein jaati hain aur audit block wahi note pehle se chhapta hai
  (`api_accounting()` dict mein `keys_available` / `key_switches` /
  `active_key` / `keys_note` bhi maujood hain, jab ChatGPT chaahe use kar le).
- **Patents connector nahi hai.** §3 "patents" ko priority connector maanta hai,
  par repo mein koi patent connector maujood nahi (papers/books/datasets/web hi
  hain). Naya connector add karna alag task hai — is batch ka hissa nahi.
- Kuch declared-but-unused packages `requirements.txt` mein hain. Inhe **hataya
  nahi gaya** (feature/dependency kabhi nahi hatate — intel ka rule).
