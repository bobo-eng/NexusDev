FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy application code first (needed for pip install -e)
COPY pyproject.toml ./
COPY README.md ./
COPY packages/ ./packages/
COPY apps/ ./apps/
COPY config/ ./config/

# Install Python dependencies
RUN pip install --no-cache-dir -e "."

# Create artifacts directory
RUN mkdir -p /app/artifacts

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Default command (can be overridden)
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
