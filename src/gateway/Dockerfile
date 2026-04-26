FROM python:3.12-slim

WORKDIR /app

COPY src/gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/gateway/main.py .
COPY src/gateway/config.py .
COPY src/gateway/models.py .
COPY src/gateway/routers/ routers/
COPY src/gateway/services/ services/

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
