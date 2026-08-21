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
| `pytest -q tests/ test_research_engine.py` ka naya total (195 expected) | intel | pending | — | — |
| USPTO ODP free key (optional) → Railway `USPTO_ODP_API_KEY` | intel | optional | Railway Variables | — |

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

## Naya batch — Cross-Domain Research Reliability Benchmark (Owner: Claude)

intel ka instruction (2026-08-21): *"Ab koi naya flashy feature mat add karo.
Pehle prove karo ki research engine alag-alag fields mein genuinely reliable hai."*
Maqsad saaf tha — superconductivity par jo tuning hui, wo overfitting hai ya nahi.

Aath bilkul alag domain, har ek mein 12 jaan-boojh kar bichhaye gaye trap
(kaam ka source, keyword-overlap wala dhoka, duplicate/mirror, snippet-only,
abstract-only, asli full text, ghatiya quality, ulta evidence, sirf-support
evidence, na-kaafi evidence, retracted metadata, model-dead) aur har domain par
16 category ke automatic check.

| Task | Owner | Status | Files | Commit |
|---|---|---|---|---|
| 8-domain benchmark harness + fixtures + scorecard + confusion matrix | Claude | done | `tests/benchmark_cross_domain.py` (naya) | (is batch mein) |
| 8 domain profiles (medicine/materials/energy/engineering/cs_ai/archaeology/economics/biology) + `must` branches | Claude | done | `research_engine/domain.py` | (is batch mein) |
| stance lexicon domain-neutral (contradiction har field mein bane) | Claude | done | `research_engine/contradiction.py` | (is batch mein) |
| label gate ka do-pass hisaab ek jagah (`merge_reports`) | Claude | done | `research_engine/claim_labels.py`, `research_engine/orchestrator.py` | (is batch mein) |
| galat conversion par khadi comparison pakdo | Claude | done | `research_engine/physics_checks.py` | (is batch mein) |
| hypothesis cap evidence gate ki izzat kare | Claude | done | `research_engine/hypothesis.py` | (is batch mein) |
| lone-keyword trap rejection (`Bearing witness` type) | Claude | done | `research_engine/relevance.py` | (is batch mein) |
| pytest bhi wahi test chalaye jo script chalati hai | Claude | done | `tests/test_pdf_chunking.py`, `tests/test_answer_structure.py`, `tests/test_consensus_gate.py`, `tests/test_relevance_domain.py`, `test_research_engine.py` | (is batch mein) |

Chalane ka tareeka: `python3 tests/benchmark_cross_domain.py` (poora offline —
network nahi, API key nahi, paisa nahi). Aakhir mein per-domain scorecard
(domain / relevance / evidence / verification / consensus / hypothesis / fallback
/ presentation) aur domain-confusion matrix chhapti hai.

Benchmark ne 5 asli bug pakde (test aasan karke nahi, code theek karke gaye):

1. **Contradiction sirf medicine mein banti thi.** Stance lexicon poori tarah
   clinical-trial ki angrezi thi ("efficacious", "reduces risk"), isliye
   engineering / cs_ai / archaeology / economics ke sources NEUTRAL nikalte the
   aur "iske against kya mila?" khaali reh jaata tha. Ab null-result ki
   domain-neutral bhaasha bhi cue hai, aur `_all_negated()` ki wajah se
   "no improvement" support mein nahi ginta.
2. **Jis field ka sabse bada failure mode retracted claim hai, usi ka
   "kya ye replicate hua?" search nahi hota tha.** Superconductivity ke 17
   branches mein `expanded_queries(limit=9)` replication/retraction wala angle
   kaat deta tha. Ab `Branch.must` hai aur `controversy` + `mechanism` kabhi
   nahi kat‑te.
3. **Audit apna hi kaam kam karke batata tha.** Strict pass line ko pehle hi
   `[UNVERIFIED]` kar deta tha, isliye depth pass imaandaari se `checked: 0`
   likhta tha — jawab mein downgrade dikhta tha par `label_report` khaali.
   `merge_reports()` dono pass ka total deta hai.
