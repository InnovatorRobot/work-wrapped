# Work Wrapped – Personal & Team Dashboard
FROM python:3.12-slim

# Build-time version (default from VERSION file when building with docker compose)
ARG VERSION=1.0.0
LABEL org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.title="Work Wrapped"

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code and frontend
COPY src/ ./src/
COPY frontend/ ./frontend/
COPY run.py .
COPY VERSION .
COPY .env.example .env.example
# Include .env when present (so the image can be shared with config built-in)
COPY .env* ./
RUN test -f .env || cp .env.example .env

# Optional: run as non-root (app writes session only to memory by default)
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 5001

# .env can be mounted at runtime or passed via docker-compose env_file
CMD ["python", "run.py"]
