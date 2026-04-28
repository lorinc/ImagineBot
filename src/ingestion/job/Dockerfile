FROM python:3.12-slim
WORKDIR /app
COPY src/ingestion/requirements.txt requirements-base.txt
COPY src/ingestion/job/requirements.txt requirements-job.txt
RUN pip install --no-cache-dir -r requirements-base.txt -r requirements-job.txt
COPY src/ src/
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
CMD ["python3", "-m", "src.ingestion.job.main"]
