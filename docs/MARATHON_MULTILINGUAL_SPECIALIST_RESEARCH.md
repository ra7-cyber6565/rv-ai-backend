# Marathon Multilingual Specialist Research

## Purpose

Marathon is a bounded, durable research mode for questions that need books,
official archives, several disciplines, multilingual search and careful claim
boundaries. It is especially designed for:

- mind, cognition, consciousness, subconscious/unconscious mind and behaviour;
- Carl Jung, analytical psychology, shadow work and individuation;
- metaphysics and philosophy of mind;
- spirituality, esotericism, occult history, Hermeticism, chakras and related
  traditions;
- CIA/declassified documents and other official public records;
- Freemasonry, secret societies, New World Order and conspiracy claims;
- measured frequency/binaural-beat research versus spiritual uses of
  “frequency” or “vibration”.

It is not an “everything on the internet was read” switch. Each run remains
bounded, reports what it searched/read, and uses only legally/publicly
accessible material or user-supplied documents.

## Marathon preset

| Limit | Value |
|---|---:|
| Reasoning-call budget | 4 |
| Ranked sources used | up to 32 |
| Research rounds | up to 4 |
| Results per connector/query | up to 5 |
| Legally accessible full texts attempted | up to 12 |
| Characters supplied per source | up to 2,200 |
| Discovery wall-clock budget | 300 seconds per round |

The work runs through the durable background-job API. A browser disconnect does
not convert an ongoing job into a fake “nothing found” result. The same ₹0
provider guard and safe fallback chain used by the rest of the app still applies.

## Exact classification fix

The ordinary classifier previously used raw substring matching. That caused two
serious errors:

- `physics` matched inside `metaphysics`;
- `science` matched inside `occult sciences`.

Specialist classification now uses phrase/word boundaries. Metaphysics is
routed through philosophy/history-of-ideas research. “Occult sciences” is
handled as a historical/traditional category unless the question separately
contains a real empirical-science topic.

## Evidence lanes

The result contains a structured `specialist_research` field and a visible
“Evidence ki alag-alag lanes” section. The lanes are deliberately not
interchangeable.

| Lane | What it can establish | What it cannot establish automatically |
|---|---|---|
| Scientific / empirical evidence | measured result under a reported method | metaphysical truth or a universal causal law |
| Measured frequency evidence | signal/frequency, exposure, measurement and outcome | symbolic/spiritual “vibration” claims |
| Official / declassified document | provenance, date, release and what the document says | truth of every assertion or experiment described inside |
| Primary historical text | what a person/institution wrote in context | present-day scientific validity |
| Traditional / spiritual teaching | a real tradition, text, practice or interpretation | biomedical efficacy without suitable testing |
| Scholarly interpretation | an attributed academic analysis | the same status as a primary text or experiment |
| Allegation / conspiracy claim | the allegation, origin and available corroboration | fact merely because it is repeated or hard to disprove |
| Secondary web context | leads, background and public explanation | strong proof for a contested claim on its own |
| App-original hypothesis | a new testable synthesis | established fact, global novelty or 90–95% truth probability |
| Unknown / unresolved | an honest gap | an invented meaning or fabricated bridge |

Examples of enforced boundaries:

- “The CIA archive released a document that says X” may be supported by the
  official document. “Therefore X is scientifically true” needs independent
  evidence and cannot be inferred from the archive stamp.
- A chakra teaching can be accurately described as a traditional framework.
  A clinical effect requires suitable biomedical studies and must use a
  different lane.
- A signal at 528 Hz is a measurable frequency. A claim that it has a healing
  effect additionally needs dose/exposure, controls, outcome measurement,
  replication and adverse-effect analysis.
- A documented Freemason organization is a historical fact; a hidden-global-
  control allegation is a different claim with a different evidence burden.

## Official archive discovery

When the question actually needs declassified or institutional records, the
planner adds a maximum of three site-bounded queries from the following public
official families:

- CIA Reading Room (`cia.gov/readingroom`)
- US National Archives (`archives.gov`)
- FBI Vault (`vault.fbi.gov`)
- GovInfo (`govinfo.gov`, used as the fourth fallback scope)

These queries use the existing safe web connector and network boundary. They do
not log in, scrape private systems, bypass robots/access controls or treat a
missing result as proof that no document exists.

## Books and full text

Specialist history/tradition questions automatically request the existing book
connectors. Marathon enables Internet Archive, Open Library and Google Books
metadata/search routes, then the normal ContentFetcher attempts legally
available full text where supported.

The result still distinguishes:

- metadata only;
- search snippet;
- abstract;
- selected pages from a large document;
- complete accessible full text.

Paywalls, DRM, copyright controls and private access are never bypassed. A
catalog record does not become “book read”. A selected-page review does not
become “whole book read”.

## Multilingual behaviour

The multilingual planner always preserves the original question and records its
detected scripts. For known Hindi/Hinglish specialist terms it can make a
controlled English search seed, for example:

- `दिमाग तेज` / `dimag tej` → `cognitive performance` (search vocabulary)
- `अवचेतन मन` → `subconscious mind`
- `मानव व्यवहार` → `human behavior`
- `सात चक्र` → `seven chakras`
- `साजिश सिद्धांत` → `conspiracy theories`

This is explicitly called `glossary_assisted_search_only`; it is not presented
as a complete translation of a sentence, chapter or book. For an unsupported
language/script the plan says
`translation_required_for_semantic_full_text_review`. Any later translation
must keep the original passage beside it, and the app must say when it could not
reliably interpret the text.

## App-original hypotheses

Source findings and app-generated hypotheses are not mixed. The visible section
is `## APP ORIGINAL RESEARCH LAB` (renamed from the older “Humari Hypotheses”
heading by §20 of the research upgrade, so the heading itself says whose idea it
is) and it remains system-owned. Every accepted hypothesis is
an `UNTESTED HYPOTHESIS` and must carry, where evidence permits:

- the source-grounded starting facts;
- the gap the cited sources do not directly answer;
- the proposed mechanism/reasoning chain;
- supporting and counter-evidence;
- assumptions and risks;
- a measurable prediction;
- the required experiment or simulation;
- a falsification/rejection condition;
- what it would mean if the result is positive or negative;
- calibrated confidence wording.

The engine is not allowed to invent a 90–95% chance that a hypothesis is true or
will work. A literature-only search is also not allowed to claim global novelty.

## API and UI

The durable endpoint accepts:

```json
{
  "question": "CIA Gateway document aur consciousness claims ko evidence lanes mein research karo",
  "project_id": "<private project id>",
  "depth_mode": "MARATHON"
}
```

The web UI exposes a `Marathon` button. Progress uses real stages, and the
browser allows a longer wait while the server-side job remains durable.

Important structured result fields:

- `specialist_research.profiles`
- `specialist_research.lanes`
- `specialist_research.multilingual`
- `specialist_research.official_archive_queries`
- `specialist_research.hypothesis_policy`
- ordinary `hypotheses`, `coverage`, `verification`, `citations` and
  `requested_ledger` fields remain backward compatible.

## Known honest limits

- No single run reads every book, language or archive record in existence.
- Search-engine or public-API coverage can be incomplete or rate-limited.
- A model may understand many languages, but unsupported translation must be
  disclosed rather than guessed.
- Official documents can contain raw reports, proposals, errors, opinions or
  unreplicated experiments.
- Historical/spiritual meaning and empirical efficacy are different questions.
- A generated hypothesis is a research direction until a real test supports it.