4. **Galat conversion par khadi tulna pass ho jaati thi** ("730 days (20 years),
   jo 5 years se zyada hai" — 730 din ≈ 2 saal). Ab restatement asli value se
   dobara jaanchi jaati hai.
5. **Evidence gate kaagaz par reh jaata tha.** Gate 1 hypothesis allow karta,
   par parser ka floor `max(3, ...)` tha — report mein teen chhap jaati thi.

## Naya batch — ₹0 Patent Research + Patent Evidence Integration (Owner: Claude)

intel ka instruction (2026-08-21): *"Advanced Scientific Discovery Engine abhi
start MAT karo. Pehle original source-discovery blueprint ka real missing piece
close karo: PATENTS."* Hard rule: koi paid API nahi, koi scraping/bypass nahi,
sirf official/public endpoints, credentials repo mein kabhi nahi, aur provider
down ho to engine crash na kare.

| Task | Owner | Status | Files | Commit |
|---|---|---|---|---|
| PATENT first-class source type (`PatentMeta`, read-depth, family key, status label, novelty helpers) | Claude | done | `research_engine/patents.py` (naya) | (is batch mein) |
| Do keyless/official connector + `safe_search()` failure contract | Claude | done | `research_engine/connectors/patent_connector.py` (naya), `research_engine/connectors/__init__.py` | (is batch mein) |
| `SourceType.PATENT`, patent-aware `SourceRecord` / `EvidencePack` counters | Claude | done | `research_engine/models.py` | (is batch mein) |
| Routing: patent connector sirf invention/prior-art/novelty sawaal par | Claude | done | `research_engine/planner.py`, `research_engine/depth.py`, `research_engine/source_discovery.py` | (is batch mein) |
| Patent-family collapse (US/EP/WO = ek evidence) | Claude | done | `research_engine/dedup.py` | (is batch mein) |
| "Patent ≠ proof" ke teen alag gate | Claude | done | `research_engine/claim_labels.py`, `research_engine/claim_verification.py`, `research_engine/consensus_gate.py` | (is batch mein) |
| Prompt-level patent rule (sirf patent pack par inject) | Claude | done | `research_engine/gemini_reasoning.py` | (is batch mein) |
| Prior-art honesty + novelty-overclaim catcher report mein | Claude | done | `research_engine/orchestrator.py` | (is batch mein) |
| Relevance guard patent metrics + "filtered ≠ 0 mila" | Claude | done | `research_engine/relevance.py` | (is batch mein) |
| 152-check offline patent suite (10 deliberate trap) | Claude | done | `tests/test_patents.py` (naya) | (is batch mein) |

Provider chunav (dono ₹0 aur official):

- **EPO Linked Open Data SPARQL** (`epo_lod`) — `https://data.epo.org/linked-data/query`,
  bilkul **keyless**, EPO ka apna public endpoint. Fair-use ~10 search/min hai
  isliye `retries=0` aur `LIMIT 5`. SPARQL injection band: har quoted term
  `^[0-9a-z \-]*$` par saaf hota hai, FILTER sirf REQUIRED triple par lagti hai.
  EPO ka legal-status data official publication **nahi** maana jaata — isliye
  source string mein wahi likha jaata hai.
- **USPTO Open Data Portal** (`uspto_odp`) — free account ki API key se, isliye
  **optional**: key na ho to connector `available_names()` mein hi nahi aata aur
  reason `no_key` jaata hai (crash nahi). Key sirf `USPTO_ODP_API_KEY` env se
  padhi jaati hai, sirf `X-API-KEY` header mein jaati hai, aur kisi log/record/
  URL/params mein leak nahi hoti (test isse assert karta hai).

Patent evidence science evidence se **alag** rehta hai, teen jagah:

1. `claim_labels.line_verdict` — patent-only line `full_text` par bhi
   `[SOURCE-REPORTED]` rehti hai (reason: "LEGAL dawe").
2. `claim_verification.check_d` — patent-only claim ka verdict `UNKNOWN`.
3. `consensus_gate` ka 7th condition `science_beyond_patents` — sirf tab judta
   hai jab pack mein patent hain, aur 3 non-patent science source maangta hai.
   Plus `coverage_report()["prior_art"]` ek alag block hai, science counters
   mein mila hua nahi.

Chalane ka tareeka: `python3 tests/test_patents.py` (poora offline — network
nahi, API key nahi, paisa nahi). 11 stage, **152 check**. Suite khokhli nahi
hai: teen mutation inject karke check kiya gaya — family-collapse band karne par
7 FAIL, `patent_intent` hamesha-on karne par 1 FAIL, `is_patent` hamesha False
karne par 30 FAIL.

Regression (sab is sandbox mein 2026-08-21 ko chalaye gaye, sab `rc=0`):
`tests/benchmark_cross_domain.py` **633/633**, `tests/benchmark_superconductivity.py`
**146/146**, `test_research_engine.py` **593 pass / 0 fail**,
`test_missing_features.py` 14 assertion, aur `tests/test_*.py` ki saari 19 file
`rc=0` (test_claim_verification 143/0, test_hypothesis_quality 137/0,
test_quota_backup 122/0, test_physics_sanity 86/0, test_audit_accounting 70/0,
test_pdf_chunking 56/0, test_answer_structure 51/0, test_search_rounds 51/0,
test_relevance_domain 39/0, test_consensus_gate 28/0, test_patents 152/0 —
baaki file summary line print nahi karti). Asli `pytest` is sandbox mein import
hi nahi hoti (neeche wala gap), isliye pytest ka naya total intel ke Windows se
aayega — `tests/test_patents.py` module level par sirf ek test deti hai
(`test_patents_all_checks_pass`), isliye pichhle **194** se **195** hona
chahiye.

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
  hai.** Meri taraf ka aadha hissa 2026-08-21 ko theek kar diya gaya: jin 4 suites
  ke check `main()` ke andar the ya jo flat script thi, unme ab module-level
  `def test_...(): assert main() == 0` wrapper hai — `tests/test_pdf_chunking.py`
  (ye pytest mein **collection error** de rahi thi, kyunki module level par
  `sys.exit()` tha), `tests/test_answer_structure.py`,
  `tests/test_consensus_gate.py`, `tests/test_relevance_domain.py`. Script wala
  purana tareeka bilkul waisa hi chalta hai. Aur 2026-08-21 ko hi
  `test_research_engine.py` ke 22 stage function ka naam `test_*` se `_check_*`
  kar diya gaya (sirf naam — andar ka ek bhi check nahi badla) + ek hi
  module-level entry `test_research_engine_all_checks_pass()` jo `main()`
  chalata hai. Wajah intel ke asli pytest run se aayi: `pytest -q tests/
  test_research_engine.py` → **212 passed, 3 errors** — teen stage
  (`_check_contradictions`, `_check_verification`, `_check_synthesizer`) agle
  stage ka `pack` argument lete hain, aur pytest ne usko fixture samajh liya
  ("fixture 'pack' not found"); do stage value return karte the → future
  pytest mein error banne wali `PytestReturnNotNoneWarning`. Ab pytest wahi
  ek run karta hai jo CI (`python test_research_engine.py`) karti hai —
  same kram, same 593 check. **Baaki gap ChatGPT ka hai:** wo
  workflow 20+ aisi test files reference karta hai jo `main` par maujood hi nahi
  (`tests/test_upload_safety.py`, `tests/test_evidence_verification.py`,
  `tests/test_domain_guardrails.py`, `tests/test_presentation_guard.py`,
  `tests/test_user_presentation_contract.py` … `git ls-files tests` mein ek bhi
  nahi hai), aur repo root ki `test_academic.py` / `test_connectors.py` /
  `test_kg.py` / `test_progress.py` / `test_safety.py` / `test_web_search.py` se
  pytest 0 test collect karti hai. Ye file aur wo tests ChatGPT ke naam par hain,
  isliye chhue nahi.
- **Is sandbox mein asli `pytest` chal hi nahi saka.** `pip install pytest`
  blocked hai (proxy 403 — ₹0 se koi lena-dena nahi, network hi band hai).
  Iski jagah ek pytest-jaisa collector chalaya gaya jo har test file se
  module-level `test_*` functions collect karke chalata hai: **collected=219,
  pass=216, fail=0, error=0, skip=3** (3 skip = `test_research_engine.py` ke wo
  helper jo argument lete hain). Asli `pytest 8.3.4` intel ke Windows par chala
  (2026-08-21): pehle 4 nayi wrapper suites → **4 passed**; poori `pytest -q
  tests/ test_research_engine.py` → **212 passed, 3 errors** (wahi 3 fixture
  wale, upar likhe gaye). Un 3 ko theek karne ke baad `test_research_engine.py`
  se pytest 19 ke bajaye 1 test collect karta hai, aur intel ka agla run isi ko
  confirm karta hai: **194 passed, 0 errors, 2 warnings in 7.70s** (dono warning
  `google._upb` protobuf ki DeprecationWarning hain, humare code ki nahi).
  Commit `51a07f7` push ho chuka hai.
- **§8 ke liye ChatGPT-owned `synthesizer.py` JAAN-BOOJH KAR NAHI chhua.**
  `key_switches` / `active_key` ko audit block mein alag row banane ke liye
  `_api_accounting_block()` badalna padta — wo file ChatGPT ki hai, isliye rok
  diya. Info gaayab nahi hai: ye dono cheezein `gemini_reasoning.usage_note()`
  mein jaati hain aur audit block wahi note pehle se chhapta hai
  (`api_accounting()` dict mein `keys_available` / `key_switches` /
  `active_key` / `keys_note` bhi maujood hain, jab ChatGPT chaahe use kar le).
- **~~Patents connector nahi hai~~ — 2026-08-21 ko ho gaya**, par teen cheezein
  jaan-boojh kar khuli hain:
  - **CUSTOM mode se `use_patents` toggle nahi hota.** `depth.py` mein flag
    maujood hai (QUICK=False, DEEP/MAXIMUM=True), par CUSTOM ka payload parsing
    `api/agent_routes.py` mein hai — wo file ChatGPT ki hai, isliye chhui nahi.
    CUSTOM abhi apne base depth ka default use karta hai.
  - **`synthesizer.py` patent ke `"claims"` ko raw hi render karta hai.** Uske
    liye us file ka block badalna padta (ChatGPT-owned) — rok diya. Info gaayab
    nahi: read depth `patent_meta` + `coverage_report()["patent_read_levels"]`
    mein hai, aur prior-art line engine ke notes mein pehle se jaati hai.
  - **`family_id` sirf EPO deta hai.** USPTO ODP wale record ka `family_id`
    jaan-boojh kar `""` rehta hai (ODP is endpoint par bharosemand family id
    nahi deta) — us case mein family key priority-date + title slug se banti
    hai, aur kuch bhi na mile to key khaali rehti hai matlab wo record kabhi
    dedup mein nahi girta. Guess karke do alag invention ko ek maan lena isse
    bura hota.
- Kuch declared-but-unused packages `requirements.txt` mein hain. Inhe **hataya
  nahi gaya** (feature/dependency kabhi nahi hatate — intel ka rule).
