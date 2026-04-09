FROM python:3.11-slim

WORKDIR /app

# System packages: ffmpeg is required for the multi-frame video DICOM converter
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer-cached until requirements change)
COPY requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt

# Copy application source
COPY config/       config/
COPY dicom/        dicom/
COPY hl7_module/   hl7_module/
COPY hl7_templates/ hl7_templates/
COPY locales/      locales/
COPY web/          web/
COPY __version__.py webmain.py ./

# Config and logs are stored under PACS_DATA_DIR.
# Mount a volume here so data persists across container restarts.
ENV PACS_DATA_DIR=/data
VOLUME ["/data"]

EXPOSE 5000

# Use the existing /api/health endpoint to let Docker detect an unhealthy container.
# Interval: check every 30 s; allow 10 s to respond; retry 3 times before marking unhealthy.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/health')" || exit 1

CMD ["python", "webmain.py"]
