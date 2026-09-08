FROM python:3.12-slim

WORKDIR /app/backend

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY . /app/backend

ENV PYTHONPATH="/app:/app/backend"

EXPOSE 8001
# Access lines come from RequestLogMiddleware (JSON, with latency + request_id).
CMD ["uvicorn", "backend.v2.main:app", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]
