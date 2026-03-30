FROM python:3.11-slim

WORKDIR /app

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

CMD ["python", "webmain.py"]
