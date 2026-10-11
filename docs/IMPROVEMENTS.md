# Things to work on

Known weak spots in the current code, with the fix for each. Ordered roughly from
quickest to largest. None of these block the demo.

## Quick fixes

### 1. `POST /api/reconcile` runs without the pipeline lock

Uploads (`process_job`), the demo load and `DELETE /api/sources/...` all take
`_PIPELINE_LOCK` because every run writes the same SQLite file. `reconcile()` in
`evostrategy_backend/main.py` does not, so a reconcile started during an upload can
interleave with it.

**Fix:** wrap the call in `with _PIPELINE_LOCK:`, the same way `delete_source` does.

### 2. Two front-end/back-end contracts are matched by hand

- The Pydantic models in `evostrategy_backend/models.py` and the TypeScript types in
  `evostrategy_frontend/src/api.ts` describe the same shapes, but nothing checks that
  they agree.
- The What-if slider ranges in `WhatIfView` (`Workspace.tsx`) must equal `LEVER_LIMITS`
  in `assistant/tools.py`, or the assistant can set a value the slider cannot show.

**Fix:** generate the TypeScript types from FastAPI's `/openapi.json` (for example with
`openapi-typescript`) as part of `npm run build`. Serve `LEVER_LIMITS` from an endpoint
(or include it in `/api/assistant/status`) and build the sliders from it.

### 3. Protect the case-id format with a test

Reviewer decisions stay attached to cases only because case ids
(`pair:A|B`, `doc:X:missing-ledger`, `link:A|B`) come out identical on every
reconciliation run. Changing how an id is built in `reconciliation/orchestrator.py`
would silently detach every past review from its case.

**Fix:** add a test that runs reconciliation twice over the same documents, reviews a
case in between, and asserts the case id and its reviewed status survive.

## Medium

### 4. Uploading a second file with the same name overwrites the first

`document_id` is the file name without its extension (`_build(path.stem, ...)` in
`ingestion/service.py`), and removal deletes by `source_name`. A second
`invoice_001.pdf` from a different supplier replaces the first one's record.

**Fix:** either reject the upload when a stored document already has that name (and
tell the user), or make ids unique (for example stem plus a short hash of the file's
bytes). The second option changes case ids, so do item 3 first.

### 5. A reviewed case is not re-flagged when its evidence changes

Once a case has a review action, `upsert_cases` in `storage/registry.py` keeps the
reviewer's status even if a later run computes a different result, for example after a
new document links to the same transaction. The UI shows "engine: X" beside the
status, but nothing asks the reviewer to look again.

**Fix:** store a hash of the case's `results` when it is reviewed. On each run, if the
hash changes, mark the case "changed since review" and list it in the Review queue.

### 6. Ingestion job progress lives only in memory

`JobStore` (`evostrategy_backend/job_store.py`) is a dictionary in the server process.
Restarting the server loses job progress (results are safe in SQLite), and running
several uvicorn workers would split both the jobs and `_PIPELINE_LOCK`.

**Fix:** keep jobs in a small SQLite table, and either document the single-worker
requirement in the README or replace the thread lock with a file lock.

## Larger

### 7. Linking compares every pair of documents

`reconcile_documents` loops over all pairs, which is O(n²). It is fine for the few
hundred documents in the demo, but slows down sharply in the tens of thousands.
`reconciliation/document_linking.py` already has `generate_candidates`, which the
orchestrator does not use.

**Fix:** group documents by `identifier_match_key` and by date window first, and only
score pairs inside the same group. Keep the reference-free ledger pass as it is.

### 8. Extraction is measured on one invoice layout

Without `GEMINI_API_KEY`, everything runs on the offline rule parser and lexical
mapper. Extraction accuracy (H1) was measured on a single invoice template, and the
rule parser does not read line-item tables.

**Fix:** add invoices from at least two or three other layouts to
`evaluation_dataset/` with ground truth, re-run `scripts/evaluate_all.py`, and report
rules and Gemini results separately.
