# Resumable multilingual book/PDF reading

## What this closes

The ordinary upload path is intentionally one-shot.  A very large PDF may be
sampled across its beginning, middle and end so one request stays bounded.  That
is useful for immediate research, but it is not the same as patiently covering
every page over several sessions.

The resumable reading API preserves a caller-supplied PDF under the configured
Infinity data root and advances through sequential, bounded page batches.  Its
durable project-private ledger records:

- SHA-256 and byte length of the exact preserved file;
- user-declared title, author, edition, publication year and identifier;
- safe public source URL, legal-access basis and provenance warnings;
- original and review languages plus translation-review status;
- exact inspected, native-text, OCR-text, unreadable, pending-translation and
  vector-indexed page ranges;
- separate next-uninspected and next-index-retry pointers, so a temporary
  vector-store failure cannot silently skip an earlier page batch;
- per-batch OCR and indexing receipts; and
- the next page from which another session will resume.

The stored file and ledger are isolated behind the same opaque project
capability as research/chat data.  Public responses never include filesystem
paths or raw processor/storage exceptions.

## Honest status vocabulary

| Status | Meaning |
|---|---|
| `CREATED_NOT_INSPECTED` | PDF was preserved but no page was processed yet. |
| `PROCESSING_BLOCKED` | PDF is preserved and resumable, but the local PDF processor/file cannot currently yield pages. |
| `IN_PROGRESS` | Only part of the page range has been inspected. |
| `PAGE_INSPECTION_COMPLETE_WITH_UNREADABLE_GAPS` | Every page was attempted, but one or more pages still have no usable native/OCR text. |
| `TEXT_INGESTED_TRANSLATION_REVIEW_PENDING` | Original text is preserved/indexed, but target-language semantic translation review is incomplete. |
| `TEXT_EXTRACTED_INDEXING_INCOMPLETE` | Text was extracted, but vector indexing did not finish. |
| `FULL_DOCUMENT_TEXT_INGESTED` | Every page yielded text and indexing finished. This still does not automatically prove human/model comprehension. |

`FULL_DOCUMENT_TEXT_INGESTED` is deliberately not named “book understood”.
Catalog metadata is not a read; extraction is not comprehension; machine-
assisted translation is not human verification.

## API lifecycle

1. Create `/api/v1/session` and retain its `project_id` plus
   `X-Project-Token` capability.
2. Multipart POST the legal/user-supplied PDF to
   `/api/v1/reading-sessions/start`.  Include edition/language/provenance fields
   where known.  The endpoint is capped at a 60 MiB file / 64 MiB raw body and
   processes at most 100 pages per call.
3. POST `/api/v1/reading-sessions/{session_id}/resume` with `project_id`,
   `batch_pages` and `use_ocr`.  It starts at the first page absent from the
   durable inspected-page ranges.
4. GET `/api/v1/reading-sessions/{session_id}?project_id=...` for the exact
   progress ledger, or GET `/api/v1/reading-sessions?project_id=...` for bounded
   session summaries.

All four routes require the matching project capability.  Resume uses a
cross-process session lock; state is replaced atomically; the PDF hash is
verified again before every batch; and deterministic vector IDs make a retry
idempotent when a crash happens around indexing.

## Language and translation boundary

`original_language` and `review_language` accept bounded BCP-47-like tags such
as `hi`, `en`, `sa`, `ur` or `de`.  The current engine preserves and indexes
original extracted/OCR text.  It records one of:

- `not_required_same_language`;
- `pending_semantic_translation_review`;
- `machine_assisted_unverified`; or
- `human_verified`.

Different original/review languages cannot be labelled
`not_required_same_language`.  The existing multilingual glossary may generate
search terms, but this ledger never upgrades glossary assistance to full-text
translation. `human_verified` additionally requires a non-empty
`translation_evidence_id`; both the label and reference remain explicitly
user-declared until an independent verification workflow exists.

## Access and safety boundary

Accepted access labels are `user_owned_copy`, `public_domain`, `open_license`,
`official_public_record`, `permission_granted` and
`unknown_user_supplied`. They are caller declarations, not independent legal
verification. The app does not discover or download arbitrary copyrighted
books through this API, does not bypass passwords/DRM/paywalls, and does not
redistribute the preserved PDF.

## Current limits

- Resumable, exact page-range progression is PDF-only. Existing one-shot upload
  continues to support DOCX, TXT, Markdown, HTML, transcripts and ordinary PDFs.
- OCR depends on local Tesseract language data. Failed OCR remains an explicit
  unreadable page gap.
- Translation execution/verification is not invented. A later translator or
  human review stage can update the status only when it preserves original
  passages and produces its own auditable provenance.
- A project keeps at most 32 active reading sessions and 256 recent batch
  receipts per session. This bounds disk/ledger growth; archival/deletion policy
  remains an explicit operator action.
