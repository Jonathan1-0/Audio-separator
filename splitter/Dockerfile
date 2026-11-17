# Servidor web de Splitter (API + página). La separación corre en la GPU de Modal,
# así que esta imagen no lleva modelos ni CUDA: solo Python y ffmpeg.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 splitter

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=splitter:splitter app ./app
COPY --chown=splitter:splitter frontend ./frontend
COPY --chown=splitter:splitter migraciones ./migraciones
COPY --chown=splitter:splitter alembic.ini modal_app.py ./
RUN mkdir -p /app/data && chown splitter:splitter /app/data

USER splitter
ENV SPLITTER_DATA_DIR=/app/data \
    SPLITTER_BEHIND_PROXY=1 \
    PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
