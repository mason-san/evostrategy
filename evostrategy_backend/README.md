# EvoStrategy ingestion backend

This FastAPI service is the boundary between the onboarding upload screen and
the existing Python ingestion pipeline.

## Run locally

From the repository root:

```bash
venv/bin/pip install -r evostrategy_backend/requirements.txt
venv/bin/python -m uvicorn evostrategy_backend.main:app --reload --port 8000
```

The frontend expects the service at `http://127.0.0.1:8000`. Set
`VITE_API_URL` when the API runs elsewhere.

## Use a local Ollama model

Start Ollama in another terminal and inspect the installed model name:

```bash
ollama serve
ollama list
```

Then start FastAPI with the local provider:

```bash
export LLM_PROVIDER=ollama
export OLLAMA_MODEL=your-installed-model-name
venv/bin/python -m uvicorn evostrategy_backend.main:app --reload --host 127.0.0.1 --port 8000
```

Ollama defaults to `http://127.0.0.1:11434`; override it with `OLLAMA_URL` if
your local server uses another address. The Ollama response is required to be
JSON and follows the same extraction contract as the Gemini parser.

## API flow

1. `POST /api/ingestion/jobs` with one or more `files` multipart fields.
2. The service stores the upload under a generated job directory.
3. The existing PDF rasterization, OCR, extraction, and persistence functions
   run in a background task.
4. Poll `GET /api/ingestion/jobs/{job_id}` for `progress`, `steps`, processed
   file counts, timestamped `events`, and explicit failure messages.

Only PDFs are currently passed into the existing pipeline. CSV, XLSX, and DOCX
uploads are accepted by the upload boundary for future preprocessing adapters,
but currently finish with an explicit unsupported-format error rather than a
false success state.

The current onboarding job performs document receipt, PDF rasterization, OCR,
LLM extraction, Pydantic validation, and JSON persistence. Reconciliation is
not run by this upload job; the API reports that honestly as the next stage
instead of marking an unperformed reconciliation step complete.
