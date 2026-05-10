FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc g++ libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main-service/ ./main-service/
COPY core/ ./core/

WORKDIR /app

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "main_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
