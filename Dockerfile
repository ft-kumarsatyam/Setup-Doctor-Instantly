# Setup Doctor — API + optional streamable HTTP MCP on one process.
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SETUP_DOCTOR_MOUNT_MCP=1 \
    PORT=8080

COPY pyproject.toml README.md ./
COPY src ./src
COPY docs ./docs
COPY examples ./examples

RUN pip install --no-cache-dir -e ".[api,mcp]"

EXPOSE 8080

# FastAPI (+ /mcp when SETUP_DOCTOR_MOUNT_MCP=1). Auth via SETUP_DOCTOR_API_KEYS.
CMD ["sh", "-c", "uvicorn setup_doctor.surfaces.api:app --host 0.0.0.0 --port ${PORT}"]
