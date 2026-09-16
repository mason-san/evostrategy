# Phase 2 Implementation Plan

Phase 2 consolidates the OCR pipeline and reconciliation work into the root
project as one local, traceable system for verified revenue intelligence.

```text
source documents -> generic extraction -> canonical mapping/linking
-> reconciliation -> human verification -> verified analytics/forecasting
```

The root project now provides shared configuration and contracts, canonical
mapping/linking, typed reconciliation rules, and a local SQLite registry
foundation.

## Current state

- Stage 1 performs PDF rasterization, Tesseract OCR, Gemini generic extraction,
  Pydantic validation, and JSON output.
- Reconciliation now has typed numeric/exact comparison rules, configurable
  tolerance, canonical mapping/linking, and an idempotent local registry.
- The former dashboard implementation is still a separate nested repository and
  uses mock records; it must be migrated to the root contracts.
- Analytics, forecasting, and deployment are not yet integrated.

## Delivery sequence

1. **Contracts and configuration** — use the root repository as the single
   source of truth; keep paths, OCR settings, tolerances, storage, and API
   configuration centralized; version source-document, canonical transaction,
   reconciliation, and review schemas with provenance.
2. **Batch ingestion** — support configured files/directories, deterministic
   reruns, persisted OCR and extraction metadata, explicit failures, and
   fixture-based extraction evaluation. Preserve raw labels and values exactly;
   do not normalize inside Stage 1.
3. **Normalization and linking** — map raw fields to canonical concepts without
   losing source fields, normalize values only for comparison, resolve aliases,
   link invoice/PO/ledger/payment records, and quarantine ambiguous/duplicate
   links with explainable confidence.
4. **Reconciliation orchestration** — compare linked canonical fields, retain
   source references and evidence, handle missing/duplicate/entity mismatch
   cases, apply field tolerances, and persist idempotent cases for review.
5. **Human verification** — migrate the Streamlit dashboard from mock data to
   the registry; show source context and discrepancy evidence; require reasons
   for rejection, validate corrections, and persist reviewer identity,
   timestamps, and actions in the shared audit store.
6. **Verified analytics and forecasting** — consume only accepted/corrected
   records; implement revenue, cost, profit, budget, discrepancy, forecasting,
   and non-mutating what-if views with source/audit drill-down.
7. **Evaluation and local deployment** — run the complete fixture flow, measure
   extraction/link/reconciliation quality and reviewer efficiency, document a
   reproducible setup, and add Docker/Compose only after local contracts are
   stable.

## Non-negotiable boundaries

- Reconciliation is a hard gate before analytics and forecasting.
- No silent correction or silent link selection; unresolved cases are visible.
- Original extraction values, source paths/pages, confidence, and pipeline
  versions remain traceable through every downstream record.
- Local SQLite/files are the initial persistence tier, isolated behind interfaces
  so deployment can evolve without rewriting business logic.

## Definition of done

A configured batch of documents can move from source files through extraction,
linking, reconciliation, review, and verified analytics without hard-coded paths.
Every comparison produces a tested, durable, auditable case, and every metric
can be traced back to the source documents and reviewer actions.
