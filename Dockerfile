# ---- Base image ----
FROM python:3.11-slim AS backend

# Set working directory
WORKDIR /app

# Ensure /app is on the Python path
ENV PYTHONPATH=/app

# Disable Python output buffering for clearer Fly logs
ENV PYTHONUNBUFFERED=1

# Install system dependencies (optional but prevents build errors)
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY executor/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code into container
COPY executor ./executor

# Expose FastAPI port
EXPOSE 8000

# Preflight verification and API startup
CMD ["bash", "-c", "python executor/preflight.py && uvicorn executor.api.main:app --host 0.0.0.0 --port 8000"]