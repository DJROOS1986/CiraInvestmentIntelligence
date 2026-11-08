FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

COPY ingestion/requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt

COPY ingestion/ingest_sec.py /app/ingestion/
COPY ingestion/config.example.json /app/ingestion/
COPY portfolio-engine/ /app/portfolio-engine/
COPY scripts/07-Generate-Financial-Reports.py /app/scripts/
COPY scripts/10-Analyze-Financial-Reports.py /app/scripts/
COPY scripts/12-Run-Cloud-Pipeline.py /app/scripts/

RUN mkdir -p /app/reports/financial /app/reports/analysis

RUN useradd --create-home --uid 10001 cira \
    && chown -R cira:cira /app

USER cira

CMD ["python", "scripts/12-Run-Cloud-Pipeline.py"]

