# EvoStrategy — single-workstation ("shoebox") image.
# Stage 1 builds the React workspace; stage 2 runs the API, pipeline and UI.

FROM node:22-slim AS frontend
WORKDIR /app/evostrategy_frontend
COPY evostrategy_frontend/package.json evostrategy_frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY evostrategy_frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EVOSTRATEGY_DATA_DIR=/data \
    LLM_PROVIDER=auto
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=frontend /app/evostrategy_frontend/dist ./evostrategy_frontend/dist
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "evostrategy_backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
