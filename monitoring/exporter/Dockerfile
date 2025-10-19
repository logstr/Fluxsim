# monitoring/exporter/Dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir fastapi uvicorn[standard] prometheus-client dnspython

WORKDIR /app
COPY app.py /app/app.py

EXPOSE 9108
HEALTHCHECK CMD wget -qO- http://127.0.0.1:9108/health || exit 1
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "9108"]
