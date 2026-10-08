# EvoStrategy — Data Flow Diagrams

These match the code as implemented (module names in brackets). GitHub renders the
Mermaid blocks as diagrams.

## Level 0 — context

```mermaid
flowchart LR
    U[Finance user<br/>uploads documents] -->|PDF, scans, DOCX, CSV/XLSX| E((EvoStrategy))
    R[Reviewer] -->|ACCEPT / REJECT / CORRECT + reason| E
    M[Manager] -->|budgets, cash balance, scenario levers| E
    E -->|review queue with evidence| R
    E -->|verified analytics, forecast, runway, what-if| M
    E -->|audit trail, evaluation report| A[Auditor / guide]
```

Everything runs on one local machine; no data leaves it unless an optional cloud
LLM (Gemini) is switched on.

## Level 1 — the four stages and the gate

```mermaid
flowchart TB
    D[(Source documents)] --> S1[1 Ingestion & OCR<br/>ingestion/service.py]
    S1 -->|SourceDocument: verbatim labels/values,<br/>per-field confidence, page images| DB1[(documents)]
    DB1 --> S2[2 Reconciliation<br/>reconciliation/orchestrator.py]
    S2 -->|links, transactions| DB2[(links / transactions)]
    S2 -->|cases: MATCHED / AUTO_RESOLVED /<br/>ESCALATED / MISSING| DB3[(reconciliation_cases)]
    DB3 --> S3[3 Human verification<br/>React workspace + /api/cases]
    S3 -->|decision + reviewer + time + reason,<br/>SHA-256 chained| DB4[(review_actions)]
    DB2 & DB3 & DB4 --> G{{Gate<br/>analytics/verified.py}}
    G -->|RECONCILED / SINGLE_SOURCE /<br/>ACCEPTED / CORRECTED only| S4[4 Analytics & forecasting<br/>analytics/*]
    G -.->|PENDING_REVIEW, QUARANTINED<br/>excluded and counted| S4
    ST[(settings: budgets,<br/>cash, headcount)] --> S4
    S4 -->|every distinct forecast + its input hash| DB5[(forecast_snapshots)]
    S4 --> UI[Dashboard: analytics, forecast,<br/>runway, what-if, evaluation]
```

## Level 2a — Stage 1 ingestion

```mermaid
flowchart LR
    F[file] --> T{type?}
    T -->|PDF| P[PyMuPDF render<br/>300 DPI]
    T -->|PNG/JPG/TIFF| O
    T -->|DOCX| X[python-docx text]
    T -->|CSV/XLSX| W[one record per row,<br/>headers = labels]
    P --> O[Tesseract OCR<br/>+ word confidences]
    O -->|"page confidence < 0.85"| C["OpenCV: denoise,<br/>Otsu binarise, deskew"]
    C -->|keep the better reading| O2[OCR text + words]
    O -->|confident| O2
    O2 --> K["optional PaddleOCR<br/>second opinion"]
    O2 --> E["extraction: Gemini / Ollama /<br/>offline rule parser"]
    X --> E
    E --> Q["field confidence =<br/>parser × own-word OCR × agreement"]
    W --> V
    Q --> V["Pydantic DocumentExtraction<br/>→ SourceDocument"]
```

## Level 2b — Stage 2 reconciliation

```mermaid
flowchart LR
    S[SourceDocuments] --> SM["semantic_mapping<br/>labels → roles, doc type"]
    SM --> N["normalization<br/>amounts, dates, ids"]
    N --> L["document_linking<br/>id: OCR-tolerant key, Jaro-Winkler ≥ 0.90<br/>entity, amount, date evidence"]
    N --> DUP[duplicate detection<br/>same id, same type]
    L --> RF["unreferenced ledger postings:<br/>unique amount+date match only"]
    L & DUP & RF --> CMP["field comparison<br/>amount ±2% · date ±7 days · entity"]
    CMP --> FOLD[fold ledger-vs-duplicate-copy<br/>into the duplicate case]
    FOLD --> CASES["cases + discrepancy types:<br/>numerical_mismatch, missing_document,<br/>entity_alias, duplicate_entry, ..."]
    N --> LC["key-field confidence < 0.60<br/>→ low_confidence_extraction"]
    LC --> CASES
    CASES --> TX["transactions = linked groups<br/>union-find"]
```

## Level 2c — Stage 3 verification and Stage 4

```mermaid
flowchart LR
    Q[open cases] --> REV[reviewer sees both sources<br/>side by side]
    REV -->|ACCEPT| ACC[transaction ACCEPTED]
    REV -->|REJECT + reason| QU[QUARANTINED, excluded]
    REV -->|CORRECT field + value + reason| COR[CORRECTED, value applied<br/>in analytics only]
    ACC & COR --> GATE[verified_transactions]
    GATE --> AGG[monthly / quarterly P&L,<br/>categories, vendors, budgets]
    GATE --> FC[linear regression + SARIMA → ensemble<br/>85% interval · holdout + rolling MAPE]
    GATE --> RW[cash history from stated balance<br/>→ LR runway projection, 85% interval]
    FC --> WI[what-if: volume, price, headcount,<br/>vendor consolidation → P&L, budget, cash]
```
