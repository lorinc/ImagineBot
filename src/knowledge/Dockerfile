# Build context: repo root (docker build -f src/knowledge/Dockerfile .)
# Index files are baked into the image for UAT. Future: load from registry at runtime.
FROM python:3.12-slim

WORKDIR /app

COPY src/knowledge/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/knowledge/main.py .
COPY src/knowledge/indexer/ indexer/
COPY data/index/ index/

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
